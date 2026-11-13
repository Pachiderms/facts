"""Politique de quotas : combien de vérifications (chatbot) et de messages vérifiés (débat) par jour et par plan.

Deux budgets distincts par personne : le débat ne mange pas le quota du chatbot, et inversement.
Un budget global du débat réserve le reste du plafond d'appels LLM au chatbot.

Continuité connecté / déconnecté : le navigateur (jeton anonyme) porte un compteur « personne » qui compte TOUTES
ses utilisations, en anonyme comme en compte. L'usage vu par une personne est le plus grand de son compteur d'état
(IP ou compte) et de ce compteur navigateur : se déconnecter, se connecter ou changer de compte ne remet donc rien
à zéro. Sans jeton lisible, on retombe sur le comportement par état seul.
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
    person_key: str | None = None  # empreinte du navigateur : suit la personne entre anonyme et compte


class QuotaPolicy:
    def __init__(self, store: QuotaStore, settings: Settings, salt: str) -> None:
        self.store, self._s, self._salt = store, settings, salt

    def _person(self, participant: str | None) -> str | None:
        return make_key(self._salt, "person:" + participant) if participant else None

    def anonymous(self, ip: str, participant: str | None = None) -> Who:
        k = make_key(self._salt, "ip:" + ip)
        return Who("anonymous", k, k, self._person(participant))

    def account(self, account_id: str, ip: str, plan: str = "free", participant: str | None = None) -> Who:
        return Who(
            "pro" if plan == "pro" else "free",
            make_key(self._salt, "acct:" + account_id),
            make_key(self._salt, "ip:" + ip),
            self._person(participant),
        )

    # ---------- limites ----------
    def check_limit(self, who: Who) -> int:
        return {"pro": self._s.pro_daily_check_limit, "free": self._s.account_daily_check_limit}.get(who.plan, self._s.daily_check_limit)

    def debate_limit(self, who: Who) -> int:
        return {"pro": self._s.pro_debate_daily_checks, "free": self._s.account_debate_daily_checks}.get(who.plan, self._s.debate_daily_checks)

    # ---------- consommation ----------
    async def _person_exhausted(self, kind: str, who: Who, limit: int) -> bool:
        """La personne (navigateur) a déjà utilisé sa part du jour, tous états confondus. Lecture seule : un refus ne
        consomme rien, donc ne gonfle pas le compteur de l'IP (partagée) ni celui du compte."""
        return who.person_key is not None and await self.store.used("person_" + kind, who.person_key) >= limit

    async def _count_person(self, kind: str, who: Who) -> None:
        if who.person_key is not None:
            await self.store.consume("person_" + kind, who.person_key, 10**9)

    async def consume_check(self, who: Who) -> bool:
        limit = self.check_limit(who)
        if await self._person_exhausted("check", who, limit):
            return False
        if who.plan == "anonymous":
            granted = await self.store.consume("check", who.key, self._s.daily_check_limit)
        else:
            granted = await self.store.consume("check", who.key, limit) and await self.store.consume(
                "check_ip", who.ip_key, self._s.daily_check_limit * 4
            )
        if granted:
            await self._count_person("check", who)
        return granted

    async def consume_debate(self, who: Who) -> bool:
        """Un message de débat qui déclenche une vérification (appel LLM + recherche)."""
        limit = self.debate_limit(who)
        if await self._person_exhausted("debate", who, limit):
            return False
        if not await self.store.consume("debate", who.key, limit):
            return False
        if who.plan != "anonymous" and not await self.store.consume("debate_ip", who.ip_key, self._s.debate_daily_checks * 4):
            return False
        if not await self.store.consume("debate_global", GLOBAL_KEY, self._s.debate_global_daily_checks):
            return False
        await self._count_person("debate", who)
        return True

    # ---------- lecture ----------
    async def usage(self, who: Who) -> dict:
        check_used = await self.store.used("check", who.key)
        debate_used = await self.store.used("debate", who.key)
        if who.person_key is not None:  # la personne a pu consommer dans un autre état (anonyme ↔ compte)
            check_used = max(check_used, await self.store.used("person_check", who.person_key))
            debate_used = max(debate_used, await self.store.used("person_debate", who.person_key))
        c, d = self.check_limit(who), self.debate_limit(who)
        return {
            "plan": who.plan,
            "checks": {"used": check_used, "limit": c, "remaining": max(0, c - check_used)},
            "debate": {"used": debate_used, "limit": d, "remaining": max(0, d - debate_used)},
        }
