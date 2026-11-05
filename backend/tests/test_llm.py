import json

import httpx
import pytest

from app.adapters.llm import (
    LLMError,
    LLMRateLimitError,
    OpenAICompatibleLLM,
    parse_json_object,
)


def ok(content='{"a": 1}'):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def make_llm(handler, **kw):
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    llm = OpenAICompatibleLLM(
        base_url=kw.pop("base_url", "https://llm.example/v1/"),
        model="m",
        api_key=kw.pop("api_key", "sk-secret"),
        client=client,
        sleep=fake_sleep,
        **kw,
    )
    return llm, sleeps


# ---------- Fonctionnel ----------
async def test_complete_returns_content_and_builds_request():
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return ok("bonjour")

    llm, _ = make_llm(handler)
    out = await llm.complete("SYS", "USER", json_mode=True, max_tokens=300)
    assert out == "bonjour"
    assert seen["url"] == "https://llm.example/v1/chat/completions"  # slash final géré
    assert seen["auth"] == "Bearer sk-secret"
    body = seen["body"]
    assert body["model"] == "m" and body["temperature"] == 0.0 and body["max_tokens"] == 300
    assert body["messages"] == [{"role": "system", "content": "SYS"}, {"role": "user", "content": "USER"}]
    assert body["response_format"] == {"type": "json_object"}


async def test_no_auth_header_without_key_for_local_ollama():
    seen = {}

    def handler(request):
        seen["headers"] = dict(request.headers)
        return ok()

    llm, _ = make_llm(handler, api_key="")
    await llm.complete("s", "u")
    assert "authorization" not in seen["headers"]


async def test_no_response_format_by_default():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return ok()

    llm, _ = make_llm(handler)
    await llm.complete("s", "u")
    assert "response_format" not in seen["body"]


async def test_retries_once_on_5xx_then_succeeds():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503) if len(calls) == 1 else ok("ok")

    llm, sleeps = make_llm(handler)
    assert await llm.complete("s", "u") == "ok"
    assert len(calls) == 2 and len(sleeps) == 1


async def test_retries_on_network_error():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("boom")
        return ok("ok")

    llm, _ = make_llm(handler)
    assert await llm.complete("s", "u") == "ok"


async def test_persistent_5xx_raises_after_bounded_attempts():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(500)

    llm, _ = make_llm(handler, max_retries=2)
    with pytest.raises(LLMError):
        await llm.complete("s", "u")
    assert len(calls) == 3


async def test_timeout_raises_llm_error():
    def handler(request):
        raise httpx.ReadTimeout("slow")

    llm, _ = make_llm(handler, max_retries=0)
    with pytest.raises(LLMError):
        await llm.complete("s", "u")


# ---------- Sécurité / robustesse ----------
async def test_429_is_not_retried_and_has_dedicated_error():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429, headers={"retry-after": "30"})

    llm, _ = make_llm(handler)
    with pytest.raises(LLMRateLimitError):
        await llm.complete("s", "u")
    assert len(calls) == 1  # on ne martèle pas un fournisseur qui dit stop


@pytest.mark.parametrize("status", [400, 401, 403, 404])
async def test_4xx_not_retried_and_body_not_leaked(status):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(status, text="invalid key sk-secret for user bob")

    llm, _ = make_llm(handler)
    with pytest.raises(LLMError) as ei:
        await llm.complete("s", "u")
    assert len(calls) == 1
    assert "sk-secret" not in str(ei.value) and "bob" not in str(ei.value)


async def test_network_error_message_does_not_leak_url_or_key():
    def handler(request):
        raise httpx.ConnectError("failed to reach https://llm.example/v1 with sk-secret")

    llm, _ = make_llm(handler, max_retries=0)
    with pytest.raises(LLMError) as ei:
        await llm.complete("s", "u")
    assert "sk-secret" not in str(ei.value) and "llm.example" not in str(ei.value)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="pas du json"),
        httpx.Response(200, json={}),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"choices": [{"message": {}}]}),
        httpx.Response(200, json={"choices": [{"message": {"content": None}}]}),
        httpx.Response(200, json={"choices": [{"message": {"content": "   "}}]}),
        httpx.Response(200, json={"choices": [{"message": {"content": "x" * 60_000}}]}),
    ],
)
async def test_malformed_provider_responses_raise_llm_error(response):
    llm, _ = make_llm(lambda request: response)
    with pytest.raises(LLMError):
        await llm.complete("s", "u")


# ---------- parse_json_object ----------
def test_parse_plain_json():
    assert parse_json_object('{"verdict": "FAUX"}') == {"verdict": "FAUX"}


def test_parse_fenced_json():
    assert parse_json_object('```json\n{"a": {"b": [1, 2]}}\n```') == {"a": {"b": [1, 2]}}


def test_parse_json_surrounded_by_prose():
    assert parse_json_object('Voici le résultat :\n{"a": 1}\nBonne journée !') == {"a": 1}


def test_parse_keeps_nested_braces_and_unicode():
    assert parse_json_object('{"summary": "À nuancer {entre accolades}", "n": {"x": 1}}')["n"] == {"x": 1}


@pytest.mark.parametrize("text", ["", "pas de json", "[1, 2, 3]", '"juste une chaîne"', "42", '{"a": ', "{{{"])
def test_parse_rejects_non_objects_and_garbage(text):
    with pytest.raises(LLMError):
        parse_json_object(text)


async def test_reasoning_effort_is_sent_only_when_configured():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    llm, _ = make_llm(handler, reasoning_effort="low")
    await llm.complete("S", "U")
    assert seen["body"]["reasoning_effort"] == "low"
    llm, _ = make_llm(handler)
    await llm.complete("S", "U")
    assert "reasoning_effort" not in seen["body"]  # défaut : paramètre absent, compatible avec tous les fournisseurs
