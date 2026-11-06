"""Le pipeline complet traverse la chaîne de repli ; le câblage réel démarre et s'arrête proprement."""

from fastapi.testclient import TestClient

from app.adapters.search import SearchError
from app.adapters.search_chain import FallbackSearch, GuardedProvider
from app.core.cache import TTLCache
from app.core.config import Settings
from app.core.resilience import CircuitBreaker
from app.main import create_app
from app.services.factcheck import FactCheckService
from app.services.retrieval import Retriever
from tests.conftest import OFCE, QUERIES, ScriptedLLM, StaticProvider, analysis


def chain(*providers):
    return FallbackSearch([GuardedProvider(f"p{i}", p, CircuitBreaker(3, 60)) for i, p in enumerate(providers)])


async def test_pipeline_gets_a_verdict_when_primary_search_is_down():
    primary, secondary = StaticProvider(error=SearchError("panne")), StaticProvider([OFCE])
    llm = ScriptedLLM(QUERIES, analysis())
    service = FactCheckService(llm, Retriever(chain(primary, secondary)), TTLCache(60, 10), 500)

    response = await service.check("La hausse du SMIC à 1700€ net est dangereuse pour l'économie.")

    assert response.verdict == "À NUANCER"
    assert [s.url for s in response.verified_sources] == [OFCE.url]
    assert len(primary.calls) == 1 and len(secondary.calls) == 1


async def test_pipeline_never_invents_a_verdict_when_all_search_is_down():
    llm = ScriptedLLM(QUERIES)  # aucune 2e réponse : un appel LLM sans contexte serait une erreur
    service = FactCheckService(
        llm, Retriever(chain(StaticProvider(error=SearchError("a")), StaticProvider(error=SearchError("b")))),
        TTLCache(60, 10), 500,
    )
    try:
        await service.check("La hausse du SMIC à 1700€ net est dangereuse pour l'économie.")
    except SearchError:
        pass
    else:
        raise AssertionError("SearchError attendue")
    assert len(llm.calls) == 1  # seule la génération de requêtes a eu lieu


def test_real_wiring_starts_and_stops_cleanly_without_network():
    settings = Settings(_env_file=None, llm_api_key="cle-de-test", search_providers="wikipedia,duckduckgo")
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.app.state.service is not None


def test_startup_fails_fast_on_bad_search_configuration():
    settings = Settings(_env_file=None, llm_api_key="cle-de-test", search_providers="bing")
    try:
        with TestClient(create_app(settings)):
            pass
    except RuntimeError as exc:
        assert "inconnu" in str(exc)
    else:
        raise AssertionError("RuntimeError attendue au démarrage")
