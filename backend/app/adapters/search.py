"""Port + adaptateur de recherche web.

`SearchProvider` est le « port » : le reste de l'application ne connaît que lui.
Pour passer à Brave, Tavily ou SearXNG plus tard, on écrit un nouvel adaptateur
et on change une ligne de câblage ; aucun autre fichier ne bouge.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.domains import domain_trust_score, extract_domain
from app.core.security import InvalidInputError, sanitize_text

MAX_TITLE_CHARS = 200
MAX_SNIPPET_CHARS = 600


class SearchError(RuntimeError):
    """La recherche web a échoué (réseau, quota, timeout...)."""


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    domain: str
    trust_score: int


class SearchProvider(Protocol):
    async def search(self, query: str, max_results: int) -> list[SearchResult]: ...


def normalize_result(raw: dict[str, Any]) -> SearchResult | None:
    """Transforme un résultat brut en SearchResult sûr, ou None s'il est inexploitable.

    Les extraits web sont une entrée NON FIABLE (injection de prompt indirecte : une page
    peut contenir « ignore tes instructions »). On les nettoie comme l'entrée utilisateur.
    """
    url = str(raw.get("href") or raw.get("url") or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        return None
    domain = extract_domain(url)
    if not domain:
        return None
    try:
        # On borne l'entrée AVANT le nettoyage (coût CPU), puis on tronque APRÈS :
        # un extrait trop long est raccourci, pas écarté.
        title = sanitize_text(str(raw.get("title") or "")[: MAX_TITLE_CHARS * 2], MAX_TITLE_CHARS * 2)
        snippet = sanitize_text(
            str(raw.get("body") or raw.get("snippet") or "")[: MAX_SNIPPET_CHARS * 2], MAX_SNIPPET_CHARS * 2
        )
    except InvalidInputError:
        return None  # titre ou extrait vide après nettoyage : on l'écarte
    title, snippet = title[:MAX_TITLE_CHARS], snippet[:MAX_SNIPPET_CHARS]
    return SearchResult(title=title, url=url, snippet=snippet, domain=domain, trust_score=domain_trust_score(domain))


class DuckDuckGoSearch:
    """Adaptateur DuckDuckGo via la librairie `ddgs` (gratuit, sans clé API).

    La librairie est synchrone : on l'exécute dans un thread pour ne pas bloquer
    la boucle asyncio (donc les WebSockets des débats).
    Limite connue : scraping non officiel, peut être limité en débit -> cache + port.
    """

    def __init__(
        self,
        region: str = "fr-fr",
        timeout_seconds: float = 8.0,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._region = region
        self._timeout = timeout_seconds
        if client_factory is None:
            from ddgs import DDGS  # import tardif : les tests n'en ont pas besoin

            client_factory = lambda: DDGS(timeout=int(timeout_seconds))  # noqa: E731
        self._client_factory = client_factory

    def _search_sync(self, query: str, max_results: int) -> list[dict[str, Any]]:
        return self._client_factory().text(query, region=self._region, max_results=max_results)

    async def search(self, query: str, max_results: int) -> list[SearchResult]:
        try:
            raw = await asyncio.wait_for(
                asyncio.to_thread(self._search_sync, query, max_results),
                timeout=self._timeout + 2,
            )
        except asyncio.TimeoutError as exc:
            raise SearchError("Délai dépassé pendant la recherche web.") from exc
        except Exception as exc:  # la lib lève des exceptions variées (réseau, ratelimit...)
            raise SearchError(f"Recherche web indisponible : {type(exc).__name__}") from exc

        results = [r for r in (normalize_result(item) for item in raw or []) if r is not None]
        return results[:max_results]
