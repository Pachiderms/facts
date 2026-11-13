"""Abonnement Pro : signature des webhooks, idempotence, accès, interrupteur de paiement. Fonctionnel + sécurité."""

import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.adapters import lemonsqueezy as ls
from app.core.config import Settings
from app.core.quotas import MemoryQuotas
from app.services.billing import is_entitled
from app.services.quota_policy import QuotaPolicy
from tests.test_accounts_api import auth, fresh_db, login, make_client, query  # noqa: F401  (fresh_db : fixture)

URL = os.environ.get("FACTS_TEST_DATABASE_URL", "")
SECRET = "s3cret-s3cret-s3cret"
CHECKOUT = "https://boutique.lemonsqueezy.com/checkout/buy/abc"
db_only = pytest.mark.skipif(not URL, reason="FACTS_TEST_DATABASE_URL non défini")
UID = uuid4()


def iso(delta_days=0.0, base=None):
    return ((base or datetime.now(timezone.utc)) + timedelta(days=delta_days)).isoformat()


def payload(user_id=UID, *, event="subscription_created", status="active", sub_id="777", ends=None, renews=None, updated=None, portal="https://pay.example/portal/x", **extra):
    return {
        "meta": {"event_name": event, "custom_data": {"user_id": str(user_id)}},
        "data": {
            "type": "subscriptions",
            "id": sub_id,
            "attributes": {
                "status": status,
                "customer_id": 42,
                "renews_at": renews if renews is not None else iso(30),
                "ends_at": ends,
                "updated_at": updated or iso(),
                "urls": {"customer_portal": portal},
                **extra,
            },
        },
    }


def sign(body: bytes, secret=SECRET) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def send(client, data, *, secret=SECRET, signature=None, raw=None):
    body = raw if raw is not None else json.dumps(data).encode()
    headers = {"content-type": "application/json"}
    if signature is not False:
        headers["x-signature"] = sign(body, secret) if signature is None else signature
    return client.post("/api/v1/billing/webhook", content=body, headers=headers)


def paying_client(**kw):
    return make_client(payments_enabled=True, lemonsqueezy_webhook_secret=SECRET, lemonsqueezy_checkout_url=CHECKOUT, pro_price_label="5 € / mois", **kw)


# ======================= signature (pur) =======================
def test_signature_accepts_only_the_exact_hmac_of_the_raw_body():
    body = b'{"a": 1}'
    good = sign(body)
    assert ls.verify_signature(body, good, SECRET)
    assert ls.verify_signature(body, good.upper(), SECRET)  # l'hexadécimal n'est pas sensible à la casse
    assert not ls.verify_signature(body + b" ", good, SECRET)  # corps modifié d'un octet
    assert not ls.verify_signature(body, sign(body, "autre-secret-autre-secret"), SECRET)
    assert not ls.verify_signature(body, "", SECRET) and not ls.verify_signature(body, None, SECRET)
    assert not ls.verify_signature(body, good, "")  # secret vide : jamais valide, même avec le HMAC « vide » correspondant
    assert not ls.verify_signature(body, sign(body, ""), "")


# ======================= lecture d'un évènement (pur) =======================
def test_parse_valid_event():
    e = ls.parse_subscription_event(payload(ends=iso(5), renews=iso(30)))
    assert e.user_id == UID and e.subscription_id == "777" and e.customer_id == "42" and e.status == "active"
    assert e.portal_url == "https://pay.example/portal/x"
    assert e.period_end > datetime.now(timezone.utc) + timedelta(days=4)  # ends_at (5 j) et non renews_at (30 j)
    assert e.period_end < datetime.now(timezone.utc) + timedelta(days=6)
    renews_only = ls.parse_subscription_event(payload(renews="2030-01-01T00:00:00.000000Z"))
    assert renews_only.period_end == datetime(2030, 1, 1, tzinfo=timezone.utc)  # « Z » accepté
    ends_wins = ls.parse_subscription_event(payload(ends="2029-06-01T00:00:00Z", renews="2030-01-01T00:00:00Z"))
    assert ends_wins.period_end == datetime(2029, 6, 1, tzinfo=timezone.utc)  # la fin de période l'emporte


