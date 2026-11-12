"""Comptes de bout en bout : vraie base PostgreSQL, vrai vérificateur Google (JWKS factice), vraie API.

Ignorés sans FACTS_TEST_DATABASE_URL (la CI le définit et refuse de les ignorer).
"""

import asyncio
import hashlib
import os
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text, update

from app.core.config import Settings
from app.db.engine import Database
from app.db.schema import sessions, user_participants, users
from app.main import create_app
from app.services.google_auth import GoogleVerifier
from tests.google_helpers import CLIENT_ID, NOW, Clock, FakeGoogle, Keys
from tests.test_db_integration import migrate

URL = os.environ.get("FACTS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not URL, reason="FACTS_TEST_DATABASE_URL non défini")

KEYS = Keys()
ANON = "A" * 32
OTHER_ANON = "B" * 32


@pytest.fixture
async def fresh_db():
    db = Database(URL)
    async with db.engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await migrate("upgrade", "head")
    yield db
    async with db.engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await db.aclose()


def make_client(**kw) -> TestClient:
    settings = Settings(
        _env_file=None,
        database_url=URL,
        google_client_id=CLIENT_ID,
        llm_api_key="ci-dummy",
        search_providers="wikipedia",
        read_rate_limit_requests=1000,
        **kw,
    )
    google = GoogleVerifier(CLIENT_ID, client=FakeGoogle(KEYS).client(), clock=Clock())
    return TestClient(create_app(settings, google=google))


def login(client, *, sub="1234567890", email="alice@example.com", participant=None, **over):
    body = {"credential": KEYS.token(sub=sub, email=email, **over)}
    if participant:
        body["participant_token"] = participant
    return client.post("/api/v1/auth/login-google".replace("login-google", "google"), json=body)


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def query(sql, **params):
    async def run():
        db = Database(URL)
        try:
            async with db.session() as s:
                return (await s.execute(text(sql), params)).all()
        finally:
            await db.aclose()

    return asyncio.run(run())


# ---------- connexion ----------
def test_login_creates_account_and_session(fresh_db):
    with make_client() as client:
        r = login(client)
        assert r.status_code == 200
        body = r.json()
        assert body["user"]["email"] == "alice@example.com" and len(body["session_token"]) == 43
        me = client.get("/api/v1/auth/me", headers=auth(body["session_token"]))
        assert me.status_code == 200 and me.json()["user"]["id"] == body["user"]["id"]


def test_session_token_is_stored_only_as_a_hash(fresh_db):
    with make_client() as client:
        token = login(client).json()["session_token"]
    rows = query("SELECT token_hash FROM sessions")
    assert [r[0] for r in rows] == [hashlib.sha256(token.encode()).hexdigest()]
    assert token not in str(query("SELECT * FROM sessions")) and token not in str(query("SELECT * FROM users"))


def test_login_twice_reuses_the_account_and_follows_an_email_change(fresh_db):
    with make_client() as client:
        first = login(client).json()
        second = login(client, email="alice.new@example.com").json()
    assert first["user"]["id"] == second["user"]["id"] and first["session_token"] != second["session_token"]
    assert query("SELECT count(*) FROM users")[0][0] == 1
    assert query("SELECT email FROM users")[0][0] == "alice.new@example.com"


def test_email_already_used_by_another_account_is_a_conflict(fresh_db):
    with make_client() as client:
        assert login(client, sub="1", email="a@example.com").status_code == 200
        r = login(client, sub="2", email="a@example.com")
    assert r.status_code == 409 and query("SELECT count(*) FROM users")[0][0] == 1


def test_same_email_new_google_id_does_not_take_over_an_existing_account(fresh_db):
    """Un nouvel identifiant Google ne peut pas « hériter » d'un compte existant par son e-mail."""
    with make_client() as client:
        a = login(client, sub="1", email="a@example.com").json()
        b = login(client, sub="2", email="a@example.com")
        assert b.status_code == 409
        assert client.get("/api/v1/auth/me", headers=auth(a["session_token"])).status_code == 200


@pytest.mark.parametrize("over", [{"aud": "autre"}, {"email_verified": False}, {"exp": int(NOW) - 600}])
def test_forged_or_invalid_google_token_gets_a_generic_401(fresh_db, over):
    with make_client() as client:
        r = login(client, **over)
    assert r.status_code == 401 and "token_hash" not in r.text and CLIENT_ID not in r.text
    assert query("SELECT count(*) FROM users")[0][0] == 0 and query("SELECT count(*) FROM sessions")[0][0] == 0


def test_login_rejects_unknown_fields_and_bad_participant_token(fresh_db):
    with make_client() as client:
        cred = KEYS.token()
        assert client.post("/api/v1/auth/google", json={"credential": cred, "admin": True}).status_code == 422
        assert client.post("/api/v1/auth/google", json={"credential": cred, "participant_token": "x"}).status_code == 422
        assert client.post("/api/v1/auth/google", json={"credential": "court"}).status_code == 422


def test_login_attempts_are_rate_limited_per_ip(fresh_db):
    with make_client(login_attempts_per_window=3) as client:
        codes = [login(client, aud="autre").status_code for _ in range(5)]
    assert codes == [401, 401, 401, 429, 429]


# ---------- session ----------
@pytest.mark.parametrize("header", [None, "", "Bearer", "Bearer x", "Bearer " + "a" * 43, "Basic abc", "bearer"])
def test_missing_or_wrong_session_is_401(fresh_db, header):
    with make_client() as client:
        headers = {"Authorization": header} if header is not None else {}
        r = client.get("/api/v1/auth/me", headers=headers)
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"


def test_logout_revokes_only_this_session(fresh_db):
    with make_client() as client:
        t1 = login(client).json()["session_token"]
        t2 = login(client).json()["session_token"]
        assert client.post("/api/v1/auth/logout", headers=auth(t1)).status_code == 200
        assert client.get("/api/v1/auth/me", headers=auth(t1)).status_code == 401
        assert client.get("/api/v1/auth/me", headers=auth(t2)).status_code == 200


def test_logout_everywhere_revokes_every_session_of_that_account_only(fresh_db):
    with make_client() as client:
        mine = [login(client).json()["session_token"] for _ in range(3)]
        theirs = login(client, sub="2", email="bob@example.com").json()["session_token"]
        assert client.post("/api/v1/auth/logout-all", headers=auth(mine[0])).json() == {"revoked": 3}
        assert all(client.get("/api/v1/auth/me", headers=auth(t)).status_code == 401 for t in mine)
        assert client.get("/api/v1/auth/me", headers=auth(theirs)).status_code == 200


def test_expired_session_is_refused(fresh_db):
    with make_client() as client:
        token = login(client).json()["session_token"]

        async def expire():
            db = Database(URL)
            async with db.session() as s:
                await s.execute(update(sessions).values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
            await db.aclose()

        asyncio.run(expire())
        assert client.get("/api/v1/auth/me", headers=auth(token)).status_code == 401


def test_session_count_per_account_is_capped(fresh_db):
    with make_client(max_sessions_per_user=3) as client:
        tokens = [login(client).json()["session_token"] for _ in range(5)]
        assert query("SELECT count(*) FROM sessions")[0][0] == 3
        assert client.get("/api/v1/auth/me", headers=auth(tokens[0])).status_code == 401  # la plus ancienne a sauté
        assert client.get("/api/v1/auth/me", headers=auth(tokens[-1])).status_code == 200


def test_auth_responses_are_never_cached_and_set_no_cookie(fresh_db):
    with make_client() as client:
        r = login(client)
        me = client.get("/api/v1/auth/me", headers=auth(r.json()["session_token"]))
    for resp in (r, me):
        assert resp.headers["cache-control"] == "no-store" and "set-cookie" not in resp.headers


# ---------- identité anonyme ----------
def test_anonymous_identity_is_linked_to_the_account(fresh_db):
    with make_client() as client:
        login(client, participant=ANON)
    assert query("SELECT count(*) FROM user_participants")[0][0] == 1
    assert ANON not in str(query("SELECT * FROM user_participants"))  # seulement l'empreinte


def test_an_identity_already_linked_stays_with_its_first_account(fresh_db):
    with make_client() as client:
        a = login(client, sub="1", email="a@example.com", participant=ANON).json()["user"]["id"]
        login(client, sub="2", email="b@example.com", participant=ANON)
    owner = query("SELECT user_id FROM user_participants")
    assert len(owner) == 1 and str(owner[0][0]) == a


# ---------- RGPD ----------
def test_export_lists_the_data_without_any_secret(fresh_db):
    with make_client() as client:
        token = login(client, participant=ANON).json()["session_token"]
        r = client.get("/api/v1/auth/export", headers=auth(token))
    data = r.json()
    assert r.status_code == 200 and data["account"]["email"] == "alice@example.com"
    assert len(data["sessions"]) == 1 and data["linked_anonymous_identities"] == 1
    text_dump = r.text
    assert token not in text_dump and hashlib.sha256(token.encode()).hexdigest() not in text_dump
    assert "google_sub" not in text_dump and "1234567890" not in text_dump


def test_export_requires_a_session(fresh_db):
    with make_client() as client:
        assert client.get("/api/v1/auth/export").status_code == 401


def test_delete_requires_explicit_confirmation(fresh_db):
    with make_client() as client:
        token = login(client).json()["session_token"]
        assert client.post("/api/v1/auth/delete", json={}, headers=auth(token)).status_code == 422
        assert client.post("/api/v1/auth/delete", json={"confirm": False}, headers=auth(token)).status_code == 422
        assert client.get("/api/v1/auth/me", headers=auth(token)).status_code == 200


def test_delete_erases_everything_about_the_person(fresh_db):
    with make_client() as client:
        token = login(client, participant=ANON).json()["session_token"]
        other = login(client, sub="2", email="bob@example.com", participant=OTHER_ANON).json()["session_token"]
        assert client.post("/api/v1/auth/delete", json={"confirm": True}, headers=auth(token)).json() == {"deleted": True}
        assert client.get("/api/v1/auth/me", headers=auth(token)).status_code == 401
        assert client.get("/api/v1/auth/me", headers=auth(other)).status_code == 200  # l'autre compte est intact
    assert query("SELECT email FROM users") == [("bob@example.com",)]
    assert query("SELECT count(*) FROM sessions")[0][0] == 1 and query("SELECT count(*) FROM user_participants")[0][0] == 1


# ---------- désactivé / configuration ----------
def test_accounts_are_unavailable_without_database_or_client_id():
    for kw in ({"database_url": ""}, {"google_client_id": ""}):
        settings = Settings(_env_file=None, llm_api_key="ci-dummy", search_providers="wikipedia", **{"google_client_id": CLIENT_ID, "database_url": URL, **kw})
        with TestClient(create_app(settings)) as client:
            assert client.get("/api/v1/auth/me").status_code == 503
            assert client.post("/api/v1/auth/google", json={"credential": "x" * 30}).status_code == 503
            assert client.get("/api/v1/features").json()["accounts"] is False


def test_features_expose_only_the_public_client_id(fresh_db):
    with make_client() as client:
        data = client.get("/api/v1/features").json()
    assert data["accounts"] is True and data["google_client_id"] == CLIENT_ID


def test_cors_allows_the_authorization_header():
    with make_client() as client:
        pass
    settings = Settings(_env_file=None, cors_origins="https://site.example", llm_api_key="x", search_providers="wikipedia")
    r = TestClient(create_app(settings)).options(
        "/api/v1/auth/me",
        headers={"Origin": "https://site.example", "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization"},
    )
    assert r.status_code == 200 and "authorization" in r.headers["access-control-allow-headers"].lower()
