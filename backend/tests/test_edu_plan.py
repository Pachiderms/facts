"""Plan Edu : licences accordées à la main, capacité des salons par plan, budget de vérifications, compteurs mensuels.
Fonctionnel + sécurité (administration fermée, entrées bornées, aucun contournement des quotas personnels)."""

import asyncio
import os
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import Settings
from app.core.quotas import MemoryQuotas, PostgresQuotas, seconds_until_next_month, window_start
from app.main import create_app
from app.services.quota_policy import GLOBAL_KEY, POOL_KIND, POOL_REASON, ROOM_BUDGET_REASON, QuotaPolicy
from app.services.rooms import CheckLimits, Room, RoomFullError
from tests.test_account_rooms_api import ANON, create, session_for
from tests.test_accounts_api import CLIENT_ID, KEYS, Clock as GoogleClock, FakeGoogle, auth, fresh_db, login, query  # noqa: F401
from tests.test_rooms_create import NullChecker, Quiet

URL = os.environ.get("FACTS_TEST_DATABASE_URL", "")
db_only = pytest.mark.skipif(not URL, reason="FACTS_TEST_DATABASE_URL non défini")
ADMIN = "a" * 40
BEARER = {"Authorization": f"Bearer {ADMIN}"}


class Clock:
    def __init__(self, now=datetime(2026, 11, 13, 12, tzinfo=timezone.utc)):
        self.now = now

    def __call__(self):
        return self.now


def policy(**kw):
    clock = Clock()
    kw = {"edu_room_check_budget": 3, "edu_monthly_check_pool": 5, "debate_global_daily_checks": 100, **kw}
    s = Settings(_env_file=None, **kw)
    return QuotaPolicy(MemoryQuotas(clock), s, "sel"), clock


# ====================== capacité par plan ======================
@pytest.mark.parametrize("plan,expected", [("anonymous", 8), ("free", 8), ("pro", 20), ("edu", 300), ("n'importe quoi", 8)])
def test_room_capacity_by_plan(plan, expected):
    p, _ = policy()
    assert p.room_capacity(plan) == expected


def test_capacity_never_exceeds_the_technical_ceiling():
    p, _ = policy(ws_max_room_connections=50)
    assert p.room_capacity("edu") == 50


def test_plan_grants_cannot_be_forged_through_the_policy():
    p, _ = policy()
    assert p.account("u:1", "1.1.1.1", "edu").plan == "edu"
    assert p.account("u:1", "1.1.1.1", "admin").plan == "free"  # un plan inconnu ne donne jamais plus que « free »
    edu = p.account("u:1", "1.1.1.1", "edu")
    assert p.check_limit(edu) == p._s.pro_daily_check_limit and p.debate_limit(edu) == p._s.pro_debate_daily_checks


def room(**kw):
    return Room("r", "Titre", "Cat", "social", NullChecker(), CheckLimits(2, 20, 5.0), **kw)


def test_room_total_connections_are_capped_by_capacity():
    r = room(max_participants=2, max_clients=5, max_spectators=5)
    for i in range(5):
        r.join(Quiet().send, f"p{i}")
    with pytest.raises(RoomFullError):
        r.join(Quiet().send, "de-trop")
    r.join(Quiet().send, "p0")  # une reconnexion d'une personne déjà présente reste possible


def test_edu_room_accepts_far_more_spectators_than_the_default_limit():
    r = room(max_participants=2, max_clients=60, max_spectators=60)
    roles = [r.join(Quiet().send, f"p{i}")[0].role for i in range(60)]
    assert roles.count("spectator") == 58  # au-delà de MAX_SPECTATORS (20), jusqu'à la capacité
    with pytest.raises(RoomFullError):
        r.join(Quiet().send, "61e")


def test_default_room_keeps_the_spectator_limit():
    r = room(max_participants=2, max_clients=1000)
    for i in range(22):
        r.join(Quiet().send, f"p{i}")
    with pytest.raises(RoomFullError):
        r.join(Quiet().send, "p22")


# ====================== budget de vérifications ======================
async def test_room_budget_caps_checks_per_room_and_gives_a_reason():
    p, _ = policy()
    b = p.room_budget("u:1", pool=100)
    assert [await p.consume_room_check(b) for _ in range(4)] == [True, True, True, ROOM_BUDGET_REASON]
    assert b.used == 3
    assert await p.store.used(POOL_KIND, b.pool_key) == 3  # le refus n'a pas consommé le pool


