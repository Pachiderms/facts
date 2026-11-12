"""Adresse de base : normalisation Neon/asyncpg, chiffrement par défaut, aucun secret dans les messages."""

import ssl

import pytest

from app.core.config import Settings
from app.db.engine import Database
from app.db.url import DatabaseConfigError, normalize_database_url

NEON = "postgresql://owner:s3cr3t%21@ep-cool-123-pooler.eu-central-1.aws.neon.tech/facts?sslmode=require&channel_binding=require"


def test_neon_url_is_translated_for_asyncpg():
    url, args = normalize_database_url(NEON)
    assert url.drivername == "postgresql+asyncpg"
    assert (url.username, url.password, url.database) == ("owner", "s3cr3t!", "facts")
    assert url.query == {}  # sslmode / channel_binding : asyncpg ne les comprend pas
    assert isinstance(args["ssl"], ssl.SSLContext)


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+asyncpg", "postgresql+psycopg"])
def test_accepted_schemes_all_become_asyncpg(scheme):
    url, _ = normalize_database_url(f"{scheme}://u:p@db.example.com/x")
    assert url.drivername == "postgresql+asyncpg"


def test_remote_hosts_are_encrypted_with_certificate_verification_by_default():
    _, args = normalize_database_url("postgresql://u:p@db.example.com/x")
    ctx = args["ssl"]
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname


def test_local_host_is_plain_by_default_and_sslmode_disable_is_honoured():
    assert "ssl" not in normalize_database_url("postgresql://u:p@localhost/x")[1]
    assert "ssl" not in normalize_database_url("postgresql://u:p@db.example.com/x?sslmode=disable")[1]
    assert "ssl" in normalize_database_url("postgresql://u:p@localhost/x?sslmode=require")[1]


def test_pgbouncer_compatible_and_bounded_timeouts():
    _, args = normalize_database_url(NEON)
    assert args["statement_cache_size"] == 0 and args["prepared_statement_cache_size"] == 0
    assert args["prepared_statement_name_func"]() != args["prepared_statement_name_func"]()
    assert 0 < args["timeout"] <= 15 and 0 < args["command_timeout"] <= 30


@pytest.mark.parametrize("bad", ["", "pas une url", "sqlite:///x.db", "mysql://u:p@h/x", "postgresql://"])
def test_invalid_urls_are_rejected_without_echoing_them(bad):
    with pytest.raises(DatabaseConfigError) as e:
        normalize_database_url(bad)
    assert bad.strip() == "" or bad not in str(e.value)


def test_password_never_appears_in_error_repr_or_settings_dump():
    with pytest.raises(DatabaseConfigError) as e:
        normalize_database_url("mysql://owner:s3cr3t@h/x")
    assert "s3cr3t" not in str(e.value)
    settings = Settings(_env_file=None, database_url=NEON)
    for dump in (repr(settings), str(settings), settings.model_dump_json(), str(settings.model_dump())):
        assert "s3cr3t" not in dump
    assert "s3cr3t" not in repr(Database(NEON))
    assert settings.database_url.get_secret_value() == NEON


def test_database_is_disabled_by_default():
    assert Settings(_env_file=None).database_url.get_secret_value() == ""
