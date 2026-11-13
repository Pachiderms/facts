"""Compteurs de quotas durables : usage_counters

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usage_counters",
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("count", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("kind", "key", "day", name="pk_usage_counters"),
    )


def downgrade() -> None:
    op.drop_table("usage_counters")