def test_parse_naive_timestamps_are_utc():
    e = ls.parse_subscription_event(payload(updated="2030-01-01T10:00:00", renews="2030-02-01T00:00:00"))
    assert e.event_at.tzinfo is not None and e.event_at.utcoffset() == timedelta(0)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p["meta"].update(event_name="order_created"),
        lambda p: p["meta"].update(event_name="subscription_payment_success"),  # facture : ne change pas le statut
        lambda p: p["meta"].update(event_name=None),
        lambda p: p["meta"].update(custom_data={}),
        lambda p: p["meta"].update(custom_data={"user_id": "pas-un-uuid"}),
        lambda p: p["meta"].update(custom_data=None),
        lambda p: p["data"].update(type="orders"),
        lambda p: p["data"]["attributes"].update(status="bidon"),
        lambda p: p["data"]["attributes"].update(status=None),
        lambda p: p["data"].update(id=""),
        lambda p: p["data"].update(id="9" * 65),
        lambda p: p["data"].update(id=None),
        lambda p: p["data"]["attributes"].pop("updated_at"),
        lambda p: p["data"]["attributes"].update(updated_at="hier"),
        lambda p: p["data"].update(attributes="x"),
    ],
)
def test_parse_rejects_malformed_or_unrelated_events(mutate):
    p = payload()
    mutate(p)
    assert ls.parse_subscription_event(p) is None


@pytest.mark.parametrize("junk", [None, [], "texte", 3, {}, {"meta": 1, "data": 2}])
def test_parse_rejects_non_objects(junk):
    assert ls.parse_subscription_event(junk) is None


def test_portal_url_must_be_https_and_bounded():
    assert ls.parse_subscription_event(payload(portal="http://x.example/p")).portal_url is None
    assert ls.parse_subscription_event(payload(portal="javascript:alert(1)")).portal_url is None
    assert ls.parse_subscription_event(payload(portal="https://x.example/" + "a" * 600)).portal_url is None


def test_checkout_link_encodes_the_address_and_carries_the_account():
    link = ls.checkout_link(CHECKOUT, UID, "a+b&c=d@exemple.fr")
    assert link.startswith(CHECKOUT + "?") and "a%2Bb%26c%3Dd%40exemple.fr" in link and f"checkout%5Bcustom%5D%5Buser_id%5D={UID}" in link
    assert "&" not in link.split("?", 1)[1].replace("&checkout", "")  # aucune injection de paramètre via l'adresse
    assert ls.checkout_link(CHECKOUT + "?media=0", UID, "a@b.fr").count("?") == 1  # lien déjà paramétré : « & »


# ======================= droit d'accès (pur) =======================
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
GRACE = timedelta(days=3)


@pytest.mark.parametrize(
    "status,end,expected",
    [
        ("active", NOW + timedelta(days=10), True),
        ("on_trial", NOW + timedelta(days=1), True),
        ("active", None, True),
        ("active", NOW - timedelta(days=2), True),  # renouvellement en retard : tolérance
        ("active", NOW - timedelta(days=4), False),  # tolérance dépassée
        ("past_due", NOW - timedelta(days=1), True),
        ("past_due", NOW - timedelta(days=4), False),
        ("cancelled", NOW + timedelta(days=5), True),  # résilié mais payé jusqu'à la fin
        ("cancelled", NOW - timedelta(seconds=1), False),  # pas de tolérance après résiliation
        ("cancelled", None, False),
        ("expired", NOW + timedelta(days=5), False),
        ("paused", NOW + timedelta(days=5), False),
        ("unpaid", NOW + timedelta(days=5), False),
        ("inconnu", NOW + timedelta(days=5), False),
    ],
)
def test_entitlement_table(status, end, expected):
    assert is_entitled(status, end, NOW, GRACE) is expected


# ======================= configuration =======================
def test_enabling_payments_needs_a_complete_setup():
    base = dict(_env_file=None, payments_enabled=True, database_url="postgresql://u:p@h/db", google_client_id="x.apps.googleusercontent.com")
    ok = Settings(**base, lemonsqueezy_webhook_secret=SECRET, lemonsqueezy_checkout_url=CHECKOUT)
    assert ok.payments_enabled
    with pytest.raises(ValidationError):
        Settings(**base, lemonsqueezy_webhook_secret="court", lemonsqueezy_checkout_url=CHECKOUT)
    with pytest.raises(ValidationError):
        Settings(**base, lemonsqueezy_webhook_secret=SECRET, lemonsqueezy_checkout_url="http://non-chiffre.example")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, payments_enabled=True, lemonsqueezy_webhook_secret=SECRET, lemonsqueezy_checkout_url=CHECKOUT)  # sans comptes


