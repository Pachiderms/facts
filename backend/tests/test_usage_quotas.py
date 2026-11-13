"""Quotas par plan (anonyme / compte gratuit) et endpoint d'usage. Fonctionnel + sécurité."""

import uuid
from datetime import datetime, timezone

from app.services.accounts import User
from tests.test_api_check import ASSERTION, URL
from tests.test_daily_limits import check_client

TOKEN_A, TOKEN_B = "A" * 43, "B" * 43


class Accounts:
    """Faux service de comptes : deux sessions valides pour deux comptes."""

    def __init__(self, broken=False):
        now = datetime(2026, 11, 13, tzinfo=timezone.utc)
        self.users = {TOKEN_A: User(uuid.uuid4(), "a@example.com", now), TOKEN_B: User(uuid.uuid4(), "b@example.com", now)}
        self.broken = broken

    async def authenticate(self, token):
        if self.broken:
            raise RuntimeError("base indisponible")
        return self.users.get(token)


def client_with_accounts(broken=False, **kw):
    c = check_client(**kw)
    c.app.state.accounts = Accounts(broken)
    return c


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def post(c, token=None):
    return c.post(URL, json={"assertion": ASSERTION}, headers=bearer(token) if token else {})


def test_account_gets_a_higher_quota_than_anonymous():
    c = client_with_accounts(daily_check_limit=2, account_daily_check_limit=4)
    assert [post(c).status_code for _ in range(3)] == [200, 200, 429]
    assert [post(c, TOKEN_A).status_code for _ in range(5)] == [200, 200, 200, 200, 429]  # l'IP backstop (8) n'intervient pas


def test_account_quota_is_per_account_not_shared():
    c = client_with_accounts(daily_check_limit=5, account_daily_check_limit=1)
    assert post(c, TOKEN_A).status_code == 200 and post(c, TOKEN_A).status_code == 429
    assert post(c, TOKEN_B).status_code == 200  # autre compte : son propre quota


def test_ip_backstop_stops_account_multiplication_from_one_connection():
    c = client_with_accounts(daily_check_limit=1, account_daily_check_limit=100)  # filet IP = 4
    codes = [post(c, TOKEN_A if i % 2 else TOKEN_B).status_code for i in range(6)]
    assert codes == [200, 200, 200, 200, 429, 429]
    assert int(post(c, TOKEN_A).headers["Retry-After"]) > 0


def test_invalid_or_broken_session_counts_as_anonymous():
    c = client_with_accounts(daily_check_limit=1, account_daily_check_limit=50)
    assert post(c, "X" * 43).status_code == 200 and post(c, "X" * 43).status_code == 429
    broken = client_with_accounts(broken=True, daily_check_limit=1, account_daily_check_limit=50)
    assert post(broken, TOKEN_A).status_code == 200 and post(broken, TOKEN_A).status_code == 429


def test_malformed_authorization_headers_are_anonymous():
    c = client_with_accounts(daily_check_limit=1)
    for header in (f"Basic {TOKEN_A}", "Bearer", "Bearer   ", TOKEN_A):
        c2 = client_with_accounts(daily_check_limit=1)
        r = c2.post(URL, json={"assertion": ASSERTION}, headers={"Authorization": header})
        assert r.status_code == 200
        assert c2.post(URL, json={"assertion": ASSERTION}, headers={"Authorization": header}).status_code == 429
    assert c is not None


def test_invalid_body_does_not_consume_the_account_quota():
    c = client_with_accounts(account_daily_check_limit=1)
    assert c.post(URL, json={"assertion": ""}, headers=bearer(TOKEN_A)).status_code == 422
    assert post(c, TOKEN_A).status_code == 200


# ---------- /usage ----------
def test_usage_for_anonymous_and_account():
    c = client_with_accounts(daily_check_limit=3, account_daily_check_limit=5)
    assert c.get("/api/v1/usage").json() == {"plan": "anonymous", "checks": {"used": 0, "limit": 3, "remaining": 3}, "degraded": False}
    post(c)
    post(c, TOKEN_A)
    post(c, TOKEN_A)
    assert c.get("/api/v1/usage").json()["checks"] == {"used": 1, "limit": 3, "remaining": 2}
    mine = c.get("/api/v1/usage", headers=bearer(TOKEN_A)).json()
    assert mine["plan"] == "free" and mine["checks"] == {"used": 2, "limit": 5, "remaining": 3}
    assert c.get("/api/v1/usage", headers=bearer(TOKEN_B)).json()["checks"]["used"] == 0


def test_usage_is_read_only_and_never_exposes_identifiers():
    c = client_with_accounts(daily_check_limit=3)
    for _ in range(5):
        body = c.get("/api/v1/usage", headers=bearer(TOKEN_A)).json()
    assert body["checks"]["used"] == 0  # lire ne consomme rien
    raw = c.get("/api/v1/usage", headers=bearer(TOKEN_A)).text
    assert "a@example.com" not in raw and TOKEN_A not in raw
    assert c.get("/api/v1/usage").headers["cache-control"] == "no-store"


def test_usage_reports_degraded_mode():
    class Degraded:
        degraded = True

    c = client_with_accounts()
    c.app.state.llm = Degraded()
    assert c.get("/api/v1/usage").json()["degraded"] is True


def test_used_forgets_hits_older_than_the_window():
    from app.core.security import SlidingWindowRateLimiter

    now = [0.0]
    limiter = SlidingWindowRateLimiter(3, 100, clock=lambda: now[0])
    limiter.allow("k")
    limiter.allow("k")
    assert limiter.used("k") == 2 and limiter.used("autre") == 0
    now[0] = 101
    assert limiter.used("k") == 0
