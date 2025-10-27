"""add secure settings table

Revision ID: 20250320_0006
Revises: 20250305_0005
Create Date: 2025-03-20 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20250320_0006"
down_revision = "20250305_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "secure_settings",
        sa.Column("name", sa.String(length=64), primary_key=True),
        sa.Column("encrypted_value", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("secure_settings")
