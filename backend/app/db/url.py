"""Adresse de base de données : normalisation (Neon, Supabase, Render…) sans jamais afficher le mot de passe.

Les hébergeurs donnent `postgresql://user:pass@host/db?sslmode=require&channel_binding=require`. SQLAlchemy +
asyncpg veulent `postgresql+asyncpg://` et comprennent `ssl=`, pas `sslmode=` ni `channel_binding=` : on traduit.
"""

import ssl
import uuid
from typing import Any

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", ""}
SSL_OFF = {"disable", "allow", "prefer"}  # libpq : le chiffrement n'y est pas exigé


class DatabaseConfigError(ValueError):
    """Adresse inutilisable. Le message ne contient JAMAIS l'adresse (elle porte le mot de passe)."""


def normalize_database_url(raw: str) -> tuple[URL, dict[str, Any]]:
    """Renvoie l'URL asyncpg (sans paramètres libpq) et les `connect_args` correspondants."""
    raw = raw.strip()
    if raw.startswith("postgres://"):  # ancien alias (Heroku, certains tableaux de bord) refusé par SQLAlchemy 2
        raw = "postgresql://" + raw.removeprefix("postgres://")
    try:
        url = make_url(raw)
    except ArgumentError:
        raise DatabaseConfigError("FACTS_DATABASE_URL n'est pas une adresse valide.") from None
    if url.get_backend_name() != "postgresql":
        raise DatabaseConfigError("FACTS_DATABASE_URL doit être une adresse PostgreSQL (postgresql://…).")
    if not url.host and not url.query.get("host"):
        raise DatabaseConfigError("FACTS_DATABASE_URL : hôte manquant.")

    sslmode = str(url.query.get("sslmode", "")).lower()
    local = (url.host or "") in LOCAL_HOSTS
    # Chiffré par défaut dès que la base n'est pas sur la machine ; certificat vérifié (Neon, Supabase : valides).
    use_ssl = sslmode not in SSL_OFF if sslmode else not local
    connect_args: dict[str, Any] = {
        "timeout": 10,  # connexion : une base Neon qui se réveille met 1-3 s
        "command_timeout": 15,  # aucune requête ne bloque un worker plus longtemps
        # Compatible PgBouncer (adresse « -pooler » de Neon, mode transaction) : pas de requêtes préparées nommées.
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid.uuid4()}__",
    }
    if use_ssl:
        connect_args["ssl"] = ssl.create_default_context()
    clean = URL.create(
        "postgresql+asyncpg", url.username, url.password, url.host, url.port, url.database
    )
    return clean, connect_args
