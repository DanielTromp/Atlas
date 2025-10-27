"""add context variables to chat sessions

Revision ID: 20250220_0004
Revises: 20250101_0003
Create Date: 2025-02-20 00:00:00
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20250220_0004"
down_revision = "20250101_0003"
branch_labels = None
depends_on = None


def _json_type(bind) -> sa.types.TypeEngine:
    base = sa.JSON()
    if bind.dialect.name == "sqlite":
        base = base.with_variant(sa.Text(), "sqlite")
    return base


def upgrade() -> None:
    bind = op.get_bind()
    json_type = _json_type(bind)
    with op.batch_alter_table("chat_sessions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("context_variables", json_type, nullable=True))

    # Backfill existing rows with empty JSON object
    if bind.dialect.name == "postgresql":
        op.execute("UPDATE chat_sessions SET context_variables='{}'::jsonb WHERE context_variables IS NULL")
    else:
        op.execute("UPDATE chat_sessions SET context_variables='{}' WHERE context_variables IS NULL")

    with op.batch_alter_table("chat_sessions", schema=None) as batch_op:
        batch_op.alter_column("context_variables", nullable=False)


def downgrade() -> None:  # pragma: no cover
    with op.batch_alter_table("chat_sessions", schema=None) as batch_op:
        batch_op.drop_column("context_variables")
