import pytest
from fastapi.testclient import TestClient

from app.adapters.llm import LLMError, LLMRateLimitError
from app.adapters.search import SearchError
from app.core.config import Settings
from app.core.schemas import CheckResponse, View
from app.core.security import SlidingWindowRateLimiter
from app.main import create_app
from app.services.factcheck import AnalysisError, PromptInjectionError

ASSERTION = "La hausse du SMIC à 1700€ net est dangereuse pour l'économie française."
URL = "/api/v1/check"


class FakeService:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    async def check(self, assertion, institutional_filter=True):
        self.calls.append((assertion, institutional_filter))
        if self.error:
            raise self.error
        return self.result


def ok_response():
    return CheckResponse(
        verdict="À NUANCER",
        confidence_score=85,
        summary="Synthèse.",
        liberal_institutional_view=View(title="L", points=["a"]),
        heterodox_social_view=View(title="H", points=["b"]),
        verified_sources=[],
    )


def client_for(service, **settings_kw):
    settings = Settings(_env_file=None, **settings_kw)
    return TestClient(create_app(settings, service=service))


@pytest.fixture
def client():
    svc = FakeService(ok_response())
    c = client_for(svc)
    c.svc = svc
    return c


# ---------- Fonctionnel ----------
def test_check_ok(client):
    r = client.post(URL, json={"assertion": ASSERTION, "institutional_filter": False})
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"] == "À NUANCER" and body["cached"] is False
    assert set(body) >= {"verdict", "confidence_score", "summary", "liberal_institutional_view", "heterodox_social_view", "verified_sources"}
    assert client.svc.calls == [(ASSERTION, False)]


def test_filter_defaults_to_true(client):
    client.post(URL, json={"assertion": ASSERTION})
    assert client.svc.calls[0][1] is True


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


# ---------- Validation d'entrée ----------
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"assertion": "court"},
        {"assertion": "x" * 501},
        {"assertion": ASSERTION, "role": "admin"},
        {"assertion": 12345678901234},
        {"assertion": ["liste", "pas", "texte", "du", "tout"]},
        {"assertion": None},
    ],
)
def test_invalid_payloads_return_422_without_calling_service(client, payload):
    r = client.post(URL, json=payload)
    assert r.status_code == 422
    assert client.svc.calls == []


def test_malformed_json_returns_422(client):
    r = client.post(URL, content=b"{pas du json", headers={"content-type": "application/json"})
    assert r.status_code == 422


def test_wrong_method_is_405(client):
    assert client.get(URL).status_code == 405


def test_prompt_injection_mapped_to_422():
    c = client_for(FakeService(error=PromptInjectionError("Assertion refusée : elle ne ressemble pas à une affirmation vérifiable.")))
    r = c.post(URL, json={"assertion": ASSERTION})
    assert r.status_code == 422 and "refusée" in r.json()["detail"]


# ---------- Mapping des erreurs sans fuite d'information ----------
@pytest.mark.parametrize(
    "error,status",
    [
        (SearchError("ddg: http://10.0.0.5:8080 token=abc"), 502),
        (LLMError("https://api.groq.com sk-SECRET"), 502),
        (AnalysisError("json: sk-SECRET"), 502),
        (LLMRateLimitError("quota sk-SECRET"), 503),
    ],
)
def test_upstream_errors_are_mapped_and_do_not_leak(error, status):
    c = client_for(FakeService(error=error))
    r = c.post(URL, json={"assertion": ASSERTION})
    assert r.status_code == status
    text = r.text
    for secret in ("sk-SECRET", "10.0.0.5", "groq", "token=abc", "Traceback"):
        assert secret not in text


def test_quota_error_has_retry_after():
    c = client_for(FakeService(error=LLMRateLimitError("q")))
    assert c.post(URL, json={"assertion": ASSERTION}).headers["retry-after"] == "30"


def test_unexpected_exception_returns_500_without_traceback():
    c = TestClient(
        create_app(Settings(_env_file=None), service=FakeService(error=RuntimeError("secret interne"))),
        raise_server_exceptions=False,
    )
    r = c.post(URL, json={"assertion": ASSERTION})
    assert r.status_code == 500 and "secret interne" not in r.text


# ---------- Rate limiting ----------
def test_rate_limit_returns_429_with_retry_after():
    c = client_for(FakeService(ok_response()), rate_limit_requests=2)
    codes = [c.post(URL, json={"assertion": ASSERTION}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    r = c.post(URL, json={"assertion": ASSERTION})
    assert int(r.headers["retry-after"]) >= 1


def test_rate_limit_counts_invalid_requests_too():
    svc = FakeService(ok_response())
    c = client_for(svc, rate_limit_requests=2)
    c.post(URL, json={"assertion": "court"})
    c.post(URL, json={"assertion": "court"})
    assert c.post(URL, json={"assertion": ASSERTION}).status_code == 429
    assert svc.calls == []


def test_rate_limit_not_bypassable_with_spoofed_forwarded_header():
    c = client_for(FakeService(ok_response()), rate_limit_requests=1)
    c.post(URL, json={"assertion": ASSERTION}, headers={"X-Forwarded-For": "1.1.1.1"})
    r = c.post(URL, json={"assertion": ASSERTION}, headers={"X-Forwarded-For": "2.2.2.2"})
    assert r.status_code == 429


def test_injected_limiter_is_used():
    limiter = SlidingWindowRateLimiter(0, 60)
    c = TestClient(create_app(Settings(_env_file=None), service=FakeService(ok_response()), limiter=limiter))
    assert c.post(URL, json={"assertion": ASSERTION}).status_code == 429


# ---------- Taille du corps ----------
def test_oversized_body_rejected_with_413(client):
    r = client.post(URL, content=b"x" * 20_000, headers={"content-type": "application/json"})
    assert r.status_code == 413
    assert client.svc.calls == []


# ---------- En-têtes de sécurité & CORS ----------
def test_security_headers_present_on_success_and_errors(client):
    for r in (client.get("/health"), client.post(URL, json={}), client.post(URL, content=b"x" * 20_000)):
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["x-frame-options"] == "DENY"
        assert r.headers["cache-control"] == "no-store"


def test_cors_allows_configured_origin_only():
    c = client_for(FakeService(ok_response()), cors_origins="https://facts.example")
    allowed = c.options(URL, headers={"Origin": "https://facts.example", "Access-Control-Request-Method": "POST"})
    denied = c.options(URL, headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert allowed.headers.get("access-control-allow-origin") == "https://facts.example"
    assert "access-control-allow-origin" not in denied.headers
    assert allowed.headers.get("access-control-allow-credentials") != "true"


def test_docs_disabled_in_production():
    prod = client_for(FakeService(ok_response()), env="prod")
    dev = client_for(FakeService(ok_response()), env="dev")
    assert prod.get("/docs").status_code == 404 and prod.get("/openapi.json").status_code == 404
    assert dev.get("/docs").status_code == 200


def test_missing_remote_llm_key_fails_fast_at_startup():
    app = create_app(Settings(_env_file=None, llm_api_key="", llm_base_url="https://api.example/v1"))
    with pytest.raises(RuntimeError, match="API_KEY"):
        with TestClient(app):
            pass
