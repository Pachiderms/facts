"""Connexion par e-mail (code à usage unique) : fonctionnel + sécurité. Base PostgreSQL réelle, expéditeur factice."""

import json
import os
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app.adapters.email import EmailError, OutboxSender, ResendSender, render_login_email
from app.core.config import Settings
from app.main import create_app
from app.services.email_login import CODE_RE, normalize_email
from app.services.google_auth import GoogleVerifier
from tests.google_helpers import CLIENT_ID, Clock, FakeGoogle
from tests.test_accounts_api import KEYS, auth, fresh_db, login, query  # noqa: F401  (fresh_db : fixture)

URL = os.environ.get("FACTS_TEST_DATABASE_URL", "")
db_only = pytest.mark.skipif(not URL, reason="FACTS_TEST_DATABASE_URL non défini")
ANON = "A" * 32


def email_client(sender=None, *, google=False, **kw) -> TestClient:
    sender = sender if sender is not None else OutboxSender()
    defaults = dict(email_resend_cooldown_seconds=0, read_rate_limit_requests=1000, login_attempts_per_window=1000)
    settings = Settings(
        _env_file=None,
        database_url=URL,
        google_client_id=CLIENT_ID if google else "",
        llm_api_key="ci-dummy",
        search_providers="wikipedia",
        **{**defaults, **kw},
    )
    verifier = GoogleVerifier(CLIENT_ID, client=FakeGoogle(KEYS).client(), clock=Clock()) if google else None
    client = TestClient(create_app(settings, google=verifier, email_sender=sender))
    client.sender = sender
    return client


def ask(client, email="alice@example.com"):
    return client.post("/api/v1/auth/email/request", json={"email": email})


def verify(client, email, code, **extra):
    return client.post("/api/v1/auth/email/verify", json={"email": email, "code": code, **extra})


def last_code(client, email="alice@example.com"):
    return [c for e, c in client.sender.sent if e == email][-1]


# ======================= pur =======================
@pytest.mark.parametrize("raw,expected", [
    ("alice@example.com", "alice@example.com"),
    ("  Alice.B+tag@Example.COM ", "alice.b+tag@example.com"),
    ("a_b-c%d@sous.domaine.example.fr", "a_b-c%d@sous.domaine.example.fr"),
    ("alice@example.com\n", "alice@example.com"),  # espaces et sauts de ligne en bordure : retirés, pas conservés
])
def test_normalize_valid(raw, expected):
    assert normalize_email(raw) == expected


@pytest.mark.parametrize("raw", [
    "", "alice", "alice@", "@example.com", "alice@example", "alice@@example.com", "a b@example.com",
    "alice@exa mple.com", "alice@example.com\r\nBcc: victime@example.com", "alice@example..com",
    "alice@-.com".replace("-.", ""), "aliçe@example.com", "alice@exämple.com", "<a>@example.com", "a,b@example.com",
    "a;b@example.com", "x" * 65 + "@example.com", "a@" + "x" * 64 + ".com", "a@" + "b." * 130 + "com",
])
def test_normalize_rejects_anything_unusual(raw):
    assert normalize_email(raw) is None


def test_code_format_is_six_ascii_digits_only():
    assert CODE_RE.fullmatch("012345")
    for bad in ["12345", "1234567", "abcdef", "１２３４５６", "12 345", "12345\n", "", "+12345"]:
        assert not CODE_RE.fullmatch(bad)


def test_email_content():
    subject, text, html = render_login_email("042137", 10)
    assert "042137" in text and "042137" in html and "10 minutes" in text and "CaFaitDebat" in subject
    assert "ignorez" in text


def test_settings_availability():
    base = dict(_env_file=None, database_url="postgresql://u:p@h/db")
    assert not Settings(**base).email_login_available
    assert not Settings(**base, resend_api_key="re_x").email_login_available  # adresse d'expédition manquante
    assert not Settings(**base, resend_api_key="re_x", email_from="pas-une-adresse").email_login_available
    assert not Settings(_env_file=None, resend_api_key="re_x", email_from="CFD <c@cafaitdebat.fr>").email_login_available  # sans base
    ok = Settings(**base, resend_api_key="re_x", email_from="CFD <c@cafaitdebat.fr>")
    assert ok.email_login_available and ok.accounts_available  # les comptes n'exigent plus Google à eux seuls


