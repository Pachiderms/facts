from app.core.config import Settings


def test_defaults_are_safe():
    s = Settings(_env_file=None)
    assert s.trust_proxy_headers is False  # jamais activé par défaut
    assert s.llm_api_key == ""  # aucun secret codé en dur
    assert s.assertion_max_chars == 500


def test_env_override(monkeypatch):
    monkeypatch.setenv("FACTS_RATE_LIMIT_REQUESTS", "3")
    monkeypatch.setenv("FACTS_CORS_ORIGINS", "https://a.example, https://b.example")
    s = Settings(_env_file=None)
    assert s.rate_limit_requests == 3
    assert s.cors_origin_list == ["https://a.example", "https://b.example"]


def test_cors_never_wildcard_by_default():
    assert "*" not in Settings(_env_file=None).cors_origin_list
