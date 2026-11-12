"""Table app_meta (base de départ)

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_meta",
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("value", sa.String(1024), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("key", name="pk_app_meta"),
    )


def downgrade() -> None:
    op.drop_table("app_meta")