def test_payments_are_off_by_default():
    assert Settings(_env_file=None).payments_enabled is False


# ======================= quotas par plan (mémoire) =======================
async def test_pro_plan_has_its_own_limits_and_others_are_unchanged():
    s = Settings(_env_file=None, daily_check_limit=3, account_daily_check_limit=5, pro_daily_check_limit=9, debate_daily_checks=2, account_debate_daily_checks=4, pro_debate_daily_checks=7)
    policy = QuotaPolicy(MemoryQuotas(), s, "sel")
    anon, free, pro = policy.anonymous("1.1.1.1"), policy.account("u:a", "1.1.1.1"), policy.account("u:b", "1.1.1.1", "pro")
    assert (anon.plan, free.plan, pro.plan) == ("anonymous", "free", "pro")
    assert [policy.check_limit(w) for w in (anon, free, pro)] == [3, 5, 9]
    assert [policy.debate_limit(w) for w in (anon, free, pro)] == [2, 4, 7]
    assert policy.account("u:c", "1.1.1.1", "n'importe quoi").plan == "free"  # plan inconnu : jamais Pro
    used = 0
    while await policy.consume_check(pro):
        used += 1
        assert used < 50
    assert used == 9  # la limite Pro s'applique vraiment à la consommation
    used = 0
    while await policy.consume_debate(pro):
        used += 1
        assert used < 50
    assert used == 7


# ======================= API : paiement désactivé =======================
@db_only
def test_payments_disabled_by_default_everything_refuses(fresh_db):
    with make_client() as client:
        token = login(client).json()["session_token"]
        state = client.get("/api/v1/billing", headers=auth(token)).json()
        assert state["enabled"] is False and state["plan"] == "free" and state["price_label"] == ""
        assert client.post("/api/v1/billing/checkout", headers=auth(token)).status_code == 503
        body = json.dumps(payload()).encode()  # même avec une signature valide (secret vide : impossible, mais testons aussi un secret posé)
        assert client.post("/api/v1/billing/webhook", content=body, headers={"x-signature": sign(body)}).status_code == 503
    assert query("SELECT count(*) FROM subscriptions")[0][0] == 0


@db_only
def test_disabled_switch_wins_even_with_a_valid_secret(fresh_db):
    # Secret configuré mais interrupteur éteint : le webhook ne traite rien.
    with make_client(lemonsqueezy_webhook_secret=SECRET) as client:
        r = send(client, payload())
        assert r.status_code == 503
    assert query("SELECT count(*) FROM billing_events")[0][0] == 0


# ======================= API : paiement activé =======================
@db_only
def test_state_without_session_shows_no_account_detail(fresh_db):
    with paying_client() as client:
        s = client.get("/api/v1/billing").json()
        assert s == {"enabled": True, "price_label": "5 € / mois", "plan": "free", "status": None, "current_period_end": None, "portal_url": None}
        assert client.get("/api/v1/billing", headers=auth("x" * 43)).json()["plan"] == "free"  # session invalide


@db_only
def test_checkout_needs_a_session_and_returns_a_personal_link(fresh_db):
    with paying_client() as client:
        assert client.post("/api/v1/billing/checkout").status_code == 401
        assert client.post("/api/v1/billing/checkout", headers=auth("y" * 43)).status_code == 401
        log = login(client, email="alice+pro@example.com").json()
        r = client.post("/api/v1/billing/checkout", headers=auth(log["session_token"]))
        assert r.status_code == 200
        url = r.json()["url"]
        assert url.startswith(CHECKOUT) and log["user"]["id"] in url and "alice%2Bpro%40example.com" in url


