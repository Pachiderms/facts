"""start.sh : migrations avant le trafic seulement si une base est configurée ; échec = pas de démarrage."""

import os
import stat
import subprocess
from pathlib import Path

START = Path(__file__).resolve().parents[1] / "start.sh"


def run(tmp_path: Path, *, db_url: str | None, alembic_exit: int = 0):
    log = tmp_path / "calls.log"
    for name, code in (("alembic", alembic_exit), ("uvicorn", 0)):
        stub = tmp_path / name
        stub.write_text(f'#!/bin/sh\necho "{name} $@" >> "{log}"\nexit {code}\n')
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    env = {"PATH": f"{tmp_path}:/usr/bin:/bin", "PORT": "9123"}
    if db_url is not None:
        env["FACTS_DATABASE_URL"] = db_url
    result = subprocess.run(["sh", str(START)], env=env, capture_output=True, text=True, timeout=20)
    calls = log.read_text().splitlines() if log.exists() else []
    return result, calls


def test_without_database_only_uvicorn_runs(tmp_path):
    result, calls = run(tmp_path, db_url=None)
    assert result.returncode == 0
    assert len(calls) == 1 and calls[0].startswith("uvicorn app.main:app") and "--port 9123" in calls[0]


def test_empty_database_url_counts_as_no_database(tmp_path):
    _, calls = run(tmp_path, db_url="")
    assert [c.split()[0] for c in calls] == ["uvicorn"]


def test_with_database_migrates_before_serving(tmp_path):
    _, calls = run(tmp_path, db_url="postgresql://u:p@h/db")
    assert [c.split()[0] for c in calls] == ["alembic", "uvicorn"]
    assert calls[0] == "alembic upgrade head"


def test_failed_migration_blocks_startup(tmp_path):
    result, calls = run(tmp_path, db_url="postgresql://u:p@h/db", alembic_exit=3)
    assert result.returncode == 3
    assert [c.split()[0] for c in calls] == ["alembic"]  # uvicorn n'est jamais lancé
