"""Plafonds quotidiens par visiteur : protègent les crédits de recherche et les quotas LLM gratuits."""

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.schemas import CheckResponse, View
from app.main import create_app
from tests.test_api_check import ASSERTION, URL, FakeService, ok_response
from tests.test_api_rooms import CLAIM, WS, FakeService as RoomService, recv_until, send_message


def check_client(**kw):
    settings = Settings(_env_file=None, rate_limit_requests=1000, **kw)
    svc = FakeService(ok_response())
    client = TestClient(create_app(settings, service=svc))
    client.svc = svc
    return client


def test_daily_limit_blocks_after_quota():
    client = check_client(daily_check_limit=2)
    assert client.post(URL, json={"assertion": ASSERTION}).status_code == 200
    assert client.post(URL, json={"assertion": ASSERTION}).status_code == 200
    r = client.post(URL, json={"assertion": ASSERTION})
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) > 0
    assert len(client.svc.calls) == 2  # la 3e n'atteint jamais le service (ni recherche ni LLM)


def test_daily_limit_message_is_generic():
    client = check_client(daily_check_limit=1)
    client.post(URL, json={"assertion": ASSERTION})
    detail = client.post(URL, json={"assertion": ASSERTION}).json()["detail"]
    assert "quotidienne" in detail


def test_daily_limit_is_per_ip():
    settings = Settings(_env_file=None, rate_limit_requests=1000, daily_check_limit=1, trust_proxy_headers=True)
    client = TestClient(create_app(settings, service=FakeService(ok_response())))
    a = {"X-Forwarded-For": "1.1.1.1"}
    b = {"X-Forwarded-For": "2.2.2.2"}
    assert client.post(URL, json={"assertion": ASSERTION}, headers=a).status_code == 200
    assert client.post(URL, json={"assertion": ASSERTION}, headers=a).status_code == 429
    assert client.post(URL, json={"assertion": ASSERTION}, headers=b).status_code == 200


def test_invalid_requests_do_not_consume_the_daily_quota():
    """Un corps invalide (422) ne coûte ni recherche ni LLM : il ne consomme pas le plafond quotidien."""
    client = check_client(daily_check_limit=1)
    assert client.post(URL, json={"assertion": "x"}).status_code == 422
    assert client.post(URL, json={"assertion": ASSERTION}).status_code == 200


def test_per_minute_limit_still_applies_independently():
    settings = Settings(_env_file=None, rate_limit_requests=1, daily_check_limit=100)
    client = TestClient(create_app(settings, service=FakeService(ok_response())))
    assert client.post(URL, json={"assertion": ASSERTION}).status_code == 200
    assert client.post(URL, json={"assertion": ASSERTION}).status_code == 429


def test_websocket_daily_message_limit():
    settings = Settings(_env_file=None, daily_ws_message_limit=1, ws_messages_per_minute=100)
    client = TestClient(create_app(settings, service=RoomService()))
    with client.websocket_connect(WS, headers={"origin": "http://localhost:5173"}) as ws:
        send_message(ws, CLAIM)
        recv_until(ws, "message")
        send_message(ws, CLAIM)
        err = recv_until(ws, "error")
    assert err["code"] == "daily_limit"