@db_only
def test_webhook_rejects_missing_or_wrong_signature_and_stores_nothing(fresh_db):
    with paying_client() as client:
        log = login(client).json()
        uid = UUID(log["user"]["id"])
        data = payload(uid)
        assert send(client, data, signature=False).status_code == 401
        assert send(client, data, signature="0" * 64).status_code == 401
        assert send(client, data, secret="mauvais-secret-mauvais").status_code == 401
        assert send(client, data, signature="").status_code == 401
        # corps modifié après signature (ex. changer le compte bénéficiaire) : refusé
        good_body = json.dumps(data).encode()
        forged = json.dumps(payload(uuid4())).encode()
        assert client.post("/api/v1/billing/webhook", content=forged, headers={"x-signature": sign(good_body)}).status_code == 401
        assert client.get("/api/v1/billing", headers=auth(log["session_token"])).json()["plan"] == "free"
    assert query("SELECT count(*) FROM subscriptions")[0][0] == 0 and query("SELECT count(*) FROM billing_events")[0][0] == 0


@db_only
def test_webhook_activates_pro_and_limits_follow(fresh_db):
    with paying_client(account_daily_check_limit=60, pro_daily_check_limit=250) as client:
        log = login(client).json()
        h = auth(log["session_token"])
        assert client.get("/api/v1/usage", headers=h).json()["checks"]["limit"] == 60
        r = send(client, payload(UUID(log["user"]["id"])))
        assert r.status_code == 200 and r.json() == {"result": "applied"}
        s = client.get("/api/v1/billing", headers=h).json()
        assert s["plan"] == "pro" and s["status"] == "active" and s["portal_url"] == "https://pay.example/portal/x" and s["current_period_end"]
        u = client.get("/api/v1/usage", headers=h).json()
        assert u["plan"] == "pro" and u["checks"]["limit"] == 250  # le cache de plan est invalidé par le webhook
        assert client.post("/api/v1/billing/checkout", headers=h).status_code == 409  # déjà abonné


@db_only
def test_pro_only_applies_to_the_paying_account(fresh_db):
    with paying_client() as client:
        a = login(client, sub="1", email="a@example.com").json()
        b = login(client, sub="2", email="b@example.com").json()
        send(client, payload(UUID(a["user"]["id"])))
        assert client.get("/api/v1/billing", headers=auth(a["session_token"])).json()["plan"] == "pro"
        assert client.get("/api/v1/billing", headers=auth(b["session_token"])).json()["plan"] == "free"
        assert client.get("/api/v1/usage", headers=auth(b["session_token"])).json()["plan"] == "free"
        assert client.get("/api/v1/usage").json()["plan"] == "anonymous"


@db_only
def test_replayed_delivery_is_a_no_op(fresh_db):
    with paying_client() as client:
        uid = UUID(login(client).json()["user"]["id"])
        body = json.dumps(payload(uid)).encode()
        assert send(client, None, raw=body).json() == {"result": "applied"}
        assert send(client, None, raw=body).json() == {"result": "duplicate"}
        assert send(client, None, raw=body).json() == {"result": "duplicate"}
    assert query("SELECT count(*) FROM billing_events")[0][0] == 1


@db_only
def test_stale_event_cannot_undo_a_newer_state(fresh_db):
    with paying_client() as client:
        log = login(client).json()
        uid, h = UUID(log["user"]["id"]), auth(log["session_token"])
        now = datetime.now(timezone.utc)
        send(client, payload(uid, status="expired", ends=iso(-1), updated=iso(0, now)))
        assert client.get("/api/v1/billing", headers=h).json()["plan"] == "free"
        # un évènement « active » PLUS ANCIEN, livré en retard, ne ressuscite pas l'abonnement
        late = send(client, payload(uid, status="active", updated=iso(-2, now)))
        assert late.json() == {"result": "stale"}
        assert client.get("/api/v1/billing", headers=h).json()["plan"] == "free"
        # un évènement plus récent est appliqué
        assert send(client, payload(uid, status="active", updated=iso(1, now))).json() == {"result": "applied"}
        assert client.get("/api/v1/billing", headers=h).json()["plan"] == "pro"