async def test_pool_is_shared_between_the_rooms_of_one_licence_and_stops_them_all():
    p, _ = policy()
    a, b = p.room_budget("u:1", pool=4), p.room_budget("u:1", pool=4)
    assert [await p.consume_room_check(a) for _ in range(3)] == [True] * 3
    assert await p.consume_room_check(b) is True
    assert await p.consume_room_check(b) == POOL_REASON
    assert b.used == 1  # le refus a rendu sa place réservée dans le salon
    other = p.room_budget("u:2", pool=4)  # une autre licence a son propre pool
    assert await p.consume_room_check(other) is True


async def test_pool_default_comes_from_settings_when_the_licence_has_none():
    p, _ = policy()
    assert p.room_budget("u:1", None).pool_limit == 5
    assert p.room_budget("u:1", 77).pool_limit == 77


async def test_pool_resets_next_month_not_next_day():
    p, clock = policy()
    b1 = p.room_budget("u:1", pool=2)
    assert [await p.consume_room_check(b1) for _ in range(3)] == [True, True, POOL_REASON]
    clock.now = datetime(2026, 11, 30, 23, 59, tzinfo=timezone.utc)  # même mois : toujours épuisé
    assert await p.consume_room_check(p.room_budget("u:1", pool=2)) == POOL_REASON
    clock.now = datetime(2026, 12, 1, 0, 1, tzinfo=timezone.utc)  # mois suivant : remis à zéro
    assert await p.consume_room_check(p.room_budget("u:1", pool=2)) is True


async def test_edu_checks_never_touch_personal_quotas():
    p, _ = policy()
    student = p.anonymous("1.1.1.1", "browser")
    b = p.room_budget("u:1", pool=10)
    for _ in range(3):
        await p.consume_room_check(b)
    usage = await p.usage(student)
    assert usage["debate"]["used"] == 0 and usage["checks"]["used"] == 0


async def test_exhausted_global_budget_refuses_without_wasting_pool_or_room_budget():
    p, _ = policy(debate_global_daily_checks=1)
    b = p.room_budget("u:1", pool=10)
    assert await p.consume_room_check(b) is True
    assert await p.consume_room_check(b) is False  # budget global du jour épuisé : « quota du jour »
    assert b.used == 1 and await p.store.used(POOL_KIND, b.pool_key) == 1


async def test_concurrent_checks_never_exceed_the_room_cap():
    p, _ = policy(edu_room_check_budget=5)
    b = p.room_budget("u:1", pool=1000)
    results = await asyncio.gather(*(p.consume_room_check(b) for _ in range(40)))
    assert results.count(True) == 5 and b.used == 5


async def test_store_failure_releases_the_reserved_room_slot():
    p, _ = policy()

    class Boom:
        async def used(self, *a):
            raise RuntimeError("base")

    p.store = Boom()
    b = p.room_budget("u:1", pool=10)
    with pytest.raises(RuntimeError):
        await p.consume_room_check(b)
    assert b.used == 0


# ====================== fenêtre mensuelle ======================
def test_window_start_is_daily_or_monthly_by_kind():
    now = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
    assert window_start("check", now).isoformat() == "2026-11-13"
    assert window_start("m_edu_pool", now).isoformat() == "2026-11-01"


def test_seconds_until_next_month_handles_year_end():
    assert seconds_until_next_month(datetime(2026, 12, 31, 23, 59, 0, tzinfo=timezone.utc)) == 61
    assert seconds_until_next_month(datetime(2026, 2, 28, 0, 0, 0, tzinfo=timezone.utc)) == 86_400 + 1


async def test_memory_store_keeps_monthly_counters_when_evicting_daily_ones():
    clock = Clock()
    s = MemoryQuotas(clock, max_keys=2)
    await s.consume("m_edu_pool", "k", 10)
    await s.consume("check", "a", 10)
    clock.now = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)  # lendemain : « check » périmé, le mensuel reste
    await s.consume("check", "b", 10)
    await s.consume("check", "c", 10)  # plein : on évince d'abord les compteurs périmés
    assert await s.used("m_edu_pool", "k") == 1


# ====================== Room : motif du refus ======================
class OneShotChecker:
    async def check(self, text):
        raise AssertionError("la vérification ne doit pas partir")


async def post(r, allow, text="La hausse du SMIC à 1700€ net est dangereuse pour l'économie française."):
    client, _ = r.join(Quiet().send, "a")
    return await r.post_message(client, text, allow_check=allow)


