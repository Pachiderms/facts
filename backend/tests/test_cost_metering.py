"""Mesure des coûts : exactitude des compteurs, aucune donnée personnelle, endpoint fermé sans jeton, écriture durable."""

import asyncio
import json
import os
from datetime import date, datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.adapters.llm import LLMError, LLMRateLimitError, OpenAICompatibleLLM, ResilientLLM
from app.adapters.search import SearchError
from app.adapters.search_chain import FallbackSearch, GuardedProvider
from app.core import metering
from app.core.cache import TTLCache
from app.core.config import Settings, parse_prices
from app.core.metering import UsageMeter, default_operation, operation, record_llm, record_search
from app.core.resilience import CircuitBreaker, MonthlyQuota
from app.db.schema import cost_usage
from app.main import create_app
from app.services.costs import CostRecorder, build_report
from app.services.factcheck import FactCheckService
from app.services.message_checker import FactCheckMessageChecker
from app.services.retrieval import Retriever
from tests.conftest import IFRAP, OFCE, QUERIES, ScriptedLLM, StaticProvider, analysis
from tests.test_accounts_api import fresh_db  # noqa: F401  (fixture)

URL = os.environ.get("FACTS_TEST_DATABASE_URL", "")
db_only = pytest.mark.skipif(not URL, reason="FACTS_TEST_DATABASE_URL non défini")
D1, D2 = date(2026, 11, 13), date(2026, 11, 14)


class Day:
    def __init__(self, d=D1):
        self.d = d

    def __call__(self):
        return datetime(self.d.year, self.d.month, self.d.day, 12, tzinfo=timezone.utc)


@pytest.fixture
def meter():
    m = UsageMeter("beta", clock=Day())
    metering.set_meter(m)
    yield m
    metering.set_meter(None)


def rows(m: UsageMeter):
    return {k: v for k, v in m._pending.items()}


def one(m, kind, name, op="other"):
    return m._pending[(D1, "beta", op, kind, name)]


# ---------- compteurs ----------
def test_llm_calls_are_summed_per_model_and_operation(meter):
    with operation("check"):
        record_llm("m1", 100, 20)
        record_llm("m1", 50, 5)
        record_llm("m2", 10, 1)
    record_llm("m1", 7, 7)  # hors opération : « other »
    c = one(meter, "llm", "m1", "check")
    assert (c.calls, c.prompt_tokens, c.completion_tokens, c.errors) == (2, 150, 25, 0)
    assert one(meter, "llm", "m2", "check").calls == 1
    assert one(meter, "llm", "m1", "other").prompt_tokens == 7


def test_errors_are_counted_apart_and_never_add_tokens(meter):
    record_llm("m", 999, 999, error=True)
    c = one(meter, "llm", "m")
    assert (c.calls, c.errors, c.prompt_tokens, c.completion_tokens) == (0, 1, 0, 0)


def test_search_credits_and_free_engines(meter):
    with operation("check"):
        record_search("tavily", 1)
        record_search("tavily", 1)
        record_search("wikipedia", 0)
        record_search("tavily", error=True)
    t, w = one(meter, "search", "tavily", "check"), one(meter, "search", "wikipedia", "check")
    assert (t.calls, t.credits, t.errors) == (2, 2, 1) and (w.calls, w.credits) == (1, 0)


def test_action_is_counted_once_per_scope_and_not_when_disabled(meter):
    with operation("check"):
        with default_operation("check"):  # imbriqué, même étiquette : pas d'action de plus
            pass
    with operation("moderation", count_action=False):
        pass
    assert meter._pending[(D1, "beta", "check", "action", "-")].calls == 1
    assert (D1, "beta", "moderation", "action", "-") not in meter._pending


def test_default_operation_never_overrides_the_callers_label(meter):
    with operation("room_check"):
        with default_operation("check"):
            record_llm("m", 1, 1)
    assert (D1, "beta", "room_check", "llm", "m") in meter._pending
    assert (D1, "beta", "check", "llm", "m") not in meter._pending


def test_label_does_not_leak_after_the_block_even_on_error(meter):
    with pytest.raises(RuntimeError):
        with operation("check"):
            raise RuntimeError
    record_llm("m", 1, 1)
    assert (D1, "beta", "other", "llm", "m") in meter._pending


