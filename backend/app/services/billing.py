"""Abonnement Pro : état par compte, application idempotente des évènements du prestataire, plan effectif.

Règle d'accès : Pro tant que l'abonnement est actif (ou en essai) et sa période non échue, avec quelques jours de
tolérance pour un retard de paiement ; un abonnement résilié reste Pro jusqu'à la fin de la période déjà payée.
Toute erreur de lecture retombe sur « free » : on ne donne jamais Pro par défaut.
"""

import logging
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from app.adapters.lemonsqueezy import PROVIDER, SubscriptionEvent
from app.db.engine import Database
from app.db.schema import billing_events, subscriptions

logger = logging.getLogger("facts.billing")

PLAN_CACHE_SECONDS = 60.0
ENTITLED_WHILE_PAID = {"on_trial", "active", "past_due"}


def is_entitled(status: str, period_end: datetime | None, now: datetime, grace: timedelta) -> bool:
    if status in ENTITLED_WHILE_PAID:
        return period_end is None or now <= period_end + grace
    if status == "cancelled":  # résilié : accès jusqu'à la fin de la période payée, sans tolérance
        return period_end is not None and now <= period_end
    return False  # paused, unpaid, expired


class BillingService:
    def __init__(
        self,
        db: Database,
        *,
        grace_days: int = 3,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._db, self._grace, self._clock, self._mono = db, timedelta(days=grace_days), clock, monotonic
        self._cache: dict[UUID, tuple[float, str]] = {}

    async def plan_of(self, user_id: UUID) -> str:
        """« pro » ou « free » (mis en cache 60 s : une requête par action ne doit pas coûter une lecture en base)."""
        hit = self._cache.get(user_id)
        if hit is not None and self._mono() < hit[0]:
            return hit[1]
        try:
            info = await self.status(user_id)
        except Exception:
            logger.warning("lecture de l'abonnement impossible : plan gratuit par défaut")
            return "free"
        plan = "pro" if info["active"] else "free"
        if len(self._cache) > 2000:
            self._cache.clear()
        self._cache[user_id] = (self._mono() + PLAN_CACHE_SECONDS, plan)
        return plan

    async def status(self, user_id: UUID) -> dict[str, Any]:
        async with self._db.session() as s:
            row = (await s.execute(select(subscriptions).where(subscriptions.c.user_id == user_id))).mappings().first()
        if row is None:
            return {"active": False, "status": None, "current_period_end": None, "portal_url": None}
        active = is_entitled(row["status"], row["current_period_end"], self._clock(), self._grace)
        end = row["current_period_end"]
        return {
            "active": active,
            "status": row["status"],
            "current_period_end": end.isoformat() if end else None,
            "portal_url": row["portal_url"],
        }

    async def apply(self, event_id: str, event: SubscriptionEvent) -> str:
        """« applied » | « duplicate » (déjà traité) | « stale » (plus ancien que l'état connu) | « ignored »."""
        values = {
            "provider": PROVIDER,
            "provider_subscription_id": event.subscription_id,
            "provider_customer_id": event.customer_id,
            "status": event.status,
            "current_period_end": event.period_end,
            "portal_url": event.portal_url,
            "event_at": event.event_at,
        }
        result = "applied"
        try:
            async with self._db.session() as s:
                try:
                    async with s.begin_nested():
                        await s.execute(pg_insert(billing_events).values(event_id=event_id))
                except IntegrityError:
                    return "duplicate"
                known = (
                    await s.execute(select(subscriptions.c.event_at).where(subscriptions.c.user_id == event.user_id))
                ).scalar_one_or_none()
                if known is not None and event.event_at < known:
                    return "stale"
                stmt = pg_insert(subscriptions).values(user_id=event.user_id, **values)
                stmt = stmt.on_conflict_do_update(index_elements=[subscriptions.c.user_id], set_=values)
                await s.execute(stmt)
        except IntegrityError:
            # Compte inconnu (clé étrangère) ou abonnement déjà rattaché à un autre compte : rien n'est enregistré.
            logger.warning("évènement d'abonnement refusé (compte inconnu ou abonnement déjà rattaché)")
            return "ignored"
        self._cache.pop(event.user_id, None)
        return result
