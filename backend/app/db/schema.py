"""Schéma (SQLAlchemy Core). Toute évolution passe par une migration Alembic (`migrations/versions`)."""

import uuid

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, MetaData, String, Table, Uuid, func
from sqlalchemy.sql import expression

# Noms de contraintes prévisibles : les migrations peuvent les retrouver et les supprimer.
metadata = MetaData(
    naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)

# Clé/valeur applicatives (marqueurs, réglages) : première table, sert aussi de preuve que les migrations tournent.
app_meta = Table(
    "app_meta",
    metadata,
    Column("key", String(64), primary_key=True),
    Column("value", String(1024), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


# Comptes (optionnels : sans compte, l'identité reste le jeton anonyme du navigateur).
# Données minimales : l'adresse e-mail et l'identifiant Google (« sub »). Ni nom, ni photo.
users = Table(
    "users",
    metadata,
    Column("id", Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()),
    Column("google_sub", String(255), nullable=False, unique=True),
    Column("email", String(320), nullable=False, unique=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("last_login_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

# Sessions révocables : on ne garde que l'empreinte SHA-256 du jeton (une fuite de la base ne donne aucune session).
sessions = Table(
    "sessions",
    metadata,
    Column("id", Uuid, primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()),
    Column("user_id", Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index("ix_sessions_user_id", "user_id"),
)

# Identités anonymes rattachées à un compte (empreinte du jeton du navigateur, voir core/identity.py).
# Une identité n'appartient qu'à un seul compte.
user_participants = Table(
    "user_participants",
    metadata,
    Column("participant_id", String(16), primary_key=True),
    Column("user_id", Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("linked_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index("ix_user_participants_user_id", "user_id"),
)

# Historique « Mes salons » synchronisé (20 entrées max par compte). Jamais de code d'accès : un salon privé
# se rouvre avec le code gardé sur l'appareil, le serveur ne stocke que ce qu'il faut pour afficher la liste.
user_rooms = Table(
    "user_rooms",
    metadata,
    Column("user_id", Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("room_id", String(64), primary_key=True),
    Column("title", String(120), nullable=False),
    Column("visibility", String(8), nullable=False),
    Column("owner", Boolean, nullable=False, server_default=expression.false()),
    Column("pinned", Boolean, nullable=False, server_default=expression.false()),
    Column("last_visit", BigInteger, nullable=False),
    CheckConstraint("visibility IN ('public', 'private')", name="visibility"),
)
