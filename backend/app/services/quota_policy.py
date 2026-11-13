"""Politique de quotas : combien de vérifications (chatbot) et de messages vérifiés (débat) par jour et par plan.

Deux budgets distincts par personne : le débat ne mange pas le quota du chatbot, et inversement.
Un budget global du débat réserve le reste du plafond d'appels LLM au chatbot.
"""

from dataclasses import dataclass

from app.core.config import Settings
from app.core.quotas import QuotaStore, make_key

GLOBAL_KEY = "all"


@dataclass(frozen=True)
class Who:
    plan: str  # "anonymous" | "free" | "pro"
    key: str  # clé principale : empreinte de l'IP (anonyme) ou du compte
    ip_key: str  # empreinte de l'IP : filet commun contre la multiplication de comptes


class QuotaPolicy:
    def __init__(self, store: QuotaStore, settings: Settings, salt: str) -> None:
        self.store, self._s, self._salt = store, settings, salt

    def anonymous(self, ip: str) -> Who:
        k = make_key(self._salt, "ip:" + ip)
        return Who("anonymous", k, k)

    def account(self, account_id: str, ip: str, plan: str = "free") -> Who:
        return Who("pro" if plan == "pro" else "free", make_key(self._salt, "acct:" + account_id), make_key(self._salt, "ip:" + ip))

    # ---------- limites ----------
    def check_limit(self, who: Who) -> int:
        return {"pro": self._s.pro_daily_check_limit, "free": self._s.account_daily_check_limit}.get(who.plan, self._s.daily_check_limit)

    def debate_limit(self, who: Who) -> int:
        return {"pro": self._s.pro_debate_daily_checks, "free": self._s.account_debate_daily_checks}.get(who.plan, self._s.debate_daily_checks)

    # ---------- consommation ----------
    async def consume_check(self, who: Who) -> bool:
        if who.plan == "anonymous":
            return await self.store.consume("check", who.key, self._s.daily_check_limit)
        return await self.store.consume("check", who.key, self.check_limit(who)) and await self.store.consume(
            "check_ip", who.ip_key, self._s.daily_check_limit * 4
        )

    async def consume_debate(self, who: Who) -> bool:
        """Un message de débat qui déclenche une vérification (appel LLM + recherche)."""
        if not await self.store.consume("debate", who.key, self.debate_limit(who)):
            return False
        if who.plan != "anonymous" and not await self.store.consume("debate_ip", who.ip_key, self._s.debate_daily_checks * 4):
            return False
        return await self.store.consume("debate_global", GLOBAL_KEY, self._s.debate_global_daily_checks)

    # ---------- lecture ----------
    async def usage(self, who: Who) -> dict:
        check_used = await self.store.used("check", who.key)
        debate_used = await self.store.used("debate", who.key)
        c, d = self.check_limit(who), self.debate_limit(who)
        return {
            "plan": who.plan,
            "checks": {"used": check_used, "limit": c, "remaining": max(0, c - check_used)},
            "debate": {"used": debate_used, "limit": d, "remaining": max(0, d - debate_used)},
        }