# ======================= Resend (transport simulé) =======================
async def test_resend_sender_posts_the_code_with_the_key():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(url=str(request.url), auth=request.headers["authorization"], body=json.loads(request.content))
        return httpx.Response(200, json={"id": "x"})

    sender = ResendSender("re_secret", "CFD <c@cafaitdebat.fr>", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    await sender.send_login_code("alice@example.com", "123456", 10)
    assert seen["url"] == "https://api.resend.com/emails" and seen["auth"] == "Bearer re_secret"
    assert seen["body"]["to"] == ["alice@example.com"] and seen["body"]["from"] == "CFD <c@cafaitdebat.fr>"
    assert "123456" in seen["body"]["text"] and "123456" in seen["body"]["html"]


async def test_resend_errors_never_leak_the_address_or_the_key():
    def refuse(request):
        return httpx.Response(422, json={"message": "alice@example.com invalide, clé re_secret"})

    def down(request):
        raise httpx.ConnectError("connexion refusée pour alice@example.com")

    for handler in (refuse, down):
        sender = ResendSender("re_secret", "c@cafaitdebat.fr", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        with pytest.raises(EmailError) as exc:
            await sender.send_login_code("alice@example.com", "123456", 10)
        assert "alice" not in str(exc.value) and "re_secret" not in str(exc.value) and "123456" not in str(exc.value)


# ======================= API =======================
@db_only
def test_features_and_unavailable_without_configuration(fresh_db):
    with email_client() as c:
        f = c.get("/api/v1/features").json()
        assert f["email_login"] is True and f["accounts"] is True and f["google_client_id"] is None
    plain = TestClient(create_app(Settings(_env_file=None)))
    assert plain.get("/api/v1/features").json()["email_login"] is False
    assert plain.post("/api/v1/auth/email/request", json={"email": "a@example.com"}).status_code == 503
    assert plain.post("/api/v1/auth/email/verify", json={"email": "a@example.com", "code": "123456"}).status_code == 503


@db_only
def test_request_sends_a_six_digit_code_and_verify_opens_a_session(fresh_db):
    with email_client() as c:
        r = ask(c)
        assert r.status_code == 202 and r.json() == {"sent": True}
        (to, code), = c.sender.sent
        assert to == "alice@example.com" and CODE_RE.fullmatch(code)
        v = verify(c, "alice@example.com", code, participant_token=ANON)
        assert v.status_code == 200
        body = v.json()
        assert body["user"]["email"] == "alice@example.com" and len(body["session_token"]) == 43
        assert c.get("/api/v1/auth/me", headers=auth(body["session_token"])).json()["user"]["id"] == body["user"]["id"]
        export = c.get("/api/v1/auth/export", headers=auth(body["session_token"])).json()
        assert export["account"]["login_method"] == "email" and export["linked_anonymous_identities"] == 1
    assert query("SELECT google_sub FROM users")[0][0] is None


@db_only
def test_code_works_once_only(fresh_db):
    with email_client() as c:
        ask(c)
        code = last_code(c)
        assert verify(c, "alice@example.com", code).status_code == 200
        assert verify(c, "alice@example.com", code).status_code == 401  # aucun rejeu
        assert query("SELECT count(*) FROM login_codes")[0][0] == 0


@db_only
def test_second_login_reuses_the_same_account(fresh_db):
    with email_client() as c:
        ids = []
        for _ in range(2):
            ask(c)
            ids.append(verify(c, "alice@example.com", last_code(c)).json()["user"]["id"])
        assert ids[0] == ids[1]
    assert query("SELECT count(*) FROM users")[0][0] == 1


@db_only
def test_address_is_case_insensitive_end_to_end(fresh_db):
    with email_client() as c:
        ask(c, "Alice@Example.COM")
        assert c.sender.sent[0][0] == "alice@example.com"
        assert verify(c, "ALICE@example.com", c.sender.sent[0][1]).status_code == 200


@db_only
def test_known_new_and_capped_addresses_get_the_same_answer(fresh_db):
    with email_client(email_daily_per_address=1) as c:
        first = ask(c, "new@example.com")
        verify(c, "new@example.com", last_code(c, "new@example.com"))  # l'adresse devient un compte connu
        capped = ask(c, "new@example.com")  # connu ET plafonné
        other = ask(c, "autre@example.com")
        assert (first.status_code, first.json()) == (capped.status_code, capped.json()) == (other.status_code, other.json()) == (202, {"sent": True})
        assert len(c.sender.sent) == 2  # le 2e envoi à new@ n'a pas eu lieu, sans que la réponse le révèle


@db_only
def test_invalid_address_is_refused_before_anything_is_sent(fresh_db):
    with email_client() as c:
        for bad in ["pas-un-mail", "a@b", "a@b.com\r\nBcc: x@y.fr", "é@example.com"]:
            assert ask(c, bad).status_code == 422
        assert c.post("/api/v1/auth/email/request", json={"email": "a@example.com", "extra": 1}).status_code == 422
        assert c.sender.sent == []


@db_only
def test_wrong_codes_are_counted_and_the_code_dies_after_the_limit(fresh_db):
    with email_client(email_code_max_attempts=3) as c:
        ask(c)
        good = last_code(c)
        wrong = "000000" if good != "000000" else "111111"
        for _ in range(3):
            assert verify(c, "alice@example.com", wrong).status_code == 401
        assert verify(c, "alice@example.com", good).status_code == 401  # même le bon code est refusé : il est détruit
        assert query("SELECT count(*) FROM login_codes")[0][0] == 0
        ask(c)  # un nouveau code repart de zéro
        assert verify(c, "alice@example.com", last_code(c)).status_code == 200


@db_only
def test_attempts_are_persisted_across_requests(fresh_db):
    with email_client(email_code_max_attempts=5) as c:
        ask(c)
        good = last_code(c)
        wrong = "000000" if good != "000000" else "111111"
        verify(c, "alice@example.com", wrong)
        verify(c, "alice@example.com", wrong)
        assert query("SELECT attempts FROM login_codes")[0][0] == 2


@db_only
def test_expired_code_is_refused_and_removed(fresh_db):
    with email_client() as c:
        ask(c)
        code = last_code(c)
        later = datetime.now(timezone.utc) + timedelta(seconds=601)
        c.app.state.email_login._clock = lambda: later
        assert verify(c, "alice@example.com", code).status_code == 401
        assert query("SELECT count(*) FROM login_codes")[0][0] == 0


@db_only
def test_a_new_code_replaces_the_previous_one(fresh_db):
    with email_client() as c:
        ask(c)
        old = last_code(c)
        ask(c)
        new = last_code(c)
        assert query("SELECT count(*) FROM login_codes")[0][0] == 1
        if old != new:  # 1 chance sur 1 000 000 d'être identiques
            assert verify(c, "alice@example.com", old).status_code == 401
        assert verify(c, "alice@example.com", new).status_code == 200


@db_only
def test_resend_cooldown_keeps_the_first_code_and_sends_nothing(fresh_db):
    with email_client(email_resend_cooldown_seconds=30) as c:
        assert ask(c).status_code == 202
        assert ask(c).status_code == 202  # même réponse
        assert len(c.sender.sent) == 1
        assert verify(c, "alice@example.com", last_code(c)).status_code == 200


@db_only
def test_a_code_only_works_for_its_own_address(fresh_db):
    with email_client() as c:
        ask(c, "alice@example.com")
        ask(c, "bob@example.com")
        alice_code = last_code(c, "alice@example.com")
        bob_code = last_code(c, "bob@example.com")
        if alice_code != bob_code:
            assert verify(c, "bob@example.com", alice_code).status_code == 401
        assert verify(c, "carole@example.com", alice_code).status_code == 401  # aucune demande pour cette adresse
        assert verify(c, "alice@example.com", alice_code).status_code == 200


@db_only
def test_malformed_codes_and_addresses_are_just_refused(fresh_db):
    with email_client() as c:
        ask(c)
        for code in ["12345", "abcdef", "１２３４５６", "123 456"]:
            r = verify(c, "alice@example.com", code)
            assert r.status_code in (401, 422)
        assert verify(c, "n'importe quoi", "123456").status_code == 401
        assert verify(c, "alice@example.com", "123456", participant_token="x").status_code == 422
        assert query("SELECT attempts FROM login_codes")[0][0] == 0  # un format invalide ne consomme pas d'essai


@db_only
def test_code_is_stored_only_as_a_salted_hash_bound_to_the_address(fresh_db):
    with email_client() as c:
        ask(c)
        code = last_code(c)
        rows = query("SELECT email, code_hash FROM login_codes")
        assert len(rows[0][1]) == 64 and code not in str(rows) and rows[0][0] == "alice@example.com"
        ask(c, "bob@example.com")
        hashes = {r[0]: r[1] for r in query("SELECT email, code_hash FROM login_codes")}
        assert hashes["alice@example.com"] != hashes["bob@example.com"]


@db_only
def test_per_address_daily_cap(fresh_db):
    with email_client(email_daily_per_address=2) as c:
        for _ in range(4):
            assert ask(c).status_code == 202
        assert len(c.sender.sent) == 2


@db_only
def test_per_ip_daily_cap(fresh_db):
    with email_client(email_daily_per_ip=2) as c:
        assert ask(c, "a@example.com").status_code == 202 and ask(c, "b@example.com").status_code == 202
        r = ask(c, "c@example.com")
        assert r.status_code == 503 and len(c.sender.sent) == 2


@db_only
def test_global_daily_cap_stays_under_the_free_provider_limit(fresh_db):
    with email_client(email_daily_global=1) as c:
        assert ask(c, "a@example.com").status_code == 202
        assert ask(c, "b@example.com").status_code == 503
        assert len(c.sender.sent) == 1


@db_only
def test_send_failure_is_a_clean_503_and_stores_nothing(fresh_db):
    with email_client(OutboxSender(fail=True)) as c:
        r = ask(c)
        assert r.status_code == 503 and "alice" not in r.text
        assert query("SELECT count(*) FROM login_codes")[0][0] == 0


@db_only
def test_login_rate_limit_applies_to_request_and_verify(fresh_db):
    with email_client(login_attempts_per_window=3) as c:
        codes = [ask(c).status_code for _ in range(3)]
        assert codes == [202, 202, 202] and ask(c).status_code == 429
    with email_client(login_attempts_per_window=2) as c:
        ask(c)
        assert verify(c, "alice@example.com", "000000").status_code in (401, 200)
        assert verify(c, "alice@example.com", "000000").status_code == 429  # force brute freinée par IP aussi


@db_only
def test_google_endpoint_is_unavailable_without_a_google_setup(fresh_db):
    with email_client() as c:
        r = c.post("/api/v1/auth/google", json={"credential": "x" * 30})
        assert r.status_code == 503


@db_only
def test_email_then_google_with_the_same_address_is_one_account(fresh_db):
    with email_client(google=True) as c:
        ask(c)
        by_email = verify(c, "alice@example.com", last_code(c)).json()["user"]["id"]
        by_google = login(c, sub="g-1", email="alice@example.com").json()["user"]["id"]
        assert by_email == by_google
    assert query("SELECT count(*) FROM users")[0][0] == 1 and query("SELECT google_sub FROM users")[0][0] == "g-1"


@db_only
def test_google_then_email_with_the_same_address_is_one_account(fresh_db):
    with email_client(google=True) as c:
        by_google = login(c, sub="g-1", email="alice@example.com").json()["user"]["id"]
        ask(c)
        by_email = verify(c, "alice@example.com", last_code(c)).json()["user"]["id"]
        assert by_google == by_email
    assert query("SELECT count(*) FROM users")[0][0] == 1


@db_only
def test_a_second_google_account_cannot_take_an_address_already_bound_to_another_google_account(fresh_db):
    with email_client(google=True) as c:
        assert login(c, sub="g-1", email="alice@example.com").status_code == 200
        assert login(c, sub="g-2", email="alice@example.com").status_code == 409  # comportement existant conservé


@db_only
def test_deleting_the_account_erases_any_pending_code(fresh_db):
    with email_client() as c:
        ask(c)
        token = verify(c, "alice@example.com", last_code(c)).json()["session_token"]
        ask(c)  # nouveau code en attente
        assert query("SELECT count(*) FROM login_codes")[0][0] == 1
        assert c.post("/api/v1/auth/delete", json={"confirm": True}, headers=auth(token)).status_code == 200
    assert query("SELECT count(*) FROM login_codes")[0][0] == 0 and query("SELECT count(*) FROM users")[0][0] == 0


@db_only
def test_expired_codes_are_purged_on_the_next_request(fresh_db):
    with email_client() as c:
        ask(c, "old@example.com")
        later = datetime.now(timezone.utc) + timedelta(hours=1)
        c.app.state.email_login._clock = lambda: later
        ask(c, "new@example.com")
        assert [r[0] for r in query("SELECT email FROM login_codes")] == ["new@example.com"]


# ======================= empreinte et tirage du code =======================
def _service(salt="sel-1"):
    from app.services.email_login import EmailLoginService

    return EmailLoginService(None, None, OutboxSender(), None, Settings(_env_file=None), salt)


def test_code_hash_is_bound_to_the_address_and_to_the_secret_salt():
    a, b = _service(), _service("sel-2")
    assert a._code_hash("alice@example.com", "123456") == a._code_hash("alice@example.com", "123456")
    assert a._code_hash("alice@example.com", "123456") != a._code_hash("bob@example.com", "123456")  # code d'une adresse inutilisable pour une autre
    assert a._code_hash("alice@example.com", "123456") != a._code_hash("alice@example.com", "123457")
    assert a._code_hash("alice@example.com", "123456") != b._code_hash("alice@example.com", "123456")  # sans le sel, pas d'empreinte
    assert len(a._code_hash("alice@example.com", "123456")) == 64


@db_only
def test_codes_are_not_predictable_constants(fresh_db):
    with email_client(email_daily_per_address=100, email_daily_global=1000, email_daily_per_ip=1000) as c:
        for _ in range(12):
            ask(c)
        codes = [code for _, code in c.sender.sent]
        assert len(codes) == 12 and all(CODE_RE.fullmatch(code) for code in codes)
        assert len(set(codes)) > 6  # un tirage aléatoire sur 10^6 valeurs : jamais (ou presque) deux fois la même


@db_only
async def test_a_code_cannot_be_redeemed_twice_by_concurrent_requests(fresh_db):
    from app.core.quotas import MemoryQuotas
    from app.db.engine import Database
    from app.services.accounts import AccountService
    from app.services.email_login import EmailLoginService
    from app.services.quota_policy import QuotaPolicy
    import asyncio

    db = Database(URL)
    try:
        settings = Settings(_env_file=None, email_resend_cooldown_seconds=0)
        sender = OutboxSender()
        service = EmailLoginService(db, AccountService(db), sender, QuotaPolicy(MemoryQuotas(), settings, "sel"), settings, "sel")
        assert await service.request("alice@example.com", "1.1.1.1")
        code = sender.sent[0][1]
        results = await asyncio.gather(*[service.verify("alice@example.com", code) for _ in range(6)])
        assert sum(r is not None for r in results) == 1  # un seul rachat : le verrou de ligne sérialise les essais
    finally:
        await db.aclose()
