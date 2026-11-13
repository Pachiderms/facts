"""Abonnements Pro et évènements de paiement : subscriptions, billing_events

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subscriptions",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(24), nullable=False),
        sa.Column("provider_subscription_id", sa.String(64), nullable=False),
        sa.Column("provider_customer_id", sa.String(64), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("portal_url", sa.String(512), nullable=True),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", name="pk_subscriptions"),
        sa.UniqueConstraint("provider_subscription_id", name="uq_subscriptions_provider_subscription_id"),
    )
    op.create_table(
        "billing_events",
        sa.Column("event_id", sa.String(64), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("event_id", name="pk_billing_events"),
    )


def downgrade() -> None:
    op.drop_table("billing_events")
    op.drop_table("subscriptions")
