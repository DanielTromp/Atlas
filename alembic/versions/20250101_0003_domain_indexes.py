"""add indexes supporting domain repositories

Revision ID: 20250101_0003
Revises: 20241220_0002
Create Date: 2025-01-01 00:00:00
"""
from __future__ import annotations

from alembic import op

revision = "20250101_0003"
down_revision = "20241220_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_chat_messages_session_id_created_at",
        "chat_messages",
        ["session_id", "created_at"],
    )
    op.create_index(
        "ix_chat_sessions_user_id_updated_at",
        "chat_sessions",
        ["user_id", "updated_at"],
    )
    op.create_index(
        "ix_user_api_keys_user_id",
        "user_api_keys",
        ["user_id"],
    )


def downgrade() -> None:  # pragma: no cover - forward-only migration
    raise RuntimeError("Downgrade not supported for 20250101_0003; restore from backup if required.")
