"""Enregistrement et lecture des coûts réels (voir `app.core.metering`)."""

import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.metering import KIND_ACTION, KIND_LLM, KIND_SEARCH, UsageMeter
from app.db.engine import Database
from app.db.schema import cost_usage

logger = logging.getLogger("facts.costs")
MAX_DAYS = 90
_PK = ["day", "profile", "operation", "kind", "name"]
_SUMMED = ["calls", "errors", "prompt_tokens", "completion_tokens", "credits"]


class CostRecorder:
    def __init__(self, db: Database, meter: UsageMeter) -> None:
        self._db, self._meter = db, meter
        self._lock = asyncio.Lock()

    async def flush(self) -> int:
        """Écrit les compteurs en attente (additif : plusieurs instances ou redémarrages ne s'écrasent pas)."""
        async with self._lock:
            taken = self._meter.take()
            if not taken:
                return 0
            rows = [
                {
                    "day": day, "profile": profile, "operation": op, "kind": kind, "name": name,
                    "calls": c.calls, "errors": c.errors, "prompt_tokens": c.prompt_tokens,
                    "completion_tokens": c.completion_tokens, "credits": c.credits,
                }
                for (day, profile, op, kind, name), c in taken.items()
            ]
            try:
                stmt = insert(cost_usage).values(rows)
                stmt = stmt.on_conflict_do_update(
                    index_elements=_PK, set_={col: cost_usage.c[col] + stmt.excluded[col] for col in _SUMMED}
                )
                async with self._db.session() as s:
                    await s.execute(stmt)
            except Exception:  # noqa: BLE001 - la mesure ne doit jamais gêner le service ; on retentera
                self._meter.restore(taken)
                logger.warning("écriture des coûts impossible, nouvel essai au prochain cycle")
                return 0
            return len(rows)

    async def run(self, interval: float) -> None:
        while True:
            await asyncio.sleep(interval)
            await self.flush()

    async def report(self, days: int, prices: dict[str, dict[str, list[float]]], today: Callable[[], date] | None = None) -> dict[str, Any]:
        days = max(1, min(days, MAX_DAYS))
        end = (today or (lambda: datetime.now(timezone.utc).date()))()
        start = end - timedelta(days=days - 1)
        async with self._db.session() as s:
            rows = (await s.execute(select(cost_usage).where(cost_usage.c.day >= start, cost_usage.c.day <= end))).mappings().all()
        return build_report(rows, prices, start, end)


def _cost(row: Any, prices: dict[str, dict[str, list[float]]]) -> tuple[float, bool]:
    """(coût en €, tarif connu ?). Un modèle sans tarif compte 0 et est signalé, jamais deviné."""
    if row["kind"] == KIND_LLM:
        p = prices["llm"].get(row["name"])
        if p is None:
            return 0.0, False
        return (row["prompt_tokens"] * p[0] + row["completion_tokens"] * p[1]) / 1_000_000, True
    if row["kind"] == KIND_SEARCH:
        p = prices["search"].get(row["name"])
        if p is None:
            return 0.0, row["credits"] == 0  # un moteur sans crédit consommé n'a pas besoin de tarif
        return row["credits"] * p[0], True
    return 0.0, True


def build_report(rows: Any, prices: dict[str, dict[str, list[float]]], start: date, end: date) -> dict[str, Any]:
    ops: dict[str, dict[str, Any]] = defaultdict(lambda: {"actions": 0, "llm_calls": 0, "llm_errors": 0, "prompt_tokens": 0, "completion_tokens": 0, "search_calls": 0, "search_credits": 0, "cost_eur": 0.0})
    per_day: dict[str, float] = defaultdict(float)
    unpriced: set[str] = set()
    for row in rows:
        o = ops[row["operation"]]
        cost, known = _cost(row, prices)
        if not known:
            unpriced.add(f"{row['kind']}:{row['name']}")
        o["cost_eur"] += cost
        per_day[row["day"].isoformat()] += cost
        if row["kind"] == KIND_ACTION:
            o["actions"] += row["calls"]
        elif row["kind"] == KIND_LLM:
            o["llm_calls"] += row["calls"]
            o["llm_errors"] += row["errors"]
            o["prompt_tokens"] += row["prompt_tokens"]
            o["completion_tokens"] += row["completion_tokens"]
        elif row["kind"] == KIND_SEARCH:
            o["search_calls"] += row["calls"]
            o["search_credits"] += row["credits"]
    operations = {}
    for name, o in sorted(ops.items()):
        o["cost_eur"] = round(o["cost_eur"], 6)
        o["cost_per_action_eur"] = round(o["cost_eur"] / o["actions"], 6) if o["actions"] else None
        operations[name] = o
    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "total_cost_eur": round(sum(o["cost_eur"] for o in operations.values()), 6),
        "per_day_eur": {d: round(v, 6) for d, v in sorted(per_day.items())},
        "operations": operations,
        "unpriced": sorted(unpriced),
    }
