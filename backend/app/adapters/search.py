"""Port + adaptateur de recherche web.

`SearchProvider` est le « port » : le reste de l'application ne connaît que lui.
Pour passer à Brave, Tavily ou SearXNG plus tard, on écrit un nouvel adaptateur
et on change une ligne de câblage ; aucun autre fichier ne bouge.
"""

import asyncio
import html
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from app.core.domains import domain_trust_score, extract_domain
from app.core.security import InvalidInputError, sanitize_text

MAX_TITLE_CHARS = 200
MAX_SNIPPET_CHARS = 600

logger = logging.getLogger("facts.search")


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
            str(raw.get("body") or raw.get("snippet") or raw.get("content") or "")[: MAX_SNIPPET_CHARS * 2], MAX_SNIPPET_CHARS * 2
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


MAX_QUERY_CHARS = 300
_LANG_RE = re.compile(r"[a-z]{2,3}")
USER_AGENT = "FactsApp/0.1 (+https://github.com/pachiderms/facts)"


class _HttpSearchBase:
    """Socle commun aux adaptateurs HTTP : client partagé, erreurs génériques, fermeture propre.

    Les messages d'erreur ne contiennent jamais d'URL complète, d'en-tête ni de corps de réponse :
    ni la clé API ni du contenu hostile ne doivent fuiter dans les journaux ou vers le client.
    """

    name = "http"

    def __init__(self, timeout_seconds: float, client: httpx.AsyncClient | None) -> None:
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds, headers={"User-Agent": USER_AGENT})

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        try:
            response = await self._client.request(method, url, **kwargs)
        except httpx.TimeoutException as exc:
            raise SearchError(f"{self.name} : délai dépassé.") from exc
        except httpx.HTTPError as exc:
            raise SearchError(f"{self.name} indisponible : {type(exc).__name__}") from exc
        if response.status_code in (401, 403):
            logger.error("%s : accès refusé (HTTP %s), vérifier la clé API", self.name, response.status_code)
            raise SearchError(f"{self.name} : accès refusé.")
        if response.status_code == 429:
            raise SearchError(f"{self.name} : limite de débit atteinte.")
        if response.status_code >= 400:
            raise SearchError(f"{self.name} : erreur HTTP {response.status_code}.")
        try:
            return response.json()
        except ValueError as exc:
            raise SearchError(f"{self.name} : réponse illisible.") from exc


class TavilySearch(_HttpSearchBase):
    """API de recherche Tavily (offre gratuite : crédits mensuels, 1 crédit par recherche « basic »).

    Seule la recherche « basic » est utilisée (1 crédit) ; « advanced » en coûte 2.
    La réponse générée par Tavily (`answer`) est volontairement désactivée : on ne veut que
    des sources, la synthèse reste celle de NOTRE pipeline, dont la sortie est validée.
    NB : la clé est envoyée en en-tête Bearer ET dans le corps, car la documentation consultée
    (ancienne) cite le corps et les versions récentes l'en-tête. À valider avec une vraie clé.
    """

    name = "tavily"
    URL = "https://api.tavily.com/search"

    def __init__(
        self, api_key: str, timeout_seconds: float = 8.0, client: httpx.AsyncClient | None = None
    ) -> None:
        if not api_key:
            raise ValueError("Clé API Tavily manquante.")
        super().__init__(timeout_seconds, client)
        self._api_key = api_key

    async def search(self, query: str, max_results: int) -> list[SearchResult]:
        body = {
            "api_key": self._api_key,
            "query": query[:MAX_QUERY_CHARS],
            "search_depth": "basic",
            "max_results": max_results,
            "include_answer": False,
        }
        data = await self._request(
            "POST", self.URL, json=body, headers={"Authorization": f"Bearer {self._api_key}"}
        )
        items = data.get("results") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise SearchError("tavily : réponse inattendue.")
        results = [r for r in (normalize_result(i) for i in items if isinstance(i, dict)) if r is not None]
        return results[:max_results]


class WikipediaSearch(_HttpSearchBase):
    """Recherche plein texte Wikipédia (gratuite, sans clé). Source de contexte, pas de preuve :
    son score de confiance reste celui d'un domaine « autre » (40), donc elle ne passe jamais
    devant une source institutionnelle dans le classement."""

    name = "wikipedia"

    def __init__(
        self, lang: str = "fr", timeout_seconds: float = 8.0, client: httpx.AsyncClient | None = None
    ) -> None:
        if not _LANG_RE.fullmatch(lang):  # la langue entre dans le nom d'hôte : on la valide
            raise ValueError("Code de langue Wikipédia invalide.")
        super().__init__(timeout_seconds, client)
        self._lang = lang

    async def search(self, query: str, max_results: int) -> list[SearchResult]:
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query[:MAX_QUERY_CHARS],
            "srlimit": max(1, min(max_results, 10)),
            "srnamespace": 0,
            "format": "json",
            "utf8": 1,
        }
        data = await self._request("GET", f"https://{self._lang}.wikipedia.org/w/api.php", params=params)
        try:
            items = data["query"]["search"]
        except (KeyError, TypeError) as exc:
            raise SearchError("wikipedia : réponse inattendue.") from exc
        if not isinstance(items, list):
            raise SearchError("wikipedia : réponse inattendue.")

        results: list[SearchResult] = []
        for item in items:
            if not isinstance(item, dict) or not item.get("title"):
                continue
            title = html.unescape(str(item["title"]))
            url = f"https://{self._lang}.wikipedia.org/wiki/{quote(title.replace(' ', '_'), safe='_()')}"
            # Le snippet contient du HTML (<span class="searchmatch">) : retiré par sanitize_text.
            snippet = html.unescape(str(item.get("snippet") or ""))
            normalized = normalize_result({"url": url, "title": title, "snippet": snippet})
            if normalized is not None:
                results.append(normalized)
        return results[:max_results]
