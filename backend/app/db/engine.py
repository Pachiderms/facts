"""Accès à la base : un moteur asynchrone, des sessions courtes, un `ping` pour la sonde dédiée."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.db.url import normalize_database_url


class Database:
    """Petit pool (offre gratuite : quelques connexions suffisent) ; une connexion coupée par la mise en veille
    de la base est détectée avant usage (`pool_pre_ping`) et remplacée."""

    def __init__(self, url: str, *, pool_size: int = 3, max_overflow: int = 2) -> None:
        sa_url, connect_args = normalize_database_url(url)
        self._engine: AsyncEngine = create_async_engine(
            sa_url,
            connect_args=connect_args,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_pre_ping=True,
            pool_recycle=240,  # sous le délai de veille de 5 min de Neon
            pool_timeout=10,
        )
        self._sessions = async_sessionmaker(self._engine, expire_on_commit=False)

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Une transaction : validée en sortie normale, annulée sur exception."""
        async with self._sessions() as session, session.begin():
            yield session

    async def ping(self) -> None:
        async with self._engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def aclose(self) -> None:
        await self._engine.dispose()

    def __repr__(self) -> str:  # jamais l'adresse : elle contient le mot de passe
        return "Database(<masqué>)"
