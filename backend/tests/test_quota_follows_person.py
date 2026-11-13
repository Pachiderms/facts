"""Le quota suit la personne (navigateur) entre anonyme et compte, dans les deux sens. Fonctionnel + sécurité."""

import os
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import Settings
from app.core.quotas import MemoryQuotas
from app.services.quota_policy import QuotaPolicy
from tests.test_account_rooms_api import ANON, create, recv_until, session_for  # noqa: F401
from tests.test_accounts_api import OTHER_ANON, auth, fresh_db, make_client  # noqa: F401
from tests.test_api_check import ASSERTION, URL
from tests.test_usage_quotas import TOKEN_A, TOKEN_B, client_with_accounts

BROWSER_1, BROWSER_2 = "p" * 43, "q" * 43
DB = os.environ.get("FACTS_TEST_DATABASE_URL", "")


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)

    def __call__(self):
        return self.now


def policy(**kw):
    clock = Clock()
    s = Settings(_env_file=None, daily_check_limit=2, account_daily_check_limit=4, pro_daily_check_limit=8,
                 debate_daily_checks=2, account_debate_daily_checks=4, pro_debate_daily_checks=8, **kw)
    return QuotaPolicy(MemoryQuotas(clock), s, "sel"), clock


async def run(p, who, n, kind="check"):
    consume = p.consume_check if kind == "check" else p.consume_debate
    return [await consume(who) for _ in range(n)]


# ---------- politique (sans HTTP) ----------
@pytest.mark.parametrize("kind", ["check", "debate"])
async def test_logging_out_keeps_what_the_account_already_used(kind):
    p, _ = policy()
    assert await run(p, p.account("u:1", "1.1.1.1", participant="b1"), 3, kind) == [True, True, True]
    assert await run(p, p.anonymous("1.1.1.1", "b1"), 1, kind) == [False]  # 3 déjà utilisés ≥ 2 en anonyme
    usage = await p.usage(p.anonymous("1.1.1.1", "b1"))
    assert usage["checks" if kind == "check" else "debate"] == {"used": 3, "limit": 2, "remaining": 0}


@pytest.mark.parametrize("kind", ["check", "debate"])
async def test_logging_in_keeps_what_was_used_anonymously(kind):
    p, _ = policy()
    assert await run(p, p.anonymous("1.1.1.1", "b1"), 2, kind) == [True, True]
    who = p.account("u:1", "1.1.1.1", participant="b1")
    assert (await p.usage(who))["checks" if kind == "check" else "debate"] == {"used": 2, "limit": 4, "remaining": 2}
    assert await run(p, who, 3, kind) == [True, True, False]  # 2 + 2 = plafond du compte (4), pas 2 + 4


async def test_switching_account_on_the_same_browser_does_not_reset():
    p, _ = policy()
    await run(p, p.account("u:1", "1.1.1.1", participant="b1"), 3)
    assert await run(p, p.account("u:2", "1.1.1.1", participant="b1"), 2) == [True, False]  # reste 1 sur 4


async def test_another_browser_is_not_affected():
    p, _ = policy()
    await run(p, p.account("u:1", "1.1.1.1", participant="b1"), 3)
    assert await run(p, p.anonymous("2.2.2.2", "b2"), 3) == [True, True, False]


async def test_account_used_on_another_device_still_counts_on_a_new_browser():
    p, _ = policy()
    await run(p, p.account("u:1", "1.1.1.1", participant="b1"), 3)
    assert (await p.usage(p.account("u:1", "9.9.9.9", participant="b-new")))["checks"]["used"] == 3  # compteur du compte


async def test_without_a_browser_token_nothing_is_linked():
    p, _ = policy()
    await run(p, p.account("u:1", "1.1.1.1"), 3)
    assert await run(p, p.anonymous("1.1.1.1"), 3) == [True, True, False]


async def test_check_and_debate_budgets_stay_independent():
    p, _ = policy()
    await run(p, p.anonymous("1.1.1.1", "b1"), 2, "check")
    assert await run(p, p.anonymous("1.1.1.1", "b1"), 2, "debate") == [True, True]


