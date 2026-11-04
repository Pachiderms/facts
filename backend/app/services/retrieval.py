"""Récupération : exécute 1 à 2 requêtes, fusionne, dédoublonne et classe les résultats."""

import asyncio

from app.adapters.search import SearchError, SearchProvider, SearchResult


class Retriever:
    def __init__(self, provider: SearchProvider, max_results: int = 5) -> None:
        self._provider = provider
        self._max_results = max_results

    async def retrieve(self, queries: list[str], institutional_priority: bool = True) -> list[SearchResult]:
        """Retourne au plus `max_results` extraits.

        - Les requêtes tournent en parallèle ; une requête qui échoue n'annule pas les autres.
        - Si TOUTES échouent, on remonte SearchError (l'API répondra 502, pas un faux verdict).
        - `institutional_priority` : classe par score de confiance du domaine (tri stable,
          donc l'ordre du moteur de recherche départage les ex æquo). On demande plus de
          résultats que nécessaire pour avoir de quoi trier.
        """
        queries = [q for q in dict.fromkeys(q.strip() for q in queries) if q][:2]
        if not queries:
            return []

        fetch_n = self._max_results * 2 if institutional_priority else self._max_results
        outcomes = await asyncio.gather(
            *(self._provider.search(q, fetch_n) for q in queries), return_exceptions=True
        )

        errors = [o for o in outcomes if isinstance(o, BaseException)]
        if len(errors) == len(outcomes):
            first = errors[0]
            raise first if isinstance(first, SearchError) else SearchError(str(first))

        seen: set[str] = set()
        merged: list[SearchResult] = []
        for outcome in outcomes:
            if isinstance(outcome, BaseException):
                continue
            for result in outcome:
                key = result.url.rstrip("/").lower()
                if key not in seen:
                    seen.add(key)
                    merged.append(result)

        if institutional_priority:
            merged.sort(key=lambda r: r.trust_score, reverse=True)
        return merged[: self._max_results]
