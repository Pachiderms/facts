import logging
from datetime import datetime, timezone

import pytest

from app.adapters.search import SearchError, TavilySearch, WikipediaSearch, DuckDuckGoSearch
from app.adapters.search_chain import FallbackSearch, GuardedProvider, build_search_chain
from app.core.config import Settings
from app.core.resilience import CircuitBreaker, MonthlyQuota
from app.services.retrieval import Retriever
from tests.conftest import BLOG, IFRAP, OFCE, StaticProvider


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def guarded(name, provider, *, threshold=2, clock=None, quota=None):
    return GuardedProvider(name, provider, CircuitBreaker(threshold, 60, clock=clock or Clock()), quota)


def failing():
    return StaticProvider(error=SearchError("panne"))


# ---------- ordre et repli ----------
async def test_first_provider_answers_and_others_are_not_called():
    a, b = StaticProvider([OFCE]), StaticProvider([IFRAP])
    chain = FallbackSearch([guarded("a", a), guarded("b", b)])
    assert await chain.search("q", 5) == [OFCE]
    assert b.calls == []  # on ne consomme pas le suivant pour rien


async def test_falls_back_when_first_fails():
    a, b = failing(), StaticProvider([IFRAP])
    chain = FallbackSearch([guarded("a", a), guarded("b", b)])
    assert await chain.search("q", 5) == [IFRAP]
    assert len(a.calls) == 1 and len(b.calls) == 1


async def test_falls_back_when_first_returns_nothing():
    a, b = StaticProvider([]), StaticProvider([BLOG])
    chain = FallbackSearch([guarded("a", a), guarded("b", b)])
    assert await chain.search("q", 5) == [BLOG]


async def test_empty_answer_is_not_counted_as_a_failure():
    a = StaticProvider([])
    g = guarded("a", a, threshold=1)
    chain = FallbackSearch([g, guarded("b", StaticProvider([BLOG]))])
    for _ in range(3):
        await chain.search("q", 5)
    assert not g.breaker.is_open and len(a.calls) == 3


async def test_returns_empty_list_when_providers_answer_without_results():
    chain = FallbackSearch([guarded("a", StaticProvider([])), guarded("b", StaticProvider([]))])
    assert await chain.search("q", 5) == []


async def test_raises_when_every_provider_fails():
    chain = FallbackSearch([guarded("a", failing()), guarded("b", failing())])
    with pytest.raises(SearchError):
        await chain.search("q", 5)


async def test_one_failure_and_one_empty_answer_is_empty_not_error():
    chain = FallbackSearch([guarded("a", failing()), guarded("b", StaticProvider([]))])
    assert await chain.search("q", 5) == []  # b a bien répondu : il n'y a simplement rien


async def test_only_search_errors_are_caught():
    class Buggy:
        async def search(self, query, max_results):
            raise KeyError("bug")

    chain = FallbackSearch([guarded("a", Buggy()), guarded("b", StaticProvider([OFCE]))])
    with pytest.raises(KeyError):  # un vrai bug de code ne doit pas être masqué par le repli
        await chain.search("q", 5)


# ---------- disjoncteur ----------
async def test_failing_provider_is_skipped_once_breaker_opens():
    a = failing()
    chain = FallbackSearch([guarded("a", a, threshold=2), guarded("b", StaticProvider([OFCE]))])
    for _ in range(5):
        await chain.search("q", 5)
    assert len(a.calls) == 2  # après 2 échecs, a n'est plus sollicité


async def test_provider_is_retried_after_cooldown():
    clock, a = Clock(), failing()
    chain = FallbackSearch([guarded("a", a, threshold=1, clock=clock), guarded("b", StaticProvider([OFCE]))])
    await chain.search("q", 5)
    await chain.search("q", 5)
    assert len(a.calls) == 1
    clock.t = 61
    await chain.search("q", 5)
    assert len(a.calls) == 2


async def test_provider_recovers_after_successful_probe():
    clock = Clock()

    class Flaky:
        def __init__(self):
            self.fail, self.calls = True, 0

        async def search(self, query, max_results):
            self.calls += 1
            if self.fail:
                raise SearchError("panne")
            return [OFCE]

    flaky = Flaky()
    g = guarded("a", flaky, threshold=1, clock=clock)
    chain = FallbackSearch([g, guarded("b", StaticProvider([BLOG]))])
    await chain.search("q", 5)
    assert g.breaker.is_open
    flaky.fail, clock.t = False, 61
    assert await chain.search("q", 5) == [OFCE]
    assert not g.breaker.is_open


async def test_raises_when_all_breakers_are_open():
    chain = FallbackSearch([guarded("a", failing(), threshold=1), guarded("b", failing(), threshold=1)])
    with pytest.raises(SearchError):
        await chain.search("q", 5)  # les deux échouent et s'ouvrent
    with pytest.raises(SearchError):
        await chain.search("q", 5)  # plus rien d'appelable : toujours une erreur claire, pas un faux « aucun résultat »


# ---------- quota ----------
class FixedDate:
    def __init__(self, month=11):
        self.month = month

    def __call__(self):
        return datetime(2026, self.month, 5, tzinfo=timezone.utc)