async def test_label_follows_concurrent_tasks_without_mixing(meter):
    async def work(op, model):
        with operation(op):
            await asyncio.sleep(0)
            await asyncio.gather(*(asyncio.create_task(asyncio.sleep(0)) for _ in range(2)))
            record_llm(model, 1, 1)

    await asyncio.gather(work("check", "a"), work("moderation", "b"))
    assert (D1, "beta", "check", "llm", "a") in meter._pending
    assert (D1, "beta", "moderation", "llm", "b") in meter._pending
    assert (D1, "beta", "check", "llm", "b") not in meter._pending


def test_without_a_meter_everything_is_a_noop():
    metering.set_meter(None)
    with operation("check"):
        record_llm("m", 5, 5)
        record_search("tavily", 1)


@pytest.mark.parametrize("bad", [-5, "12", None, True, float("nan"), float("inf"), float("-inf"), [1], {"a": 1}])
def test_absurd_token_values_count_as_zero(meter, bad):
    try:
        record_llm("m", bad, bad)
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"ne doit jamais lever : {exc!r}")
    c = one(meter, "llm", "m")
    assert c.calls == 1 and c.prompt_tokens == 0 and c.completion_tokens == 0


def test_huge_values_are_capped(meter):
    record_llm("m", 10**15, 10**15)
    assert one(meter, "llm", "m").prompt_tokens == metering.MAX_TOKENS


def test_model_names_are_sanitized_and_bounded(meter):
    record_llm("x" * 500 + "\n\x00", 1, 1)
    (key,) = rows(meter)
    assert len(key[4]) == metering.MAX_NAME and key[4].isprintable()
    record_llm("", 1, 1)
    assert any(k[4] == "?" for k in rows(meter))
    record_llm("mod\x00\x1bel\n", 1, 1)
    assert any(k[4] == "model" for k in rows(meter))  # caractères de contrôle retirés (journaux, affichage)


def test_take_empties_and_restore_adds_back(meter):
    record_llm("m", 10, 1)
    taken = meter.take()
    assert len(meter) == 0
    record_llm("m", 5, 1)  # arrivé pendant l'écriture
    meter.restore(taken)
    assert one(meter, "llm", "m").prompt_tokens == 15 and one(meter, "llm", "m").calls == 2


def test_counters_follow_the_utc_day():
    clock = Day(D1)
    m = UsageMeter("v1", clock=clock)
    metering.set_meter(m)
    try:
        record_llm("m", 1, 1)
        clock.d = D2
        record_llm("m", 1, 1)
    finally:
        metering.set_meter(None)
    assert {k[0] for k in m._pending} == {D1, D2} and {k[1] for k in m._pending} == {"v1"}


# ---------- adaptateurs ----------
def llm_with(handler, model="mod-a"):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenAICompatibleLLM("https://llm.example/v1", model, "k", client=client, max_retries=0)


def reply(content="ok", usage=None):
    body = {"choices": [{"message": {"content": content}}]}
    if usage is not None:
        body["usage"] = usage
    return httpx.Response(200, json=body)


async def test_adapter_records_the_providers_token_usage(meter):
    llm = llm_with(lambda r: reply(usage={"prompt_tokens": 321, "completion_tokens": 45, "total_tokens": 366}))
    with operation("check"):
        await llm.complete("sys", "user")
    c = one(meter, "llm", "mod-a", "check")
    assert (c.calls, c.prompt_tokens, c.completion_tokens) == (1, 321, 45)


@pytest.mark.parametrize("usage", [None, "x", [1], {"prompt_tokens": "a"}, {}])
async def test_adapter_survives_missing_or_malformed_usage(meter, usage):
    llm = llm_with(lambda r: reply(usage=usage))
    assert await llm.complete("s", "u") == "ok"
    c = one(meter, "llm", "mod-a")
    assert (c.calls, c.prompt_tokens, c.completion_tokens, c.errors) == (1, 0, 0, 0)


@pytest.mark.parametrize(
    "response,exc",
    [
        (httpx.Response(429), LLMRateLimitError),
        (httpx.Response(500), LLMError),
        (httpx.Response(400, text="secret"), LLMError),
        (httpx.Response(200, text="pas du json"), LLMError),
        (reply(content="   "), LLMError),
    ],
)
async def test_adapter_failures_are_counted_as_errors_and_still_raise(meter, response, exc):
    llm = llm_with(lambda r: response)
    with pytest.raises(exc):
        await llm.complete("s", "u")
    c = one(meter, "llm", "mod-a")
    assert (c.calls, c.errors, c.prompt_tokens) == (0, 1, 0)


