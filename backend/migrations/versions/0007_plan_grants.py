"""Plans accordés à la main (licence Edu) : plan_grants

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plan_grants",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("plan", sa.String(16), nullable=False),
        sa.Column("check_pool", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("plan IN ('edu')", name="ck_plan_grants_plan_known"),
        sa.CheckConstraint("check_pool IS NULL OR check_pool > 0", name="ck_plan_grants_pool_positive"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_plan_grants_user_id_users", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", name="pk_plan_grants"),
    )


def downgrade() -> None:
    op.drop_table("plan_grants")
