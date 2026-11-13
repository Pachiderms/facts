"""Chaîne de recherche avec repli : essaie les fournisseurs dans l'ordre configuré.

Chaque fournisseur est protégé par un disjoncteur (on cesse d'insister s'il échoue) et,
s'il est payant ou à crédits, par un quota mensuel (on ne dépasse jamais l'offre gratuite).
La chaîne elle-même respecte le port `SearchProvider` : le reste de l'application ne change pas.
"""

import logging
from typing import Any

from app.adapters.search import (
    DuckDuckGoSearch,
    SearchError,
    SearchProvider,
    SearchResult,
    TavilySearch,
    WikipediaSearch,
)
from app.core.config import Settings
from app.core.metering import record_search
from app.core.resilience import CircuitBreaker, MonthlyQuota

logger = logging.getLogger("facts.search")

KNOWN_PROVIDERS = ("tavily", "wikipedia", "duckduckgo")
CREDITS_PER_CALL = {"tavily": 1}  # recherche « basic » : 1 crédit ; les autres moteurs sont gratuits


class GuardedProvider:
    def __init__(
        self,
        name: str,
        provider: SearchProvider,
        breaker: CircuitBreaker,
        quota: MonthlyQuota | None = None,
    ) -> None:
        self.name = name
        self.provider = provider
        self.breaker = breaker
        self.quota = quota

    def acquire(self) -> bool:
        """Vérifie disjoncteur PUIS quota (un disjoncteur ouvert ne doit pas consommer de crédit)."""
        if not self.breaker.allow():
            return False
        if self.quota is not None and not self.quota.try_consume():
            self.breaker.record_success()  # libère un éventuel essai : ce n'est pas une panne du service
            return False
        return True

    async def aclose(self) -> None:
        closer = getattr(self.provider, "aclose", None)
        if closer is not None:
            await closer()


class FallbackSearch:
    """Retourne les résultats du premier fournisseur disponible qui en trouve.

    - Un fournisseur qui échoue (SearchError) fait passer au suivant et alimente son disjoncteur.
    - Un fournisseur qui répond sans résultat fait aussi passer au suivant, sans compter d'échec.
    - SearchError seulement si AUCUN fournisseur n'a pu répondre (tous en panne, ouverts ou à court de quota) :
      l'API répond alors 502 au lieu de produire un faux verdict.
    """

    def __init__(self, providers: list[GuardedProvider]) -> None:
        if not providers:
            raise ValueError("Au moins un fournisseur de recherche est requis.")
        self._providers = providers

    @property
    def provider_names(self) -> list[str]:
        return [p.name for p in self._providers]

    async def search(self, query: str, max_results: int) -> list[SearchResult]:
        answered = False
        for guarded in self._providers:
            if not guarded.acquire():
                logger.info("recherche : %s ignoré (disjoncteur ouvert ou quota épuisé)", guarded.name)
                continue
            try:
                results = await guarded.provider.search(query, max_results)
            except SearchError:
                record_search(guarded.name, error=True)
                guarded.breaker.record_failure()
                logger.warning("recherche : %s a échoué, repli sur le suivant", guarded.name)
                continue
            guarded.breaker.record_success()
            record_search(guarded.name, CREDITS_PER_CALL.get(guarded.name, 0))
            answered = True
            if results:
                return results
        if not answered:
            raise SearchError("Aucun moteur de recherche n'est disponible.")
        return []

    async def aclose(self) -> None:
        for guarded in self._providers:
            await guarded.aclose()


def _make_provider(name: str, settings: Settings) -> tuple[SearchProvider, MonthlyQuota | None] | None:
    if name == "tavily":
        if not settings.tavily_api_key:
            logger.warning("Tavily ignoré : FACTS_TAVILY_API_KEY absente.")
            return None
        # Marge sous le quota réel (1 000 crédits/mois) : une vérification peut lancer 2 recherches.
        return (
            TavilySearch(settings.tavily_api_key, settings.search_timeout_seconds),
            MonthlyQuota(settings.tavily_monthly_limit),
        )
    if name == "wikipedia":
        return WikipediaSearch(settings.wikipedia_lang, settings.search_timeout_seconds), None
    if name == "duckduckgo":
        return DuckDuckGoSearch(timeout_seconds=settings.search_timeout_seconds), None
    raise RuntimeError(f"Fournisseur de recherche inconnu : {name!r} (valeurs : {', '.join(KNOWN_PROVIDERS)}).")


def build_search_chain(settings: Settings, **breaker_kwargs: Any) -> FallbackSearch:
    names = [n.strip().lower() for n in settings.search_providers.split(",") if n.strip()]
    guarded: list[GuardedProvider] = []
    for name in dict.fromkeys(names):  # dédoublonne en gardant l'ordre
        made = _make_provider(name, settings)
        if made is None:
            continue
        provider, quota = made
        breaker = CircuitBreaker(
            settings.search_breaker_failures, settings.search_breaker_cooldown_seconds, **breaker_kwargs
        )
        guarded.append(GuardedProvider(name, provider, breaker, quota))
    if not guarded:
        raise RuntimeError("Aucun fournisseur de recherche utilisable (vérifier FACTS_SEARCH_PROVIDERS).")
    return FallbackSearch(guarded)