async def test_transport_error_is_counted(meter):
    def boom(request):
        raise httpx.ConnectError("x")

    with pytest.raises(LLMError):
        await llm_with(boom).complete("s", "u")
    assert one(meter, "llm", "mod-a").errors == 1


async def test_fallback_model_is_billed_under_its_own_name(meter):
    primary = llm_with(lambda r: httpx.Response(429), "primary")
    fallback = llm_with(lambda r: reply(usage={"prompt_tokens": 9, "completion_tokens": 3}), "fallback")
    out = await ResilientLLM(primary, fallback).complete("s", "u")
    assert out == "ok"
    assert one(meter, "llm", "primary").errors == 1
    assert one(meter, "llm", "fallback").prompt_tokens == 9


async def test_no_prompt_or_answer_text_ever_reaches_the_meter(meter):
    secret = "MON-TEXTE-PRIVE-12345"
    llm = llm_with(lambda r: reply(content=secret, usage={"prompt_tokens": 1, "completion_tokens": 1}))
    with operation("check"):
        await llm.complete(secret, secret)
    assert secret not in repr(meter._pending)


def guarded(name, provider, quota=None):
    return GuardedProvider(name, provider, CircuitBreaker(5, 60), quota)


async def test_search_chain_records_credits_only_for_tavily(meter):
    chain = FallbackSearch([guarded("tavily", StaticProvider([OFCE])), guarded("wikipedia", StaticProvider([IFRAP]))])
    with operation("check"):
        await chain.search("q", 5)
    assert (one(meter, "search", "tavily", "check").calls, one(meter, "search", "tavily", "check").credits) == (1, 1)
    assert (D1, "beta", "check", "search", "wikipedia") not in meter._pending  # jamais appelé


async def test_search_failure_costs_no_credit_and_fallback_is_free(meter):
    chain = FallbackSearch([guarded("tavily", StaticProvider(error=SearchError("x"))), guarded("wikipedia", StaticProvider([IFRAP]))])
    await chain.search("q", 5)
    t, w = one(meter, "search", "tavily"), one(meter, "search", "wikipedia")
    assert (t.errors, t.credits, t.calls) == (1, 0, 0) and (w.calls, w.credits) == (1, 0)


async def test_provider_skipped_by_quota_is_not_recorded(meter):
    quota = MonthlyQuota(0)
    chain = FallbackSearch([guarded("tavily", StaticProvider([OFCE]), quota), guarded("wikipedia", StaticProvider([IFRAP]))])
    await chain.search("q", 5)
    assert not any(k[4] == "tavily" for k in meter._pending)


# ---------- étiquettes posées par les services ----------
def service_with(llm):
    return FactCheckService(llm, Retriever(StaticProvider([OFCE, IFRAP]), max_results=5), TTLCache(3600, 100))


class MeteredFake(ScriptedLLM):
    """Comme un vrai adaptateur : signale ses appels au compteur."""

    async def complete(self, *a, **kw):
        out = await super().complete(*a, **kw)
        record_llm("fake", 10, 2)
        return out


async def test_chatbot_check_is_labelled_check_and_counts_one_action(meter):
    await service_with(MeteredFake(QUERIES, analysis())).check("Le SMIC a augmenté de 10 % en 2024.")
    assert one(meter, "llm", "fake", "check").calls == 2
    assert meter._pending[(D1, "beta", "check", "action", "-")].calls == 1


async def test_cache_hit_counts_an_action_without_cost(meter):
    svc = service_with(MeteredFake(QUERIES, analysis()))
    await svc.check("Le SMIC a augmenté de 10 % en 2024.")
    await svc.check("Le SMIC a augmenté de 10 % en 2024.")
    assert meter._pending[(D1, "beta", "check", "action", "-")].calls == 2
    assert one(meter, "llm", "fake", "check").calls == 2  # pas d'appel de plus : c'est ce qui fait baisser le coût moyen


async def test_room_message_is_labelled_room_check_not_check(meter):
    checker = FactCheckMessageChecker(service_with(MeteredFake(QUERIES, analysis())))
    await checker.check("Le SMIC a augmenté de 10 % en 2024.")
    assert one(meter, "llm", "fake", "room_check").calls == 2
    assert not any(k[2] == "check" for k in meter._pending)
    assert meter._pending[(D1, "beta", "room_check", "action", "-")].calls == 1


