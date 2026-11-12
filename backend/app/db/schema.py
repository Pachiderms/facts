"""Schéma (SQLAlchemy Core). Toute évolution passe par une migration Alembic (`migrations/versions`)."""

from sqlalchemy import Column, DateTime, MetaData, String, Table, func

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
