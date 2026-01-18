"""Add playground session and preset tables for Agent Playground.

Revision ID: 20260118_0017
Revises: 20260118_0016
Create Date: 2026-01-18

Tables created:
- playground_sessions: Ephemeral sessions for agent testing
- playground_presets: Saved configuration presets
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260118_0017"
down_revision: str | None = "20260118_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Playground Sessions - ephemeral testing sessions
    op.create_table(
        "playground_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_id", sa.String(255), nullable=False, comment="Agent type: triage, engineer, reviewer, etc."),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        # Session state
        sa.Column("state", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("config_override", sa.JSON(), nullable=False, server_default="{}", comment="Model, temperature, skills"),
        sa.Column("messages", sa.JSON(), nullable=False, server_default="[]", comment="Conversation history"),
        # Metrics
        sa.Column("total_tokens", sa.Integer(), default=0, nullable=False),
        sa.Column("total_cost_usd", sa.Float(), default=0.0, nullable=True),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_playground_sessions_agent_id", "playground_sessions", ["agent_id"])
    op.create_index("ix_playground_sessions_user_id", "playground_sessions", ["user_id"])
    op.create_index("ix_playground_sessions_updated_at", "playground_sessions", ["updated_at"])

    # Playground Presets - saved configuration presets
    op.create_table(
        "playground_presets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("agent_id", sa.String(255), nullable=False, comment="Agent type this preset applies to"),
        # Configuration
        sa.Column("config", sa.JSON(), nullable=False, comment="Model, temperature, skills, prompt override"),
        # Ownership
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
            comment="Owner, null for system presets",
        ),
        sa.Column("is_shared", sa.Boolean(), default=False, nullable=False, comment="Visible to all users"),
        sa.Column("is_default", sa.Boolean(), default=False, nullable=False, comment="Default preset for this agent"),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "name", name="uq_preset_user_name"),
    )
    op.create_index("ix_playground_presets_agent_id", "playground_presets", ["agent_id"])
    op.create_index("ix_playground_presets_user_id", "playground_presets", ["user_id"])
    op.create_index("ix_playground_presets_is_shared", "playground_presets", ["is_shared"])


def downgrade() -> None:
    op.drop_table("playground_presets")
    op.drop_table("playground_sessions")