async def test_quota_exhaustion_switches_to_next_provider_without_calling():
    paid, free = StaticProvider([OFCE]), StaticProvider([BLOG])
    chain = FallbackSearch([guarded("paid", paid, quota=MonthlyQuota(2, FixedDate())), guarded("free", free)])
    assert await chain.search("q", 5) == [OFCE]
    assert await chain.search("q", 5) == [OFCE]
    assert await chain.search("q", 5) == [BLOG]  # quota épuisé : on bascule
    assert len(paid.calls) == 2  # jamais d'appel au-delà du quota


async def test_quota_resets_next_month():
    date, paid = FixedDate(11), StaticProvider([OFCE])
    chain = FallbackSearch([guarded("paid", paid, quota=MonthlyQuota(1, date)), guarded("free", StaticProvider([BLOG]))])
    assert await chain.search("q", 5) == [OFCE]
    assert await chain.search("q", 5) == [BLOG]
    date.month = 12
    assert await chain.search("q", 5) == [OFCE]


async def test_quota_is_consumed_even_when_the_call_fails():
    paid, quota = failing(), MonthlyQuota(5, FixedDate())
    chain = FallbackSearch([guarded("paid", paid, threshold=99, quota=quota), guarded("free", StaticProvider([BLOG]))])
    await chain.search("q", 5)
    assert quota.remaining == 4  # estimation prudente : un appel échoué a pu coûter un crédit


async def test_open_breaker_does_not_consume_quota():
    quota = MonthlyQuota(10, FixedDate())
    chain = FallbackSearch([guarded("paid", failing(), threshold=1, quota=quota), guarded("free", StaticProvider([BLOG]))])
    for _ in range(4):
        await chain.search("q", 5)
    assert quota.remaining == 9  # 1 seul appel réel avant l'ouverture


async def test_exhausted_quota_does_not_trip_the_breaker():
    quota = MonthlyQuota(0, FixedDate())
    g = guarded("paid", StaticProvider([OFCE]), threshold=1, quota=quota)
    chain = FallbackSearch([g, guarded("free", StaticProvider([BLOG]))])
    await chain.search("q", 5)
    assert not g.breaker.is_open  # quota épuisé n'est pas une panne


# ---------- intégration avec le Retriever ----------
async def test_retriever_works_through_the_chain():
    chain = FallbackSearch([guarded("a", failing()), guarded("b", StaticProvider([OFCE, BLOG]))])
    results = await Retriever(chain, max_results=5).retrieve(["q1", "q2"])
    assert OFCE in results


async def test_retriever_gets_search_error_when_chain_is_down():
    chain = FallbackSearch([guarded("a", failing())])
    with pytest.raises(SearchError):
        await Retriever(chain).retrieve(["q"])


# ---------- fermeture ----------
async def test_aclose_closes_providers_that_support_it():
    class Closable(StaticProvider):
        closed = False

        async def aclose(self):
            self.closed = True

    p = Closable([OFCE])
    chain = FallbackSearch([guarded("a", p), guarded("b", StaticProvider([]))])
    await chain.aclose()
    assert p.closed


def test_chain_requires_at_least_one_provider():
    with pytest.raises(ValueError):
        FallbackSearch([])


# ---------- construction depuis la configuration ----------
def settings(**kw):
    return Settings(_env_file=None, **kw)


def test_default_chain_skips_tavily_without_key():
    chain = build_search_chain(settings())
    assert chain.provider_names == ["wikipedia", "duckduckgo"]


def test_default_chain_includes_tavily_with_key_and_keeps_order():
    chain = build_search_chain(settings(tavily_api_key="k"))
    assert chain.provider_names == ["tavily", "wikipedia", "duckduckgo"]
    types = [type(g.provider) for g in chain._providers]
    assert types == [TavilySearch, WikipediaSearch, DuckDuckGoSearch]


def test_tavily_gets_a_quota_and_free_providers_do_not():
    chain = build_search_chain(settings(tavily_api_key="k", tavily_monthly_limit=42))
    tavily, wikipedia, ddg = chain._providers
    assert tavily.quota is not None and tavily.quota.limit == 42
    assert wikipedia.quota is None and ddg.quota is None


def test_order_is_configurable_and_deduplicated_and_case_insensitive():
    chain = build_search_chain(settings(search_providers="DuckDuckGo, wikipedia,duckduckgo,"))
    assert chain.provider_names == ["duckduckgo", "wikipedia"]


def test_unknown_provider_fails_fast_with_explicit_message():
    with pytest.raises(RuntimeError, match="inconnu"):
        build_search_chain(settings(search_providers="bing"))


def test_only_tavily_without_key_fails_fast():
    with pytest.raises(RuntimeError, match="Aucun fournisseur"):
        build_search_chain(settings(search_providers="tavily"))


def test_missing_key_is_logged_without_exposing_anything(caplog):
    with caplog.at_level(logging.WARNING, logger="facts.search"):
        build_search_chain(settings())
    assert any("Tavily ignoré" in r.message for r in caplog.records)


def test_breaker_settings_are_applied():
    chain = build_search_chain(settings(search_breaker_failures=7, search_breaker_cooldown_seconds=9))
    breaker = chain._providers[0].breaker
    assert (breaker.failure_threshold, breaker.cooldown_s) == (7, 9)


def test_default_settings_are_cost_safe():
    s = settings()
    assert s.tavily_api_key == ""  # aucun secret codé en dur
    assert s.tavily_monthly_limit < 1000  # marge sous l'offre gratuite
    assert s.cache_ttl_seconds == 86_400
    assert s.daily_check_limit > 0 and s.daily_ws_message_limit > 0
