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
POOL_KIND = "m_edu_pool"  # compteur MENSUEL : vérifications consommées par une licence Edu, tous ses salons confondus
ROOM_BUDGET_REASON = "BUDGET DU SALON ATTEINT"
POOL_REASON = "BUDGET DE LA LICENCE ATTEINT"


@dataclass
class RoomBudget:
    """Budget de vérifications d'un salon Edu : un plafond par séance + le pool mensuel de la licence de son créateur.
    `used` vit en mémoire avec le salon (un salon est de toute façon éphémère) ; le pool, lui, est durable."""

    cap: int
    pool_key: str
    pool_limit: int
    used: int = 0


@dataclass(frozen=True)
class Who:
    plan: str  # "anonymous" | "free" | "pro" | "edu"
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
            plan if plan in ("pro", "edu") else "free",
            make_key(self._salt, "acct:" + account_id),
            make_key(self._salt, "ip:" + ip),
            self._person(participant),
        )

    # ---------- limites ----------
    def check_limit(self, who: Who) -> int:
        return {"pro": self._s.pro_daily_check_limit, "edu": self._s.pro_daily_check_limit, "free": self._s.account_daily_check_limit}.get(who.plan, self._s.daily_check_limit)

    def debate_limit(self, who: Who) -> int:
        return {"pro": self._s.pro_debate_daily_checks, "edu": self._s.pro_debate_daily_checks, "free": self._s.account_debate_daily_checks}.get(who.plan, self._s.debate_daily_checks)

    # ---------- salons ----------
    def room_capacity(self, plan: str) -> int:
        """Personnes connectées en même temps (intervenants + spectateurs) dans un salon créé avec ce plan."""
        s = self._s
        cap = {"edu": s.room_capacity_edu, "pro": s.room_capacity_pro, "free": s.room_capacity_free}.get(plan, s.room_capacity_anonymous)
        return max(1, min(cap, s.ws_max_room_connections))  # jamais au-delà du plafond technique

    def room_budget(self, owner_account_id: str, pool: int | None) -> RoomBudget:
        return RoomBudget(
            cap=self._s.edu_room_check_budget,
            pool_key=make_key(self._salt, "edu:" + owner_account_id),
            pool_limit=pool if pool is not None else self._s.edu_monthly_check_pool,
        )

    async def consume_room_check(self, budget: RoomBudget) -> bool | str:
        """Vérification d'un message dans un salon Edu : elle ne consomme NI le quota personnel de l'élève, NI celui de
        l'enseignant, mais le budget du salon et le pool de la licence. True, ou le motif du refus (publié « non vérifié »).
        Ordre : le plafond du salon (mémoire) est réservé d'abord, puis lecture du pool, puis budget global, puis
        consommation atomique du pool : un refus ne gaspille jamais le budget global ni le pool."""
        if budget.used >= budget.cap:
            return ROOM_BUDGET_REASON
        budget.used += 1  # réservé avant tout `await` : deux messages simultanés ne dépassent pas le plafond
        try:
            if await self.store.used(POOL_KIND, budget.pool_key) >= budget.pool_limit:
                budget.used -= 1
                return POOL_REASON
            if not await self.store.consume("debate_global", GLOBAL_KEY, self._s.debate_global_daily_checks):
                budget.used -= 1
                return False
            if not await self.store.consume(POOL_KIND, budget.pool_key, budget.pool_limit):
                budget.used -= 1
                return POOL_REASON
        except BaseException:
            budget.used -= 1
            raise
        return True

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
