"""Quotas durables (jour UTC), IP derrière un proxy, budget du débat. Fonctionnel + sécurité."""

import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from starlette.requests import Request

from app.core.quotas import MemoryQuotas, PostgresQuotas, make_key, seconds_until_next_day
from app.core.security import get_client_ip
from tests.test_api_rooms import CLAIM, connect, make_client, recv_until, send_message

URL = os.environ.get("FACTS_TEST_DATABASE_URL", "")


class Day:
    def __init__(self):
        self.now = datetime(2026, 11, 13, 10, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now


# ---------- IP derrière un proxy (régression : compteur qui ne baissait pas sur Render) ----------
def req(xff, client=("9.9.9.9", 1)):
    return Request({"type": "http", "headers": [(b"x-forwarded-for", xff.encode())], "client": client})


def test_hops_selects_the_entry_before_the_trailing_proxies():
    # Render derrière Cloudflare : « client, proxy » -> le client est l'avant-dernière entrée.
    assert get_client_ip(req("81.1.1.1, 172.70.0.5"), True, 1) == "81.1.1.1"
    assert get_client_ip(req("81.1.1.1, 172.70.0.5"), True, 0) == "172.70.0.5"  # comportement historique
    assert get_client_ip(req("a, 81.1.1.1, p1, p2"), True, 2) == "81.1.1.1"


def test_a_changing_trailing_proxy_does_not_change_the_visitor():
    ips = {get_client_ip(req(f"81.1.1.1, 172.70.0.{n}"), True, 1) for n in range(20)}
    assert ips == {"81.1.1.1"}


def test_client_cannot_forge_its_ip_by_prepending_entries():
    assert get_client_ip(req("6.6.6.6, 81.1.1.1, 172.70.0.5"), True, 1) == "81.1.1.1"


def test_short_chain_or_garbage_falls_back_to_the_connection_address():
    assert get_client_ip(req("172.70.0.5"), True, 1) == "9.9.9.9"  # accès direct sans le proxy attendu
    assert get_client_ip(req(", 1.1.1.1"), True, 1) == "9.9.9.9"  # entrée vide
    assert get_client_ip(req("81.1.1.1, 172.70.0.5"), False, 1) == "9.9.9.9"  # en-tête ignoré si non fiable
    assert get_client_ip(req("81.1.1.1, 172.70.0.5"), True, -3) == "172.70.0.5"  # négatif traité comme 0


def test_health_ip_diagnostic_reports_only_the_callers_own_view():
    with make_client(trust_proxy_headers=True, proxy_hops=1) as c:
        body = c.get("/health/ip", headers={"X-Forwarded-For": "81.1.1.1, 172.70.0.5"}).json()
        assert body["resolved_ip"] == "81.1.1.1" and body["proxy_hops"] == 1 and body["trust_proxy_headers"] is True


def test_quota_counts_per_visitor_even_when_the_proxy_address_changes():
    with make_client(trust_proxy_headers=True, proxy_hops=1, daily_check_limit=2, rate_limit_requests=1000) as c:
        body = {"assertion": "Le chômage a baissé en France depuis 2017."}
        codes = [c.post("/api/v1/check", json=body, headers={"X-Forwarded-For": f"81.1.1.1, 172.70.0.{n}"}).status_code for n in range(3)]
        assert codes == [200, 200, 429]
        used = c.get("/api/v1/usage", headers={"X-Forwarded-For": "81.1.1.1, 172.70.9.9"}).json()["checks"]
        assert used == {"used": 2, "limit": 2, "remaining": 0}


# ---------- stockage mémoire ----------
async def test_memory_quota_limit_and_day_rollover():
    day = Day()
    q = MemoryQuotas(day)
    assert [await q.consume("check", "k", 2) for _ in range(3)] == [True, True, False]
    assert await q.used("check", "k") == 2 and await q.used("check", "autre") == 0 and await q.used("debate", "k") == 0
    day.now += timedelta(days=1)
    assert await q.used("check", "k") == 0 and await q.consume("check", "k", 2)


async def test_memory_quota_is_bounded():
    q = MemoryQuotas(max_keys=10)
    for i in range(50):
        await q.consume("check", str(i), 5)
    assert len(q._counts) <= 10


def test_retry_after_is_the_time_until_midnight_utc():
    assert seconds_until_next_day(datetime(2026, 11, 13, 23, 59, 0, tzinfo=timezone.utc)) == 61
    assert seconds_until_next_day(datetime(2026, 11, 13, 0, 0, 0, tzinfo=timezone.utc)) == 86_401


def test_keys_are_salted_and_never_contain_the_address():
    a, b = make_key("sel1", "ip:81.1.1.1"), make_key("sel2", "ip:81.1.1.1")
    assert a != b and "81.1.1.1" not in a and len(a) == 32 and make_key("sel1", "ip:81.1.1.1") == a


# ---------- stockage Postgres ----------
pg = pytest.mark.skipif(not URL, reason="FACTS_TEST_DATABASE_URL non défini")


@pytest.fixture
async def database():
    from app.db.engine import Database
    from tests.test_db_integration import migrate

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


@pg
async def test_pg_limit_and_persistence_across_restarts(database):
    day = Day()
    assert [await PostgresQuotas(database, clock=day).consume("check", "k", 2) for _ in range(3)] == [True, True, False]
    restarted = PostgresQuotas(database, clock=day)  # nouveau processus : le compteur survit
    assert await restarted.used("check", "k") == 2 and not await restarted.consume("check", "k", 2)


@pg
async def test_pg_is_atomic_under_concurrency(database):
    q = PostgresQuotas(database)
    results = await asyncio.gather(*(q.consume("check", "k", 5) for _ in range(40)))
    assert sum(results) == 5 and await q.used("check", "k") == 5


@pg
async def test_pg_day_rollover_and_purge(database):
    from app.core import quotas

    day = Day()
    q = PostgresQuotas(database, clock=day)
    await q.consume("check", "old", 5)
    day.now += timedelta(days=3)
    assert await q.used("check", "old") == 0 and await q.consume("check", "old", 1)
    quotas.PURGE_EVERY = 1
    await q.consume("check", "autre", 5)  # déclenche la purge des jours trop anciens
    async with database.session() as s:
        days = (await s.execute(text("SELECT DISTINCT day FROM usage_counters"))).scalars().all()
    assert len(days) == 1
    quotas.PURGE_EVERY = 500


@pg
async def test_pg_falls_back_to_memory_when_the_database_fails(database):
    q = PostgresQuotas(database)
    await database.aclose()  # base injoignable
    q._db = type("Broken", (), {"session": lambda self: (_ for _ in ()).throw(RuntimeError("secret-host"))})()
    assert [await q.consume("check", "k", 1) for _ in range(2)] == [True, False]  # la limite tient quand même
    assert await q.used("check", "k") == 1


@pg
async def test_pg_stores_only_salted_keys(database):
    from app.core.quotas import PostgresQuotas as P

    q = P(database)
    await q.consume("check", make_key("sel", "ip:81.1.1.1"), 3)
    async with database.session() as s:
        rows = (await s.execute(text("SELECT key FROM usage_counters"))).scalars().all()
    assert rows and all("81.1.1.1" not in r for r in rows)


# ---------- budget du débat ----------
def start_two(c):
    return connect(c, n=1), connect(c, n=2)


def test_debate_message_beyond_the_daily_budget_is_posted_unchecked():
    with make_client(debate_daily_checks=2) as c, connect(c, n=1) as a:
        recv_until(a, "snapshot")
        for _ in range(2):
            send_message(a, CLAIM)
            assert recv_until(a, "message")["message"]["check"]["status"] == "pending"
            recv_until(a, "check_result")
        send_message(a, CLAIM)
        msg = recv_until(a, "message")["message"]
        assert msg["check"]["status"] == "unchecked" and "QUOTA" in msg["check"]["badge_text"]


def test_over_budget_message_never_reaches_the_checker():
    with make_client(debate_daily_checks=1) as c, connect(c, n=1) as a:
        recv_until(a, "snapshot")
        send_message(a, CLAIM)
        recv_until(a, "check_result")
        send_message(a, CLAIM + " bis")
        recv_until(a, "message")
        send_message(a, CLAIM + " ter")
        recv_until(a, "message")
        assert len(c.app.state.service.calls) == 1  # seul le premier message a coûté un appel


def test_global_debate_budget_protects_the_chatbot_share():
    with make_client(debate_global_daily_checks=1, debate_daily_checks=40) as c:
        with connect(c, n=1) as a:
            recv_until(a, "snapshot")
            send_message(a, CLAIM)
            recv_until(a, "check_result")
        with connect(c, n=2) as b:  # autre personne : le budget global est épuisé pour tous
            recv_until(b, "snapshot")
            send_message(b, CLAIM)
            assert recv_until(b, "message")["message"]["check"]["status"] == "unchecked"


def test_debate_and_chatbot_budgets_are_independent():
    with make_client(debate_daily_checks=1, daily_check_limit=1, rate_limit_requests=1000) as c:
        with connect(c, n=1) as a:
            recv_until(a, "snapshot")
            send_message(a, CLAIM)
            recv_until(a, "check_result")
        body = {"assertion": "Le chômage a baissé en France depuis 2017."}
        assert c.post("/api/v1/check", json=body).status_code == 200  # le débat n'a pas entamé le quota du chatbot
        usage = c.get("/api/v1/usage").json()
        assert usage["debate"]["used"] == 1 and usage["checks"]["used"] == 1


def test_non_checkable_messages_cost_nothing():
    with make_client(debate_daily_checks=1) as c, connect(c, n=1) as a:
        recv_until(a, "snapshot")
        for _ in range(3):
            send_message(a, "Bonjour tout le monde.")
            assert recv_until(a, "message")["message"]["check"]["status"] != "unchecked"
        assert c.get("/api/v1/usage").json()["debate"]["used"] == 0


async def test_ip_backstop_limits_debate_budget_multiplied_by_accounts():
    from app.core.config import Settings
    from app.services.quota_policy import QuotaPolicy

    policy = QuotaPolicy(MemoryQuotas(), Settings(_env_file=None, debate_daily_checks=1, account_debate_daily_checks=100), "sel")
    granted = [await policy.consume_debate(policy.account(f"compte-{i}", "81.1.1.1")) for i in range(8)]
    assert granted == [True] * 4 + [False] * 4  # 4 x le plafond anonyme, quel que soit le nombre de comptes
    assert await policy.consume_debate(policy.account("autre", "82.2.2.2"))  # une autre connexion n'est pas touchée