async def test_refusal_reason_is_published_on_the_message():
    r = room(checkable=lambda t: True)

    async def deny():
        return POOL_REASON

    msg = await post(r, deny)
    assert msg["check"]["status"] == "unchecked" and msg["check"]["badge_text"] == POOL_REASON


async def test_plain_refusal_keeps_the_daily_quota_wording():
    r = room(checkable=lambda t: True)

    async def deny():
        return False

    assert (await post(r, deny))["check"]["badge_text"] == "QUOTA DU JOUR ATTEINT"


async def test_empty_reason_string_is_a_refusal_with_the_default_wording():
    r = room(checkable=lambda t: True)

    async def deny():
        return ""

    assert (await post(r, deny))["check"]["badge_text"] == "QUOTA DU JOUR ATTEINT"


async def test_granted_check_starts_a_pending_verification():
    r = room(checkable=lambda t: True)

    async def ok():
        return True

    msg = await post(r, ok)
    assert msg["check"]["status"] == "pending"
    await r.aclose()


# ====================== PostgreSQL ======================
@db_only
async def test_purge_keeps_current_monthly_counters(fresh_db):
    clock = Clock()
    store = PostgresQuotas(fresh_db, clock=clock)
    await store.consume("m_edu_pool", "k", 100)
    await store.consume("check", "old", 100)
    clock.now = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)
    import app.core.quotas as q

    old, q.PURGE_EVERY = q.PURGE_EVERY, 1
    try:
        await store.consume("check", "new", 100)  # déclenche la purge
    finally:
        q.PURGE_EVERY = old
    assert await store.used("m_edu_pool", "k") == 1  # le mensuel du mois en cours survit
    assert await store.used("check", "old") == 0


@db_only
async def test_purge_drops_monthly_counters_older_than_the_previous_month(fresh_db):
    clock = Clock()
    store = PostgresQuotas(fresh_db, clock=clock)
    await store.consume("m_edu_pool", "k", 100)
    clock.now = datetime(2027, 1, 15, 12, tzinfo=timezone.utc)
    import app.core.quotas as q

    old, q.PURGE_EVERY = q.PURGE_EVERY, 1
    try:
        await store.consume("check", "x", 100)
    finally:
        q.PURGE_EVERY = old
    async with fresh_db.session() as s:
        n = (await s.execute(text("SELECT count(*) FROM usage_counters WHERE kind = 'm_edu_pool'"))).scalar_one()
    assert n == 0


@db_only
async def test_monthly_counter_is_atomic_and_durable(fresh_db):
    store = PostgresQuotas(fresh_db)
    results = await asyncio.gather(*(store.consume("m_edu_pool", "k", 7) for _ in range(30)))
    assert results.count(True) == 7 and await store.used("m_edu_pool", "k") == 7


# ====================== API : administration ======================
def make(**kw) -> TestClient:
    from app.services.google_auth import GoogleVerifier

    settings = Settings(_env_file=None, database_url=URL, google_client_id=CLIENT_ID, llm_api_key="ci-dummy",
                        search_providers="wikipedia", read_rate_limit_requests=1000, admin_token=ADMIN, **kw)
    google = GoogleVerifier(CLIENT_ID, client=FakeGoogle(KEYS).client(), clock=GoogleClock())
    return TestClient(create_app(settings, google=google))


def grant(c, **body):
    return c.post("/api/v1/admin/plans/grant", json={"email": "prof@example.com", **body}, headers=BEARER)


@db_only
def test_admin_plan_endpoints_are_closed_without_the_exact_token(fresh_db):
    with make() as c:
        for method, path in [("get", "/plans"), ("post", "/plans/grant"), ("post", "/plans/revoke")]:
            r = getattr(c, method)("/api/v1/admin" + path, **({"json": {"email": "a@b.fr"}} if method == "post" else {}))
            assert r.status_code == 401
            r = getattr(c, method)("/api/v1/admin" + path, headers={"Authorization": "Bearer " + "b" * 40}, **({"json": {"email": "a@b.fr"}} if method == "post" else {}))
            assert r.status_code == 401


@db_only
def test_admin_plan_endpoints_do_not_exist_without_a_configured_token(fresh_db):
    settings = Settings(_env_file=None, database_url=URL, llm_api_key="ci-dummy", search_providers="wikipedia")
    with TestClient(create_app(settings)) as c:
        assert c.get("/api/v1/admin/plans", headers=BEARER).status_code == 404
        assert c.post("/api/v1/admin/plans/grant", json={"email": "a@b.fr"}, headers=BEARER).status_code == 404


