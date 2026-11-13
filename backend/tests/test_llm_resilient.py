"""Modèle de secours et plafond global d'appels LLM. Fonctionnel + sécurité (aucune fuite, aucun appel inutile)."""

import pytest

from app.adapters.llm import LLMError, LLMRateLimitError, ResilientLLM
from app.core.config import Settings
from app.main import build_service


class Fake:
    def __init__(self, name, *, fail=None):
        self.name, self.fail, self.calls, self.closed = name, fail, [], False

    async def complete(self, system, user, **kw):
        self.calls.append((system, user, kw))
        if self.fail:
            raise self.fail
        return self.name

    async def aclose(self):
        self.closed = True


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make(primary, fallback=None, **kw):
    clock = Clock()
    return ResilientLLM(primary, fallback, clock=clock, **kw), clock


async def test_uses_primary_when_healthy():
    p, f = Fake("p"), Fake("f")
    llm, _ = make(p, f)
    assert await llm.complete("s", "u", json_mode=True, max_tokens=7, temperature=0.3) == "p"
    assert p.calls[0][2] == {"json_mode": True, "max_tokens": 7, "temperature": 0.3} and not f.calls and not llm.degraded


async def test_rate_limit_switches_to_fallback_immediately_without_retry():
    p, f = Fake("p", fail=LLMRateLimitError("429")), Fake("f")
    llm, _ = make(p, f)
    assert await llm.complete("s", "u") == "f"
    assert len(p.calls) == 1 and len(f.calls) == 1  # un seul appel refusé, pas de relance


async def test_primary_is_paused_after_a_429_then_resumes():
    p, f = Fake("p", fail=LLMRateLimitError("429")), Fake("f")
    llm, clock = make(p, f, cooldown_seconds=60)
    await llm.complete("s", "u")
    await llm.complete("s", "u")
    await llm.complete("s", "u")
    assert len(p.calls) == 1 and len(f.calls) == 3 and llm.degraded  # pas d'appel gaspillé pendant la pause
    clock.now += 61
    p.fail = None
    assert await llm.complete("s", "u") == "p" and not llm.degraded


async def test_without_fallback_the_rate_limit_propagates():
    llm, _ = make(Fake("p", fail=LLMRateLimitError("429")))
    with pytest.raises(LLMRateLimitError):
        await llm.complete("s", "u")
    with pytest.raises(LLMRateLimitError):  # en pause : plus d'appel au principal
        await llm.complete("s", "u")


async def test_daily_cap_stops_calls_to_the_primary():
    p, f = Fake("p"), Fake("f")
    llm, clock = make(p, f, daily_calls=3)
    for _ in range(3):
        assert await llm.complete("s", "u") == "p"
    assert llm.degraded and await llm.complete("s", "u") == "f"
    assert len(p.calls) == 3  # jamais d'appel au-delà du plafond
    clock.now += 86_401  # fenêtre glissante de 24 h
    assert await llm.complete("s", "u") == "p"


async def test_daily_cap_without_fallback_refuses_without_calling_the_provider():
    p = Fake("p")
    llm, _ = make(p, daily_calls=1)
    await llm.complete("s", "u")
    with pytest.raises(LLMRateLimitError):
        await llm.complete("s", "u")
    assert len(p.calls) == 1


async def test_other_errors_are_not_masked_by_the_fallback():
    p, f = Fake("p", fail=LLMError("boom")), Fake("f")
    llm, _ = make(p, f)
    with pytest.raises(LLMError):
        await llm.complete("s", "u")
    assert not f.calls and not llm.degraded


async def test_fallback_errors_propagate():
    llm, _ = make(Fake("p", fail=LLMRateLimitError("429")), Fake("f", fail=LLMRateLimitError("429 bis")))
    with pytest.raises(LLMRateLimitError):
        await llm.complete("s", "u")


async def test_aclose_closes_both_providers():
    p, f = Fake("p"), Fake("f")
    llm, _ = make(p, f)
    await llm.aclose()
    assert p.closed and f.closed


def test_build_service_wires_the_fallback_only_when_configured():
    base = dict(_env_file=None, llm_api_key="k", search_providers="wikipedia")
    _, llm, _ = build_service(Settings(**base))
    assert llm._fallback is None
    _, llm, _ = build_service(Settings(**base, llm_fallback_model="autre-modele", llm_fallback_api_key="k2"))
    assert llm._fallback is not None and llm._fallback._model == "autre-modele" and llm._fallback._api_key == "k2"
    _, llm, _ = build_service(Settings(**base, llm_fallback_model="autre-modele"))
    assert llm._fallback._api_key == "k"  # clé du principal réutilisée par défaut
    assert llm._budget.limit == 900  # défaut : sous le quota gratuit de 1 000 requêtes/jour
    _, llm, _ = build_service(Settings(**base, llm_global_daily_calls=5, llm_primary_cooldown_seconds=7))
    assert llm._budget.limit == 5 and llm._cooldown == 7
    _, llm, _ = build_service(Settings(**base, llm_global_daily_calls=0))
    assert llm._budget.limit >= 10**9  # 0 = pas de plafond
