"""Mesure des coûts : cost_usage (totaux journaliers, sans donnée personnelle)

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cost_usage",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("profile", sa.String(16), nullable=False),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("calls", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("errors", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("prompt_tokens", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("completion_tokens", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("credits", sa.BigInteger(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("day", "profile", "operation", "kind", "name", name="pk_cost_usage"),
    )


def downgrade() -> None:
    op.drop_table("cost_usage")