async def test_refusal_because_of_the_person_charges_nothing_else():
    p, _ = policy()
    await run(p, p.account("u:1", "1.1.1.1", participant="b1"), 3)
    ip_before = await p.store.used("check", p.anonymous("1.1.1.1").key)
    assert await run(p, p.anonymous("1.1.1.1", "b1"), 5) == [False] * 5
    assert await p.store.used("check", p.anonymous("1.1.1.1").key) == ip_before == 0  # l'IP partagée n'est pas gonflée
    assert await run(p, p.anonymous("1.1.1.1", "other"), 2) == [True, True]  # un voisin de la même IP garde son quota


async def test_debate_refusal_does_not_touch_the_global_budget():
    p, _ = policy(debate_global_daily_checks=3)
    await run(p, p.account("u:1", "1.1.1.1", participant="b1"), 3, "debate")
    assert await run(p, p.anonymous("1.1.1.1", "b1"), 4, "debate") == [False] * 4
    assert await p.store.used("debate_global", "all") == 3


async def test_denied_requests_do_not_inflate_the_person_counter():
    p, _ = policy()
    who = p.anonymous("1.1.1.1", "b1")
    await run(p, who, 5)  # 2 acceptées, 3 refusées par l'état
    assert await p.store.used("person_check", who.person_key) == 2


async def test_a_refusal_by_the_account_does_not_inflate_the_person_counter():
    p, _ = policy()
    await run(p, p.account("u:1", "1.1.1.1", participant="b1"), 4)  # compte épuisé depuis le navigateur 1
    other = p.account("u:1", "5.5.5.5", participant="b2")  # même compte, autre appareil, jamais utilisé
    assert await run(p, other, 3) == [False] * 3
    assert await p.store.used("person_check", other.person_key) == 0  # rien n'a été consommé par ce navigateur


def test_request_participant_only_accepts_well_formed_tokens():
    from types import SimpleNamespace

    from app.api.deps import request_participant
    from app.core.identity import participant_id

    req = lambda v: SimpleNamespace(headers={"x-participant-token": v} if v is not None else {})  # noqa: E731
    assert request_participant(req(BROWSER_1)) == participant_id(BROWSER_1)
    for junk in (None, "", "court", "x" * 200, "a b" * 10, "../../etc/passwd" + "a" * 10):
        assert request_participant(req(junk)) is None


async def test_pro_plan_gets_its_own_limit_for_the_same_person():
    p, _ = policy()
    await run(p, p.anonymous("1.1.1.1", "b1"), 2)
    assert await run(p, p.account("u:1", "1.1.1.1", "pro", "b1"), 7) == [True] * 6 + [False]  # 2 + 6 = 8


async def test_counters_reset_at_the_next_utc_day():
    p, clock = policy()
    await run(p, p.account("u:1", "1.1.1.1", participant="b1"), 4)
    assert await run(p, p.anonymous("1.1.1.1", "b1"), 1) == [False]
    clock.now += timedelta(days=1)
    assert await run(p, p.anonymous("1.1.1.1", "b1"), 3) == [True, True, False]


async def test_browser_key_is_a_salted_hash_not_the_token():
    p, _ = policy()
    who = p.anonymous("1.1.1.1", "b1")
    assert who.person_key and "b1" not in who.person_key and who.person_key != p.anonymous("1.1.1.1", "b2").person_key
    other = QuotaPolicy(MemoryQuotas(), Settings(_env_file=None), "autre-sel")
    assert other.anonymous("1.1.1.1", "b1").person_key != who.person_key


# ---------- HTTP ----------
def post(c, session=None, browser=BROWSER_1):
    headers = {**(auth(session) if session else {}), **({"X-Participant-Token": browser} if browser else {})}
    return c.post(URL, json={"assertion": ASSERTION}, headers=headers)


def usage(c, session=None, browser=BROWSER_1):
    headers = {**(auth(session) if session else {}), **({"X-Participant-Token": browser} if browser else {})}
    return c.get("/api/v1/usage", headers=headers).json()["checks"]


def test_http_logout_after_using_the_account_quota_leaves_nothing():
    c = client_with_accounts(daily_check_limit=2, account_daily_check_limit=4)
    assert [post(c, TOKEN_A).status_code for _ in range(3)] == [200, 200, 200]
    assert post(c).status_code == 429
    assert usage(c) == {"used": 3, "limit": 2, "remaining": 0}


