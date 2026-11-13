"""Base réelle (PostgreSQL) : migrations, transactions, requêtes paramétrées, sonde /health/db.

Exécutés si FACTS_TEST_DATABASE_URL est défini (en CI : service PostgreSQL ; en local : un Postgres jetable).
Sans cette variable ils sont ignorés, jamais « verts par défaut » : le job CI la définit toujours.
"""

import asyncio
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import insert, inspect, select, text

from app.core.config import Settings
from app.db.engine import Database
from app.db.schema import app_meta, metadata
from app.main import create_app

URL = os.environ.get("FACTS_TEST_DATABASE_URL", "")
BACKEND = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not URL, reason="FACTS_TEST_DATABASE_URL non défini")


def alembic_config(url: str = URL) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.attributes["url"] = url
    return cfg


async def migrate(action: str, rev: str, url: str = URL) -> None:
    # Alembic lance sa propre boucle asyncio : dans un thread, pour ne pas entrer en conflit avec celle de pytest.
    await asyncio.to_thread(getattr(command, action), alembic_config(url), rev)


async def wipe(db: Database) -> None:
    async with db.engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))


@pytest.fixture
async def db():
    database = Database(URL)
    await wipe(database)
    yield database
    await wipe(database)
    await database.aclose()


async def tables(db: Database) -> set[str]:
    async with db.engine.connect() as conn:
        return set(await conn.run_sync(lambda c: inspect(c).get_table_names()))


async def test_upgrade_creates_the_schema_and_downgrade_removes_it(db):
    assert await tables(db) == set()
    await migrate("upgrade", "head")
    assert await tables(db) == {"app_meta", "users", "sessions", "user_participants", "user_rooms", "usage_counters", "subscriptions", "billing_events", "cost_usage", "alembic_version"}
    async with db.engine.connect() as conn:
        pk = await conn.run_sync(lambda c: inspect(c).get_pk_constraint("app_meta"))
    assert pk["constrained_columns"] == ["key"]
    await migrate("downgrade", "base")
    assert await tables(db) == {"alembic_version"}


async def test_upgrade_twice_is_a_noop(db):
    await migrate("upgrade", "head")
    await migrate("upgrade", "head")  # un redémarrage de l'API relance les migrations : doit être sans effet
    assert "app_meta" in await tables(db)


async def test_migrations_match_the_declared_schema(db):
    """Un modèle modifié sans migration (ou l'inverse) fait échouer ce test."""
    await migrate("upgrade", "head")

    def diff(conn):
        return compare_metadata(MigrationContext.configure(conn), metadata)

    async with db.engine.connect() as conn:
        assert await conn.run_sync(diff) == []


async def test_session_commits_and_rolls_back(db):
    await migrate("upgrade", "head")
    async with db.session() as s:
        await s.execute(insert(app_meta).values(key="a", value="1"))
    with pytest.raises(RuntimeError):
        async with db.session() as s:
            await s.execute(insert(app_meta).values(key="b", value="2"))
            raise RuntimeError("échec au milieu de la transaction")
    async with db.session() as s:
        keys = set((await s.execute(select(app_meta.c.key))).scalars())
    assert keys == {"a"}  # « b » a été annulé


async def test_values_are_bound_parameters_never_sql(db):
    await migrate("upgrade", "head")
    evil = "x'); DROP TABLE app_meta; --"
    async with db.session() as s:
        await s.execute(insert(app_meta).values(key="evil", value=evil))
    async with db.session() as s:
        stored = (await s.execute(select(app_meta.c.value).where(app_meta.c.key == "evil"))).scalar_one()
    assert stored == evil and "app_meta" in await tables(db)


async def test_database_enforces_column_limits(db):
    await migrate("upgrade", "head")
    from sqlalchemy.exc import DBAPIError

    with pytest.raises(DBAPIError):
        async with db.session() as s:
            await s.execute(insert(app_meta).values(key="k" * 65, value="v"))


async def test_ping_ok(db):
    await db.ping()


# ---------- sonde HTTP ----------
def client_with(url: str | None):
    settings = Settings(
        _env_file=None, database_url=url or "", read_rate_limit_requests=1000, llm_api_key="ci-dummy", search_providers="wikipedia"
    )
    return TestClient(create_app(settings))


def test_health_db_reports_ok_with_a_real_database():
    with client_with(URL) as client:
        assert client.get("/health/db").json() == {"db": "ok"}


def test_health_db_reports_down_without_leaking_host_or_password():
    bad = "postgresql://leaky:topsecret@127.0.0.1:1/nope"
    with client_with(bad) as client:
        r = client.get("/health/db")
    assert r.status_code == 503 and r.json() == {"db": "down"}
    assert "topsecret" not in r.text and "127.0.0.1" not in r.text and "leaky" not in r.text


def test_health_db_disabled_without_url():
    with client_with(None) as client:
        assert client.get("/health/db").json() == {"db": "disabled"}


# ---------- migration en ligne de commande (ce que fait start.sh) ----------
def run_alembic(env_url: str | None) -> subprocess.CompletedProcess:
    env = {**os.environ, "FACTS_DATABASE_URL": env_url or ""}
    return subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=60
    )


async def test_cli_migration_applies_with_the_environment_url(db):
    result = await asyncio.to_thread(run_alembic, URL)
    assert result.returncode == 0, result.stderr
    assert "app_meta" in await tables(db)


def test_cli_migration_fails_fast_on_a_bad_database_without_leaking_the_password():
    result = run_alembic("postgresql://leaky:topsecret@127.0.0.1:1/nope")
    assert result.returncode != 0
    assert "topsecret" not in result.stdout + result.stderr