@db_only
def test_cancelled_keeps_pro_until_the_end_of_the_paid_period_then_free(fresh_db):
    with paying_client() as client:
        log = login(client).json()
        uid, h = UUID(log["user"]["id"]), auth(log["session_token"])
        send(client, payload(uid, event="subscription_cancelled", status="cancelled", ends=iso(10)))
        s = client.get("/api/v1/billing", headers=h).json()
        assert s["plan"] == "pro" and s["status"] == "cancelled"
        send(client, payload(uid, event="subscription_expired", status="expired", ends=iso(-1), updated=iso(1)))
        assert client.get("/api/v1/billing", headers=h).json()["plan"] == "free"


@db_only
def test_unknown_account_is_acknowledged_but_nothing_is_stored(fresh_db):
    with paying_client() as client:
        r = send(client, payload(uuid4()))
        assert r.status_code == 200 and r.json() == {"result": "ignored"}  # 200 : le prestataire ne réessaie pas indéfiniment
    assert query("SELECT count(*) FROM subscriptions")[0][0] == 0 and query("SELECT count(*) FROM billing_events")[0][0] == 0


@db_only
def test_a_subscription_cannot_be_attached_to_two_accounts(fresh_db):
    with paying_client() as client:
        a = login(client, sub="1", email="a@example.com").json()
        b = login(client, sub="2", email="b@example.com").json()
        send(client, payload(UUID(a["user"]["id"]), sub_id="same"))
        r = send(client, payload(UUID(b["user"]["id"]), sub_id="same", updated=iso(1)))
        assert r.json() == {"result": "ignored"}
        assert client.get("/api/v1/billing", headers=auth(b["session_token"])).json()["plan"] == "free"
        assert client.get("/api/v1/billing", headers=auth(a["session_token"])).json()["plan"] == "pro"


@db_only
def test_unrelated_events_and_bad_payloads(fresh_db):
    with paying_client() as client:
        uid = UUID(login(client).json()["user"]["id"])
        other = payload(uid, event="order_created")
        assert send(client, other).json() == {"result": "ignored"}
        assert send(client, None, raw=b"pas du json").status_code == 400  # signé mais illisible
        assert send(client, None, raw=b"[1, 2]").json() == {"result": "ignored"}
    assert query("SELECT count(*) FROM subscriptions")[0][0] == 0


