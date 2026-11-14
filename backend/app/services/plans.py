"""Plans accordés à la main (licence Edu, vendue sur devis) et plan effectif d'un compte.

Un plan accordé prime sur l'abonnement en ligne. Il a une date de fin facultative : passé cette date il ne donne
plus rien, sans intervention. Toute erreur de lecture retombe sur le plan en ligne (« pro » / « free ») : on
n'accorde jamais Edu par défaut.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.engine import Database
from app.db.schema import plan_grants, users

logger = logging.getLogger("facts.plans")

CACHE_SECONDS = 60.0
KNOWN_PLANS = ("edu",)


@dataclass(frozen=True)
class Grant:
    user_id: UUID
    plan: str
    check_pool: int | None
    expires_at: datetime | None


class UnknownAccountError(Exception):
    pass


class PlanService:
    def __init__(
        self,
        db: Database,
        billing: Any | None,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._db, self._billing, self._clock, self._mono = db, billing, clock, monotonic
        self._cache: dict[UUID, tuple[float, Grant | None]] = {}

    async def grant_of(self, user_id: UUID) -> Grant | None:
        """Licence en cours du compte (None si aucune, échue, ou lecture impossible). Cache 60 s."""
        hit = self._cache.get(user_id)
        if hit is not None and self._mono() < hit[0]:
            return hit[1]
        try:
            async with self._db.session() as s:
                row = (await s.execute(select(plan_grants).where(plan_grants.c.user_id == user_id))).mappings().first()
        except Exception:  # noqa: BLE001
            logger.warning("lecture des licences impossible : plan en ligne par défaut")
            return None
        grant = None
        if row is not None and row["plan"] in KNOWN_PLANS and (row["expires_at"] is None or row["expires_at"] > self._clock()):
            grant = Grant(row["user_id"], row["plan"], row["check_pool"], row["expires_at"])
        if len(self._cache) > 2000:
            self._cache.clear()
        self._cache[user_id] = (self._mono() + CACHE_SECONDS, grant)
        return grant

    async def plan_of(self, user_id: UUID) -> str:
        grant = await self.grant_of(user_id)
        if grant is not None:
            return grant.plan
        return await self._billing.plan_of(user_id) if self._billing is not None else "free"

    # ---------- administration ----------
    async def grant(self, email: str, plan: str, *, check_pool: int | None, days: int | None, note: str | None) -> dict[str, Any]:
        if plan not in KNOWN_PLANS:
            raise ValueError("plan inconnu")
        expires = self._clock() + timedelta(days=days) if days is not None else None
        async with self._db.session() as s:
            user_id = (await s.execute(select(users.c.id).where(users.c.email == email.strip().lower()))).scalar_one_or_none()
            if user_id is None:
                raise UnknownAccountError(email)
            values = {"user_id": user_id, "plan": plan, "check_pool": check_pool, "expires_at": expires, "note": note}
            stmt = pg_insert(plan_grants).values(**values).on_conflict_do_update(
                index_elements=[plan_grants.c.user_id], set_={k: v for k, v in values.items() if k != "user_id"}
            )
            await s.execute(stmt)
        self._cache.pop(user_id, None)
        return {"user_id": str(user_id), "plan": plan, "check_pool": check_pool, "expires_at": expires.isoformat() if expires else None}

    async def revoke(self, email: str) -> bool:
        async with self._db.session() as s:
            user_id = (await s.execute(select(users.c.id).where(users.c.email == email.strip().lower()))).scalar_one_or_none()
            if user_id is None:
                return False
            deleted = (await s.execute(delete(plan_grants).where(plan_grants.c.user_id == user_id))).rowcount
        self._cache.pop(user_id, None)
        return bool(deleted)

    async def listing(self) -> list[dict[str, Any]]:
        async with self._db.session() as s:
            rows = (
                await s.execute(
                    select(users.c.email, plan_grants.c.plan, plan_grants.c.check_pool, plan_grants.c.expires_at, plan_grants.c.note)
                    .join(users, users.c.id == plan_grants.c.user_id)
                    .order_by(plan_grants.c.created_at)
                )
            ).mappings().all()
        now = self._clock()
        return [
            {"email": r["email"], "plan": r["plan"], "check_pool": r["check_pool"], "note": r["note"],
             "expires_at": r["expires_at"].isoformat() if r["expires_at"] else None,
             "active": r["expires_at"] is None or r["expires_at"] > now}
            for r in rows
        ]
