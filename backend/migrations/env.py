"""Environnement Alembic (asynchrone). Adresse lue dans FACTS_DATABASE_URL, jamais dans un fichier versionné."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.db.schema import metadata
from app.db.url import DatabaseConfigError, normalize_database_url

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = metadata


def _target() -> tuple:
    # Les tests fournissent l'adresse par `config.attributes` ; en exploitation, par l'environnement.
    raw = config.attributes.get("url") or get_settings().database_url.get_secret_value()
    if not raw:
        raise DatabaseConfigError("FACTS_DATABASE_URL est vide : aucune migration à appliquer.")
    return normalize_database_url(raw)


def run_migrations_offline() -> None:
    url, _ = _target()
    context.configure(url=url.render_as_string(hide_password=False), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    url, connect_args = _target()
    engine = create_async_engine(url, connect_args=connect_args)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_do_run)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