@db_only
def test_oversized_body_is_refused_before_anything_else(fresh_db):
    with paying_client() as client:
        big = b"x" * (ls.MAX_BODY_BYTES + 1)
        assert client.post("/api/v1/billing/webhook", content=big, headers={"x-signature": sign(big)}).status_code == 413
        # et sans en-tête Content-Length honnête (flux en morceaux)
        def chunks():
            yield b"y" * (ls.MAX_BODY_BYTES // 2 + 1)
            yield b"y" * (ls.MAX_BODY_BYTES // 2 + 1)

        assert client.post("/api/v1/billing/webhook", content=chunks(), headers={"x-signature": "0" * 64}).status_code == 413


@db_only
def test_no_secret_or_card_data_is_ever_stored_or_exported(fresh_db):
    with paying_client() as client:
        log = login(client).json()
        h = auth(log["session_token"])
        send(client, payload(UUID(log["user"]["id"]), card_brand="visa", card_last_four="4242"))
        export = client.get("/api/v1/auth/export", headers=h)
        assert export.status_code == 200
        data = export.json()
        assert data["subscription"]["status"] == "active" and data["subscription"]["provider"] == "lemonsqueezy"
        assert "portal" not in export.text and SECRET not in export.text and "4242" not in export.text
    dump = str(query("SELECT * FROM subscriptions")) + str(query("SELECT * FROM billing_events"))
    assert "4242" not in dump and SECRET not in dump


@db_only
def test_account_deletion_erases_the_subscription_row(fresh_db):
    with paying_client() as client:
        log = login(client).json()
        h = auth(log["session_token"])
        send(client, payload(UUID(log["user"]["id"]), event="subscription_cancelled", status="cancelled", ends=iso(10)))
        assert query("SELECT count(*) FROM subscriptions")[0][0] == 1
        assert client.post("/api/v1/auth/delete", json={"confirm": True}, headers=h).status_code in (200, 204)
    assert query("SELECT count(*) FROM subscriptions")[0][0] == 0


@db_only
def test_account_deletion_is_blocked_while_a_renewing_subscription_is_active(fresh_db):
    with paying_client() as client:
        log = login(client).json()
        uid, h = UUID(log["user"]["id"]), auth(log["session_token"])
        send(client, payload(uid))
        r = client.post("/api/v1/auth/delete", json={"confirm": True}, headers=h)
        assert r.status_code == 409 and "Résiliez" in r.json()["detail"]
        assert client.get("/api/v1/auth/me", headers=h).status_code == 200  # compte intact
        assert query("SELECT count(*) FROM subscriptions")[0][0] == 1
        # résilié (payé jusqu'à la fin de période) ou expiré : la suppression est possible
        send(client, payload(uid, event="subscription_cancelled", status="cancelled", ends=iso(10), updated=iso(1)))
        assert client.post("/api/v1/auth/delete", json={"confirm": True}, headers=h).status_code == 200
    assert query("SELECT count(*) FROM subscriptions")[0][0] == 0


@db_only
def test_plan_is_cached_but_refreshed_by_the_webhook_and_defaults_to_free_on_errors(fresh_db):
    with paying_client() as client:
        log = login(client).json()
        uid, h = UUID(log["user"]["id"]), auth(log["session_token"])
        billing = client.app.state.billing
        send(client, payload(uid))
        assert client.get("/api/v1/usage", headers=h).json()["plan"] == "pro"

        async def boom(_):
            raise RuntimeError("base indisponible")

        billing._cache.clear()
        billing.status = boom  # panne de lecture : jamais Pro « par défaut »
        assert client.get("/api/v1/usage", headers=h).json()["plan"] == "free"


@db_only
def test_migration_creates_the_billing_tables(fresh_db):
    names = {r[0] for r in query("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")}
    assert {"subscriptions", "billing_events"} <= names


# ======================= débat (WebSocket) : le plan Pro compte =======================
class _Accounts:
    def __init__(self, users):
        self.users = users

    async def authenticate(self, token):
        return self.users.get(token)


class _Billing:
    def __init__(self, pro_ids):
        self.pro_ids = pro_ids

    async def plan_of(self, user_id):
        return "pro" if user_id in self.pro_ids else "free"


def _debate_checked(c, session, n, messages):
    from tests.test_api_rooms import CLAIM, recv_until, send_message, token

    statuses = []
    with c.websocket_connect("/api/v1/rooms/room-1/ws") as ws:
        ws.send_json({"type": "hello", "token": token(n), "session": session})
        recv_until(ws, "snapshot")
        for i in range(messages):
            send_message(ws, CLAIM + f" ({i})")
            statuses.append(recv_until(ws, "message")["message"]["check"]["status"])
            if statuses[-1] == "pending":
                recv_until(ws, "check_result")
    return statuses


def test_websocket_debate_uses_the_pro_limit_for_a_pro_account_only():
    from app.services.accounts import User
    from tests.test_api_rooms import make_client

    now = datetime.now(timezone.utc)
    pro_user, free_user = User(uuid4(), "p@example.com", now), User(uuid4(), "f@example.com", now)
    sessions = {"P" * 43: pro_user, "F" * 43: free_user}
    with make_client(account_debate_daily_checks=1, pro_debate_daily_checks=3, debate_daily_checks=1) as c:
        c.app.state.accounts = _Accounts(sessions)
        c.app.state.billing = _Billing({pro_user.id})
        free = _debate_checked(c, "F" * 43, 1, 3)
        pro = _debate_checked(c, "P" * 43, 2, 4)
    assert free == ["pending", "unchecked", "unchecked"]  # 1 message vérifié (limite gratuite)
    assert pro == ["pending", "pending", "pending", "unchecked"]  # 3 messages vérifiés (limite Pro)


async def test_pro_debate_is_still_capped_by_the_shared_ip_backstop():
    s = Settings(_env_file=None, debate_daily_checks=1, pro_debate_daily_checks=100)  # filet IP = 1 x 4
    policy = QuotaPolicy(MemoryQuotas(), s, "sel")
    granted = [await policy.consume_debate(policy.account(f"pro-{i}", "81.1.1.1", "pro")) for i in range(8)]
    assert granted == [True] * 4 + [False] * 4  # des abonnés ne multiplient pas le budget depuis une seule connexion
    assert await policy.consume_debate(policy.account("pro-x", "82.2.2.2", "pro"))