# ---------- configuration ----------
def test_profile_defaults_to_beta_and_rejects_unknown_values():
    assert Settings(_env_file=None).profile == "beta"
    assert Settings(_env_file=None, profile="v1").profile == "v1"
    with pytest.raises(ValueError):
        Settings(_env_file=None, profile="prod")


def test_admin_endpoint_is_off_by_default_and_token_must_be_long():
    assert Settings(_env_file=None).admin_token.get_secret_value() == ""
    with pytest.raises(ValueError, match="32"):
        Settings(_env_file=None, admin_token="court")
    Settings(_env_file=None, admin_token="a" * 32)


def test_prices_parse_and_validate():
    assert parse_prices("") == {"llm": {}, "search": {}}
    ok = parse_prices('{"llm": {"m": [0.15, 0.6]}, "search": {"tavily": 0.008}}')
    assert ok == {"llm": {"m": [0.15, 0.6]}, "search": {"tavily": [0.008]}}
    for bad in ["pas du json", "[]", '{"autre": {}}', '{"llm": {"m": [1]}}', '{"llm": {"m": [-1, 1]}}',
                '{"llm": {"m": ["1", 1]}}', '{"llm": {"m": [true, 1]}}', '{"search": {"t": -0.1}}', '{"llm": {"m": [NaN, 1]}}',
                '{"llm": {"m": [Infinity, 1]}}']:
        with pytest.raises(ValueError):
            parse_prices(bad)


def test_bad_prices_stop_the_application_at_startup():
    with pytest.raises(ValueError):
        Settings(_env_file=None, cost_prices="{")


# ---------- rapport ----------
def row(op, kind, name, day=D1, **kw):
    base = {"day": day, "operation": op, "kind": kind, "name": name, "calls": 0, "errors": 0, "prompt_tokens": 0, "completion_tokens": 0, "credits": 0}
    return {**base, **kw}


PRICES = {"llm": {"m": [0.5, 2.0]}, "search": {"tavily": [0.01]}}


def test_report_computes_cost_per_action():
    data = [
        row("check", "action", "-", calls=4),
        row("check", "llm", "m", calls=8, prompt_tokens=2_000_000, completion_tokens=500_000),
        row("check", "search", "tavily", calls=3, credits=3),
        row("check", "search", "wikipedia", calls=2),
    ]
    r = build_report(data, PRICES, D1, D1)
    check = r["operations"]["check"]
    assert check["cost_eur"] == pytest.approx(0.5 * 2 + 2.0 * 0.5 + 3 * 0.01)  # 2.03
    assert check["cost_per_action_eur"] == pytest.approx(2.03 / 4)
    assert (check["actions"], check["llm_calls"], check["search_credits"], check["search_calls"]) == (4, 8, 3, 5)
    assert r["total_cost_eur"] == pytest.approx(2.03) and r["unpriced"] == []


def test_a_search_provider_that_consumed_credits_without_a_price_is_reported():
    r = build_report([row("check", "search", "tavily", calls=1, credits=3)], {"llm": {}, "search": {}}, D1, D1)
    assert r["total_cost_eur"] == 0 and r["unpriced"] == ["search:tavily"]


def test_unpriced_models_cost_zero_but_are_reported_not_guessed():
    r = build_report([row("check", "action", "-", calls=1), row("check", "llm", "inconnu", calls=1, prompt_tokens=10**6)], PRICES, D1, D1)
    assert r["total_cost_eur"] == 0 and r["unpriced"] == ["llm:inconnu"]


def test_cost_per_action_is_none_without_actions_and_free_engines_need_no_price():
    r = build_report([row("moderation", "llm", "m", calls=1, prompt_tokens=100), row("check", "search", "wikipedia", calls=2)], PRICES, D1, D1)
    assert r["operations"]["moderation"]["cost_per_action_eur"] is None
    assert r["unpriced"] == []


def test_report_groups_by_day_and_sorts():
    data = [row("check", "llm", "m", day=D2, calls=1, prompt_tokens=1_000_000), row("check", "llm", "m", day=D1, calls=1, completion_tokens=1_000_000)]
    r = build_report(data, PRICES, D1, D2)
    assert r["per_day_eur"] == {"2026-11-13": 2.0, "2026-11-14": 0.5}


