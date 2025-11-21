"""add module configs table for modular integration system

Revision ID: 20251120_0009
Revises: 20251016_0008
Create Date: 2025-11-20 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20251120_0009"
down_revision = "20251016_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "module_configs",
        sa.Column("module_name", sa.String(length=64), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("config_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("module_configs")