@db_only
def test_a_user_session_is_not_an_admin_token(fresh_db):
    with make() as c:
        s = session_for(c, email="prof@example.com")
        assert c.post("/api/v1/admin/plans/grant", json={"email": "prof@example.com"}, headers=auth(s)).status_code == 401


@db_only
@pytest.mark.parametrize("body", [
    {"email": "pas-un-email"}, {"email": "a@b.fr", "plan": "pro"}, {"email": "a@b.fr", "plan": "admin"},
    {"email": "a@b.fr", "check_pool": 0}, {"email": "a@b.fr", "check_pool": -5}, {"email": "a@b.fr", "check_pool": 10**9},
    {"email": "a@b.fr", "days": 0}, {"email": "a@b.fr", "days": 99999}, {"email": "a@b.fr", "note": "x" * 201},
    {"email": "a@b.fr", "note": "a\x00b"}, {"email": "a@b.fr", "is_admin": True}, {"email": "a b@c.fr"},
])
def test_grant_rejects_invalid_input(fresh_db, body):
    with make() as c:
        assert c.post("/api/v1/admin/plans/grant", json=body, headers=BEARER).status_code == 422


@db_only
def test_grant_for_an_unknown_account_is_refused_clearly(fresh_db):
    with make() as c:
        r = grant(c)
        assert r.status_code == 404 and "se connecter" in r.json()["detail"]


@db_only
def test_grant_gives_edu_then_revoke_takes_it_back(fresh_db):
    with make() as c:
        s = session_for(c, email="prof@example.com")
        assert c.get("/api/v1/usage", headers=auth(s)).json()["plan"] == "free"
        r = grant(c, check_pool=1234, days=30, note="Lycée Test")
        assert r.status_code == 200 and r.json()["check_pool"] == 1234 and r.json()["expires_at"]
        c.app.state.plans._cache.clear()
        assert c.get("/api/v1/usage", headers=auth(s)).json()["plan"] == "edu"
        listing = c.get("/api/v1/admin/plans", headers=BEARER).json()["grants"]
        assert listing == [{"email": "prof@example.com", "plan": "edu", "check_pool": 1234, "note": "Lycée Test",
                            "expires_at": listing[0]["expires_at"], "active": True}]
        assert c.post("/api/v1/admin/plans/revoke", json={"email": "PROF@example.com"}, headers=BEARER).json() == {"revoked": True}
        assert c.get("/api/v1/usage", headers=auth(s)).json()["plan"] == "free"  # la révocation efface le cache : effet immédiat
        assert c.post("/api/v1/admin/plans/revoke", json={"email": "prof@example.com"}, headers=BEARER).json() == {"revoked": False}


@db_only
def test_regranting_updates_instead_of_duplicating(fresh_db):
    with make() as c:
        session_for(c, email="prof@example.com")
        grant(c, check_pool=10)
        grant(c, check_pool=20, note="v2")
        listing = c.get("/api/v1/admin/plans", headers=BEARER).json()["grants"]
        assert len(listing) == 1 and listing[0]["check_pool"] == 20 and listing[0]["note"] == "v2"


@db_only
def test_expired_grant_gives_nothing(fresh_db):
    with make() as c:
        s = session_for(c, email="prof@example.com")
        grant(c)
        query("UPDATE plan_grants SET expires_at = now() - interval '1 day'")
        c.app.state.plans._cache.clear()
        assert c.get("/api/v1/usage", headers=auth(s)).json()["plan"] == "free"
        assert c.get("/api/v1/admin/plans", headers=BEARER).json()["grants"][0]["active"] is False


@db_only
def test_grant_is_removed_with_the_account(fresh_db):
    with make() as c:
        s = session_for(c, email="prof@example.com")
        grant(c)
        query("DELETE FROM users WHERE email = 'prof@example.com'")
        assert query("SELECT count(*) FROM plan_grants")[0][0] == 0


@db_only
def test_database_check_constraints_refuse_unknown_plans_and_empty_pools(fresh_db):
    with make() as c:
        session_for(c, email="prof@example.com")
        for sql in ("INSERT INTO plan_grants (user_id, plan) SELECT id, 'pro' FROM users",
                    "INSERT INTO plan_grants (user_id, plan, check_pool) SELECT id, 'edu', 0 FROM users"):
            with pytest.raises(Exception):
                query(sql)