# ---------- base réelle ----------
@db_only
async def test_flush_is_additive_across_calls_and_instances(fresh_db):
    m1, m2 = UsageMeter("beta", clock=Day()), UsageMeter("beta", clock=Day())
    for m in (m1, m2):
        metering.set_meter(m)
        with operation("check"):
            record_llm("m", 100, 10)
    metering.set_meter(None)
    await CostRecorder(fresh_db, m1).flush()
    await CostRecorder(fresh_db, m2).flush()
    async with fresh_db.session() as s:
        got = (await s.execute(select(cost_usage).where(cost_usage.c.kind == "llm"))).mappings().one()
    assert (got["calls"], got["prompt_tokens"], got["completion_tokens"], got["profile"]) == (2, 200, 20, "beta")


@db_only
async def test_concurrent_flushes_lose_nothing(fresh_db):
    m = UsageMeter("beta", clock=Day())
    metering.set_meter(m)
    rec = CostRecorder(fresh_db, m)
    try:
        async def burst(i):
            for _ in range(20):
                record_llm("m", 1, 1)
                await asyncio.sleep(0)
            await rec.flush()

        await asyncio.gather(*(burst(i) for i in range(5)))
    finally:
        metering.set_meter(None)
    await rec.flush()
    async with fresh_db.session() as s:
        total = (await s.execute(text("SELECT sum(calls), sum(prompt_tokens) FROM cost_usage"))).one()
    assert tuple(total) == (100, 100)


@db_only
async def test_empty_flush_writes_nothing_and_failed_flush_keeps_the_counters(fresh_db):
    m = UsageMeter("beta", clock=Day())
    rec = CostRecorder(fresh_db, m)
    assert await rec.flush() == 0
    metering.set_meter(m)
    record_llm("m", 5, 1)
    metering.set_meter(None)
    async with fresh_db.engine.begin() as conn:
        await conn.execute(text("ALTER TABLE cost_usage RENAME TO cost_usage_off"))
    assert await rec.flush() == 0  # écriture impossible : ni exception ni perte
    assert one(m, "llm", "m").prompt_tokens == 5
    async with fresh_db.engine.begin() as conn:
        await conn.execute(text("ALTER TABLE cost_usage_off RENAME TO cost_usage"))
    assert await rec.flush() == 1
    async with fresh_db.session() as s:
        assert (await s.execute(text("SELECT prompt_tokens FROM cost_usage"))).scalar_one() == 5


@db_only
async def test_report_window_is_clamped_for_direct_callers(fresh_db):
    rec = CostRecorder(fresh_db, UsageMeter("beta", clock=Day()))
    today = lambda: D1  # noqa: E731
    assert (await rec.report(0, parse_prices(""), today=today))["from"] == "2026-11-13"  # au moins 1 jour
    assert (await rec.report(10_000, parse_prices(""), today=today))["from"] == "2026-08-16"  # au plus 90 jours


@db_only
async def test_an_empty_flush_does_not_touch_the_database_or_log_a_warning(fresh_db, caplog):
    rec = CostRecorder(fresh_db, UsageMeter("beta", clock=Day()))
    async with fresh_db.engine.begin() as conn:
        await conn.execute(text("ALTER TABLE cost_usage RENAME TO cost_usage_off"))  # une écriture échouerait
    with caplog.at_level("WARNING", logger="facts.costs"):
        assert await rec.flush() == 0
    assert caplog.records == []
    async with fresh_db.engine.begin() as conn:
        await conn.execute(text("ALTER TABLE cost_usage_off RENAME TO cost_usage"))


