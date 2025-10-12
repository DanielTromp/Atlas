"""add vcenter configs table

Revision ID: 20250325_0007
Revises: 20250320_0006
Create Date: 2025-03-25 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20250325_0007"
down_revision = "20250320_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vcenter_configs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("base_url", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=128), nullable=False),
        sa.Column("password_secret", sa.String(length=128), nullable=False),
        sa.Column("verify_ssl", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("name", name="uq_vcenter_config_name"),
    )


def downgrade() -> None:
    op.drop_table("vcenter_configs")