@db_only
def test_room_creation_applies_the_capacity_of_the_creator_plan(fresh_db):
    with make() as c:
        anon = create(c).json()["id"]
        s = session_for(c, email="prof@example.com")
        free = create(c, session=s).json()["id"]
        grant(c)
        c.app.state.plans._cache.clear()
        edu = create(c, session=s).json()["id"]
        rooms = c.app.state.rooms
        assert (rooms.get(anon).budget, rooms.get(anon)._max_clients) == (None, 8)
        assert (rooms.get(free).budget, rooms.get(free)._max_clients) == (None, 8)
        r = rooms.get(edu)
        assert r._max_clients == 300 and r._max_spectators == 300 and r.budget is not None
        assert r.budget.cap == 300 and r.budget.pool_limit == 5000  # valeurs par défaut des réglages


@db_only
def test_licence_pool_size_is_taken_from_the_grant(fresh_db):
    with make() as c:
        s = session_for(c, email="prof@example.com")
        grant(c, check_pool=42)
        c.app.state.plans._cache.clear()
        room = c.app.state.rooms.get(create(c, session=s).json()["id"])
        assert room.budget.pool_limit == 42


@db_only
def test_a_pro_subscriber_room_has_capacity_20_without_budget(fresh_db):
    with make() as c:
        s = session_for(c, email="prof@example.com")
        uid = query("SELECT id FROM users")[0][0]
        query("INSERT INTO subscriptions (user_id, provider, provider_subscription_id, provider_customer_id, status, current_period_end, event_at) "
              "VALUES (:u, 'lemonsqueezy', '1', '1', 'active', now() + interval '10 days', now())".replace(":u", f"'{uid}'"))
        c.app.state.billing._cache.clear()
        room = c.app.state.rooms.get(create(c, session=s).json()["id"])
        assert room._max_clients == 20 and room.budget is None


@db_only
def test_edu_room_websocket_uses_room_budget_and_lets_many_students_in_from_one_ip(fresh_db):
    with make(edu_room_check_budget=1, ws_max_connections_per_ip=2, ws_max_connections_per_ip_edu=6) as c:
        s = session_for(c, email="prof@example.com")
        grant(c)
        c.app.state.plans._cache.clear()
        room_id = create(c, session=s, visibility="public").json()["id"]
        sockets = []
        try:
            for i in range(5):  # 5 connexions depuis la même IP : refusées dans un salon ordinaire (plafond 2)
                ws = c.websocket_connect(f"/api/v1/rooms/{room_id}/ws").__enter__()
                ws.send_json({"type": "hello", "token": f"eleve-{i:02d}-" + "x" * 20})
                assert ws.receive_json()["type"] == "snapshot"
                sockets.append(ws)
            claim = "La hausse du SMIC à 1700€ net est dangereuse pour l'économie française."
            sockets[0].send_json({"type": "message", "text": claim})
            sockets[1].send_json({"type": "message", "text": claim + " Vraiment."})
            seen = []
            while len(seen) < 2:
                ev = sockets[0].receive_json()
                if ev["type"] == "message":
                    seen.append(ev["message"]["check"])
            assert seen[0]["status"] == "pending"
            assert seen[1]["status"] == "unchecked" and seen[1]["badge_text"] == ROOM_BUDGET_REASON
            personal = c.app.state.quota_policy
            student = personal.anonymous("testclient", "eleve-00-" + "x" * 20)
            assert (await_run(personal.usage(student)))["debate"]["used"] == 0  # le quota personnel de l'élève est intact
        finally:
            for ws in sockets:
                ws.__exit__(None, None, None)


def await_run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@db_only
def test_ordinary_room_keeps_the_low_per_ip_connection_cap(fresh_db):
    with make(ws_max_connections_per_ip=2, ws_max_connections_per_ip_edu=6) as c:
        room_id = create(c, visibility="public").json()["id"]
        opened = []
        try:
            for i in range(2):
                ws = c.websocket_connect(f"/api/v1/rooms/{room_id}/ws").__enter__()
                ws.send_json({"type": "hello", "token": f"visiteur-{i:02d}-" + "y" * 20})
                assert ws.receive_json()["type"] == "snapshot"
                opened.append(ws)
            with pytest.raises(Exception):
                with c.websocket_connect(f"/api/v1/rooms/{room_id}/ws") as ws3:
                    ws3.send_json({"type": "hello", "token": "visiteur-99-" + "y" * 20})
                    ws3.receive_json()
        finally:
            for ws in opened:
                ws.__exit__(None, None, None)