def test_http_login_after_anonymous_use_deducts_it():
    c = client_with_accounts(daily_check_limit=2, account_daily_check_limit=4)
    assert [post(c).status_code for _ in range(2)] == [200, 200]
    assert usage(c, TOKEN_A) == {"used": 2, "limit": 4, "remaining": 2}
    assert [post(c, TOKEN_A).status_code for _ in range(3)] == [200, 200, 429]


def test_http_accounts_on_one_browser_share_the_persons_usage():
    c = client_with_accounts(daily_check_limit=2, account_daily_check_limit=4)
    assert [post(c, TOKEN_A).status_code for _ in range(3)] == [200, 200, 200]
    assert [post(c, TOKEN_B).status_code for _ in range(2)] == [200, 429]


def test_http_other_browser_is_untouched():
    c = client_with_accounts(daily_check_limit=2, account_daily_check_limit=4)
    for _ in range(3):
        post(c, TOKEN_A)
    assert [post(c, browser=BROWSER_2).status_code for _ in range(3)] == [200, 200, 429]


def test_http_without_the_header_behaves_as_before():
    c = client_with_accounts(daily_check_limit=2, account_daily_check_limit=4)
    assert [post(c, TOKEN_A, browser=None).status_code for _ in range(3)] == [200, 200, 200]
    assert [post(c, browser=None).status_code for _ in range(3)] == [200, 200, 429]
    assert usage(c, browser=None) == {"used": 2, "limit": 2, "remaining": 0}


@pytest.mark.parametrize("junk", ["", "court", "x" * 200, "a b c d e f g h i j k l m n o p", "../../etc/passwd" + "a" * 10, "tok\ten" + "a" * 30])
def test_http_malformed_browser_token_is_ignored_not_an_error(junk):
    c = client_with_accounts(daily_check_limit=2, account_daily_check_limit=4)
    for _ in range(3):
        post(c, TOKEN_A)
    r = c.post(URL, json={"assertion": ASSERTION}, headers={"X-Participant-Token": junk})
    assert r.status_code == 200  # jeton illisible : aucun lien, quota anonyme intact


def test_http_a_guessed_token_cannot_spend_someone_elses_quota_without_knowing_it():
    c = client_with_accounts(daily_check_limit=2, account_daily_check_limit=4)
    for _ in range(3):
        post(c, TOKEN_A)
    assert post(c, browser="z" * 43).status_code == 200  # un autre jeton valide n'hérite de rien


def test_http_refused_request_does_not_consume_the_shared_ip_counter():
    c = client_with_accounts(daily_check_limit=2, account_daily_check_limit=4)
    for _ in range(3):
        post(c, TOKEN_A)
    for _ in range(5):
        assert post(c).status_code == 429
    assert [post(c, browser=BROWSER_2).status_code for _ in range(3)] == [200, 200, 429]  # même IP, quota intact


# ---------- WebSocket (débat), vraie base ----------
@pytest.mark.skipif(not DB, reason="FACTS_TEST_DATABASE_URL non défini")
def test_ws_debate_budget_follows_the_person_both_ways(fresh_db):
    msg = lambda i: {"type": "message", "text": f"Selon l'INSEE, l'inflation est de {i + 2} % en 2025."}  # noqa: E731
    with make_client(debate_daily_checks=2, account_debate_daily_checks=3, rate_limit_requests=1000) as c:
        room = create(c, ANON, visibility="public").json()["id"]
        sess = session_for(c, participant=ANON)

        def play(n, **hello):
            out = []
            with c.websocket_connect(f"/api/v1/rooms/{room}/ws") as ws:
                ws.send_json({"type": "hello", "token": ANON, **hello})
                recv_until(ws, "snapshot")
                for i in range(n):
                    ws.send_json(msg(i))
                    out.append(recv_until(ws, "message")["message"]["check"]["status"])
            return out

        assert play(2) == ["pending", "pending"]  # anonyme : 2 utilisés
        assert play(3, session=sess) == ["pending", "unchecked", "unchecked"]  # compte : 3 − 2 = 1 restant
        assert play(1) == ["unchecked"]  # déconnecté : 3 utilisés ≥ 2
        shown = c.get("/api/v1/usage", headers={**auth(sess), "X-Participant-Token": ANON}).json()["debate"]
        assert shown == {"used": 3, "limit": 3, "remaining": 0}
