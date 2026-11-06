"""Pipeline de vérification d'une assertion (workflow de Guidelines.md).

  1. SLM  : génère 1-2 requêtes ciblées            (repli sur l'assertion si le SLM échoue)
  2. Code : recherche web + classement des sources
  3. SLM  : analyse -> JSON, puis VALIDATION EN CODE de ce que le modèle a dit

Le point clé est l'étape 3 bis (`finalize_analysis`) : on ne fait jamais confiance au LLM
pour les sources. Une URL qui ne vient pas de la recherche est supprimée ; le titre, le
domaine et le score de confiance sont ceux calculés par NOTRE code ; sans source valide,
aucun verdict tranché n'est publié.
"""

import logging

from pydantic import ValidationError

from app.adapters.llm import LLMError, LLMProvider, LLMRateLimitError, parse_json_object
from app.adapters.search import SearchResult
from app.core.cache import TTLCache
from app.core.domains import TIER_RESEARCH
from app.core.schemas import CheckResponse, LLMAnalysis, Source, View
from app.core.security import InvalidInputError, looks_like_prompt_injection, sanitize_text
from app.core.text import fit_sentences
from app.services.prompts import (
    ANALYSIS_SYSTEM_PROMPT,
    QUERY_SYSTEM_PROMPT,
    build_analysis_user_prompt,
    build_query_user_prompt,
)
from app.services.retrieval import Retriever

logger = logging.getLogger("facts.factcheck")

MAX_QUERY_CHARS = 150
SUMMARY_MAX_CHARS = 500  # garde de la marge sous les 600 du schéma public
ANALYSIS_ATTEMPTS = 2

# Plafonds de confiance : le LLM ne peut pas être « sûr à 95 % » sans bonnes sources.
CONFIDENCE_CAP_NO_SOURCE = 30
CONFIDENCE_CAP_WEAK_SOURCES = 70


class PromptInjectionError(InvalidInputError):
    """L'assertion ressemble à une tentative de détournement du modèle."""


class AnalysisError(RuntimeError):
    """Le LLM n'a pas produit d'analyse exploitable après plusieurs tentatives."""


def _unverifiable(summary: str) -> CheckResponse:
    return CheckResponse(
        verdict="NON VÉRIFIABLE",
        confidence_score=0,
        summary=summary,
        liberal_institutional_view=View(title="Risques & Analyses Institutionnelles / Libérales", points=[]),
        heterodox_social_view=View(title="Leviers & Analyses Hétérodoxes / Sociales", points=[]),
        verified_sources=[],
    )


def finalize_analysis(analysis: LLMAnalysis, results: list[SearchResult]) -> CheckResponse:
    """Revalide la sortie du LLM contre les résultats de recherche réels."""
    by_url = {r.url.rstrip("/").lower(): r for r in results}

    sources: list[Source] = []
    seen: set[str] = set()
    for ref in analysis.verified_sources:
        key = ref.url.strip().rstrip("/").lower()
        real = by_url.get(key)
        if real is None or key in seen:
            continue  # URL inventée (ou doublon) : supprimée
        seen.add(key)
        sources.append(Source(title=real.title, url=real.url, domain=real.domain, trust_score=real.trust_score))

    if not sources:
        # Rien de vérifiable ne soutient l'analyse : on ne publie ni verdict ni points non sourcés.
        return _unverifiable("Aucune source exploitable n'a pu confirmer cette assertion.")

    cap = 100 if max(s.trust_score for s in sources) >= TIER_RESEARCH else CONFIDENCE_CAP_WEAK_SOURCES
    return CheckResponse(
        verdict=analysis.verdict,
        confidence_score=min(analysis.confidence_score, cap),
        summary=fit_sentences(analysis.summary, SUMMARY_MAX_CHARS),
        liberal_institutional_view=analysis.liberal_institutional_view,
        heterodox_social_view=analysis.heterodox_social_view,
        verified_sources=sources,
    )


class FactCheckService:
    def __init__(
        self,
        llm: LLMProvider,
        retriever: Retriever,
        cache: TTLCache[CheckResponse],
        assertion_max_chars: int = 500,
    ) -> None:
        self._llm = llm
        self._retriever = retriever
        self._cache = cache
        self._max_chars = assertion_max_chars

    @staticmethod
    def _cache_key(assertion: str, institutional_filter: bool) -> str:
        return f"{int(institutional_filter)}:{assertion.casefold()}"

    async def check(self, assertion: str, institutional_filter: bool = True) -> CheckResponse:
        clean = sanitize_text(assertion, self._max_chars)
        if looks_like_prompt_injection(assertion) or looks_like_prompt_injection(clean):
            raise PromptInjectionError("Assertion refusée : elle ne ressemble pas à une affirmation vérifiable.")

        key = self._cache_key(clean, institutional_filter)
        hit = self._cache.get(key)
        if hit is not None:
            return hit.model_copy(update={"cached": True})

        queries = await self._generate_queries(clean)
        results = await self._retriever.retrieve(queries, institutional_priority=institutional_filter)
        if not results:
            # Pas de contexte -> on n'interroge même pas le LLM (zéro risque d'hallucination).
            return _unverifiable("Aucune source web n'a été trouvée pour cette assertion.")

        analysis = await self._analyze(clean, results)
        response = finalize_analysis(analysis, results)
        if response.verified_sources:  # on ne met pas en cache les échecs : l'utilisateur peut réessayer
            self._cache.set(key, response)
        return response

    async def _generate_queries(self, assertion: str) -> list[str]:
        """Étape 1. Toute défaillance du SLM ici est non bloquante : repli sur l'assertion."""
        fallback = [assertion[:MAX_QUERY_CHARS]]
        try:
            raw = await self._llm.complete(
                QUERY_SYSTEM_PROMPT, build_query_user_prompt(assertion), json_mode=True, max_tokens=500
            )
            candidates = parse_json_object(raw).get("queries")
        except LLMRateLimitError:
            raise  # quota atteint : inutile de rappeler le fournisseur à l'étape 3
        except LLMError:
            logger.warning("génération de requêtes impossible, repli sur l'assertion")
            return fallback
        if not isinstance(candidates, list):
            return fallback

        queries: list[str] = []
        for item in candidates:
            if not isinstance(item, str):
                continue
            try:
                queries.append(sanitize_text(item[: MAX_QUERY_CHARS * 2], MAX_QUERY_CHARS * 2)[:MAX_QUERY_CHARS])
            except InvalidInputError:
                continue
        return queries[:2] or fallback

    async def _analyze(self, assertion: str, results: list[SearchResult]) -> LLMAnalysis:
        """Étape 3. Une nouvelle tentative si le JSON est invalide ; les erreurs réseau/quota remontent."""
        user_prompt = build_analysis_user_prompt(assertion, results)
        for attempt in range(1, ANALYSIS_ATTEMPTS + 1):
            raw = await self._llm.complete(ANALYSIS_SYSTEM_PROMPT, user_prompt, json_mode=True, max_tokens=2500)
            try:
                return LLMAnalysis.model_validate(parse_json_object(raw))
            except (LLMError, ValidationError) as exc:
                logger.warning("analyse invalide (tentative %d/%d): %s", attempt, ANALYSIS_ATTEMPTS, type(exc).__name__)
        raise AnalysisError("Le modèle n'a pas produit d'analyse valide.")
