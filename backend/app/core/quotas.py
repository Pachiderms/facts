"""Quotas quotidiens (fenêtre = jour UTC), durables quand une base est configurée.

Pourquoi pas en mémoire seule : l'hébergeur gratuit s'endort et redémarre, ce qui remettait tous les
compteurs à zéro (et laissait n'importe qui dépasser sa limite en attendant un redémarrage).

  * `consume` est atomique (un seul UPSERT conditionnel) : pas de dépassement sous concurrence.
  * Les clés sont des empreintes salées (HMAC) : la base ne contient jamais d'adresse IP en clair.
  * Base indisponible : repli sur la mémoire (on ne bloque personne et on ne perd pas la protection).
"""

import hashlib
import hmac
import logging
import secrets
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from typing import Protocol

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.engine import Database
from app.db.schema import usage_counters

logger = logging.getLogger("facts.quotas")

PURGE_EVERY = 500  # écritures entre deux purges des anciens jours


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def seconds_until_next_day(now: datetime) -> int:
    nxt = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    return max(1, int((nxt - now).total_seconds()) + 1)


class QuotaStore(Protocol):
    async def consume(self, kind: str, key: str, limit: int) -> bool: ...
    async def used(self, kind: str, key: str) -> int: ...
    def retry_after(self) -> int: ...


class MemoryQuotas:
    def __init__(self, clock: Callable[[], datetime] = _utc_now, max_keys: int = 50_000) -> None:
        self._clock, self._max = clock, max_keys
        self._counts: dict[tuple[str, str], tuple[date, int]] = {}

    def _count(self, kind: str, key: str) -> int:
        item = self._counts.get((kind, key))
        return item[1] if item is not None and item[0] == self._clock().date() else 0

    async def consume(self, kind: str, key: str, limit: int) -> bool:
        today = self._clock().date()
        if self._count(kind, key) >= limit:
            return False
        if (kind, key) not in self._counts and len(self._counts) >= self._max:
            for k in [k for k, (d, _) in self._counts.items() if d != today] or [next(iter(self._counts))]:
                del self._counts[k]
        self._counts[(kind, key)] = (today, self._count(kind, key) + 1)
        return True

    async def used(self, kind: str, key: str) -> int:
        return self._count(kind, key)

    def retry_after(self) -> int:
        return seconds_until_next_day(self._clock())


class PostgresQuotas:
    """Compteurs en base, repli mémoire si elle est injoignable."""

    def __init__(self, db: Database, fallback: MemoryQuotas | None = None, clock: Callable[[], datetime] = _utc_now) -> None:
        self._db, self._clock = db, clock
        self._fallback = fallback or MemoryQuotas(clock)
        self._writes = 0

    async def consume(self, kind: str, key: str, limit: int) -> bool:
        stmt = (
            pg_insert(usage_counters)
            .values(kind=kind, key=key, day=self._clock().date(), count=1)
            .on_conflict_do_update(
                index_elements=[usage_counters.c.kind, usage_counters.c.key, usage_counters.c.day],
                set_={"count": usage_counters.c.count + 1},
                where=usage_counters.c.count < limit,
            )
            .returning(usage_counters.c.count)
        )
        try:
            async with self._db.session() as s:
                granted = (await s.execute(stmt)).first() is not None
                self._writes += 1
                if self._writes % PURGE_EVERY == 0:
                    await s.execute(delete(usage_counters).where(usage_counters.c.day < self._clock().date() - timedelta(days=1)))
            return granted
        except Exception:  # noqa: BLE001 - détail (hôte, mot de passe) jamais journalisé
            logger.warning("quotas : base injoignable, repli sur la mémoire")
            return await self._fallback.consume(kind, key, limit)

    async def used(self, kind: str, key: str) -> int:
        try:
            async with self._db.session() as s:
                row = (
                    await s.execute(
                        select(usage_counters.c.count).where(
                            usage_counters.c.kind == kind, usage_counters.c.key == key, usage_counters.c.day == self._clock().date()
                        )
                    )
                ).first()
            return int(row[0]) if row else 0
        except Exception:  # noqa: BLE001
            logger.warning("quotas : base injoignable, repli sur la mémoire")
            return await self._fallback.used(kind, key)

    def retry_after(self) -> int:
        return seconds_until_next_day(self._clock())


def make_key(salt: str, raw: str) -> str:
    """Empreinte salée (HMAC-SHA256 tronquée) : une IP ne se retrouve pas par force brute sans le sel."""
    return hmac.new(salt.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def random_salt() -> str:
    return secrets.token_hex(16)