@db_only
async def test_stored_rows_contain_no_personal_or_content_columns(fresh_db):
    async with fresh_db.engine.connect() as conn:
        cols = {r[0] for r in (await conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='cost_usage'"))).all()}
    assert cols == {"day", "profile", "operation", "kind", "name", "calls", "errors", "prompt_tokens", "completion_tokens", "credits"}


@db_only
async def test_report_reads_back_through_the_recorder(fresh_db):
    m = UsageMeter("beta", clock=Day())
    metering.set_meter(m)
    with operation("check"):
        record_llm("m", 1_000_000, 0)
    metering.set_meter(None)
    rec = CostRecorder(fresh_db, m)
    await rec.flush()
    out = await rec.report(7, {"llm": {"m": [0.5, 1.0]}, "search": {}}, today=lambda: D1)
    assert out["operations"]["check"]["cost_eur"] == 0.5 and out["from"] == "2026-11-07" and out["to"] == "2026-11-13"
    old = await rec.report(7, {"llm": {}, "search": {}}, today=lambda: date(2026, 12, 25))  # hors fenêtre
    assert old["operations"] == {}


TOKEN = "t" * 40
PRICED = '{"llm": {"m": [1.0, 1.0]}, "search": {}}'


def admin_client(**kw):
    settings = Settings(
        _env_file=None, database_url=URL, llm_api_key="ci-dummy", search_providers="wikipedia", read_rate_limit_requests=1000,
        admin_token=TOKEN, cost_prices=PRICED, **kw,
    )
    return TestClient(create_app(settings))


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


@db_only
def test_admin_endpoint_is_invisible_without_a_configured_token(fresh_db):
    settings = Settings(_env_file=None, database_url=URL, llm_api_key="ci-dummy", search_providers="wikipedia")
    with TestClient(create_app(settings)) as c:
        for headers in ({}, bearer(TOKEN), bearer("")):
            r = c.get("/api/v1/admin/costs", headers=headers)
            assert r.status_code == 404 and r.json() == {"detail": "Not Found"}


def test_admin_endpoint_is_invisible_without_a_database():
    settings = Settings(_env_file=None, llm_api_key="ci-dummy", search_providers="wikipedia", admin_token=TOKEN)
    with TestClient(create_app(settings)) as c:
        assert c.get("/api/v1/admin/costs", headers=bearer(TOKEN)).status_code == 404


@db_only
@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": ""}, {"Authorization": "Bearer "}, {"Authorization": "Bearer wrong"}, {"Authorization": TOKEN},
     {"Authorization": f"Basic {TOKEN}"}, {"Authorization": f"Bearer {TOKEN}x"}, {"Authorization": f"Bearer {TOKEN[:-1]}"},
     {"Authorization": f"Bearer {TOKEN.upper()}"}, {"Authorization": f"Bearex {TOKEN}"}],
)
def test_admin_endpoint_refuses_anything_but_the_exact_token(fresh_db, headers):
    with admin_client() as c:
        r = c.get("/api/v1/admin/costs", headers=headers)
    assert r.status_code == 401 and TOKEN not in r.text and "costs" not in r.text


@db_only
def test_admin_endpoint_returns_costs_and_flushes_pending_counters(fresh_db):
    with admin_client() as c:
        meter = metering.get_meter()
        assert meter is not None and c.app.state.settings.profile == "beta"
        with operation("check"):
            record_llm("m", 2_000_000, 0)
        r = c.get("/api/v1/admin/costs?days=3", headers=bearer(TOKEN))
    assert r.status_code == 200
    body = r.json()
    assert body["profile"] == "beta" and body["operations"]["check"]["cost_eur"] == 2.0 and body["total_cost_eur"] == 2.0
    assert TOKEN not in r.text and "database" not in r.text.lower()


@db_only
@pytest.mark.parametrize("days", ["0", "91", "-1", "abc"])
def test_admin_days_parameter_is_bounded(fresh_db, days):
    with admin_client() as c:
        assert c.get(f"/api/v1/admin/costs?days={days}", headers=bearer(TOKEN)).status_code == 422


@db_only
def test_admin_token_guessing_is_rate_limited(fresh_db):
    with admin_client(login_attempts_per_window=3) as c:
        codes = [c.get("/api/v1/admin/costs", headers=bearer(f"bad{i}")).status_code for i in range(5)]
        good = c.get("/api/v1/admin/costs", headers=bearer(TOKEN)).status_code
    assert codes[:3] == [401, 401, 401] and codes[3:] == [429, 429]
    assert good == 429  # même le bon jeton attend : la limite est posée avant la comparaison


@db_only
async def test_pending_counters_are_written_when_the_app_stops(fresh_db):
    with admin_client() as c:
        with operation("check"):
            record_llm("m", 7, 1)
        assert c.app.state.costs is not None
    async with fresh_db.session() as s:
        n = (await s.execute(text("SELECT sum(prompt_tokens) FROM cost_usage WHERE kind='llm'"))).scalar_one()
    assert n == 7
    assert metering.get_meter() is None  # ne fuit pas vers les tests suivants


@db_only
def test_meter_is_inactive_without_a_database():
    settings = Settings(_env_file=None, llm_api_key="ci-dummy", search_providers="wikipedia")
    with TestClient(create_app(settings)):
        assert metering.get_meter() is None
