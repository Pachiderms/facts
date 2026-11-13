"""Connexion par e-mail : users.google_sub facultatif, table login_codes

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
    op.alter_column("users", "google_sub", existing_type=sa.String(255), nullable=True)
    op.create_table(
        "login_codes",
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("email", name="pk_login_codes"),
    )


def downgrade() -> None:
    op.drop_table("login_codes")
    # Les comptes sans identifiant Google (créés par e-mail) ne peuvent pas revenir à l'ancien schéma : on les retire.
    op.execute("DELETE FROM users WHERE google_sub IS NULL")
    op.alter_column("users", "google_sub", existing_type=sa.String(255), nullable=False)
