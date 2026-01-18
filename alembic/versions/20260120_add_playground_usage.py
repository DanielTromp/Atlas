"""Add playground_usage table for logging agent interactions.

Revision ID: 20260120_usage
Revises: 20260118_0017
Create Date: 2026-01-20

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260120_usage"
down_revision: str | None = "20260118_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "playground_usage",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        # User info
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("username", sa.String(255), nullable=True),  # Denormalized for easy querying
        # Session/request info
        sa.Column("session_id", sa.String(64), nullable=False, index=True),
        sa.Column("agent_id", sa.String(50), nullable=False, index=True),
        sa.Column("model", sa.String(100), nullable=False),
        # Message content
        sa.Column("user_message", sa.Text(), nullable=False),
        sa.Column("assistant_message", sa.Text(), nullable=True),
        # Token usage
        sa.Column("input_tokens", sa.Integer(), nullable=False, default=0),
        sa.Column("output_tokens", sa.Integer(), nullable=False, default=0),
        sa.Column("total_tokens", sa.Integer(), nullable=False, default=0),
        # Cost (in USD, stored as cents for precision)
        sa.Column("cost_usd", sa.Float(), nullable=False, default=0.0),
        # Tool calls (JSON array)
        sa.Column("tool_calls", sa.JSON(), nullable=True),
        # Performance
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        # Error tracking
        sa.Column("error", sa.Text(), nullable=True),
        # Timestamps
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False, index=True),
    )

    # Create indexes for common queries
    op.create_index("ix_playground_usage_user_created", "playground_usage", ["user_id", "created_at"])
    op.create_index("ix_playground_usage_agent_created", "playground_usage", ["agent_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_playground_usage_agent_created")
    op.drop_index("ix_playground_usage_user_created")
    op.drop_table("playground_usage")
