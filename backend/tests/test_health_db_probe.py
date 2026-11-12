"""/health ne doit JAMAIS toucher la base : le pinger l'appelle toutes les 10 min et empêcherait Neon de se mettre en veille."""

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


class CountingDB:
    def __init__(self, fail=False):
        self.pings, self.fail = 0, fail

    async def ping(self):
        self.pings += 1
        if self.fail:
            raise ConnectionError("postgresql://u:topsecret@h/db")


def make(db, **kw):
    return TestClient(create_app(Settings(_env_file=None, **kw), db=db))


def test_plain_health_never_pings_the_database():
    db = CountingDB()
    client = make(db)
    for _ in range(3):
        assert client.get("/health").json()["status"] == "ok"
    assert db.pings == 0


def test_health_db_pings_once_per_call():
    db = CountingDB()
    client = make(db, read_rate_limit_requests=100)
    assert client.get("/health/db").json() == {"db": "ok"}
    assert db.pings == 1


def test_health_db_hides_the_error_detail():
    client = make(CountingDB(fail=True))
    r = client.get("/health/db")
    assert r.status_code == 503 and r.json() == {"db": "down"} and "topsecret" not in r.text


def test_health_db_is_rate_limited_because_each_call_wakes_the_database():
    db = CountingDB()
    client = make(db, read_rate_limit_requests=2)
    codes = [client.get("/health/db").status_code for _ in range(4)]
    assert codes == [200, 200, 429, 429] and db.pings == 2


def test_health_db_is_hidden_from_the_api_schema():
    client = make(CountingDB())
    assert "/health/db" not in client.get("/openapi.json").text
