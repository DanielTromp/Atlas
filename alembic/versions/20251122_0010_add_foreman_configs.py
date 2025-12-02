"""add foreman configs table

Revision ID: 20251122_0010
Revises: 20251120_0009
Create Date: 2025-11-22 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20251122_0010"
down_revision = "20251120_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Check if table already exists (handles case where table was created manually)
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "foreman_configs" not in inspector.get_table_names():
        op.create_table(
            "foreman_configs",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("name", sa.String(length=80), nullable=False),
            sa.Column("base_url", sa.String(length=255), nullable=False),
            sa.Column("token_secret", sa.String(length=128), nullable=False),
            sa.Column("verify_ssl", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("name", name="uq_foreman_config_name"),
        )


def downgrade() -> None:
    op.drop_table("foreman_configs")
