"""Historique « Mes salons » synchronisé : user_rooms

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_rooms",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("room_id", sa.String(64), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("visibility", sa.String(8), nullable=False),
        sa.Column("owner", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("pinned", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("last_visit", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("visibility IN ('public', 'private')", name="ck_user_rooms_visibility"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_user_rooms_user_id_users", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "room_id", name="pk_user_rooms"),
    )


def downgrade() -> None:
    op.drop_table("user_rooms")
