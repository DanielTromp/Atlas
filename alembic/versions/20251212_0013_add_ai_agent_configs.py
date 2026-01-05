"""Add AI agent configuration tables.

Revision ID: 20251212_0013
Revises: 20251202_0012
Create Date: 2024-12-12

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20251212_0013"
down_revision: str | None = "20251202_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # AI Provider Configurations
    op.create_table(
        "ai_provider_configs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(64), unique=True, nullable=False),
        sa.Column("provider_type", sa.String(32), nullable=False),
        sa.Column("enabled", sa.Boolean(), default=True, nullable=False),
        sa.Column("api_key_secret", sa.String(128), nullable=True),  # Reference to secure_settings
        sa.Column("azure_endpoint", sa.String(512), nullable=True),
        sa.Column("azure_deployment", sa.String(128), nullable=True),
        sa.Column("api_version", sa.String(32), nullable=True),
        sa.Column("base_url", sa.String(512), nullable=True),
        sa.Column("default_model", sa.String(128), nullable=True),
        sa.Column("config_json", sa.JSON(), default=dict, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )

    # AI Agent Configurations
    op.create_table(
        "ai_agent_configs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_id", sa.String(64), unique=True, nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("provider_config_id", sa.String(36), nullable=True),  # Logical FK to ai_provider_configs
        sa.Column("provider_type", sa.String(32), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("max_tokens", sa.Integer(), nullable=True),
        sa.Column("tools_enabled", sa.Boolean(), default=True, nullable=False),
        sa.Column("streaming_enabled", sa.Boolean(), default=True, nullable=False),
        sa.Column("is_default", sa.Boolean(), default=False, nullable=False),
        sa.Column("config_json", sa.JSON(), default=dict, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )

    # Update chat_sessions to link to agents
    # Note: SQLite doesn't support ALTER with constraints, so we add columns without FK constraint
    op.add_column("chat_sessions", sa.Column("agent_config_id", sa.String(36), nullable=True))
    op.add_column("chat_sessions", sa.Column("provider_type", sa.String(32), nullable=True))
    op.add_column("chat_sessions", sa.Column("model", sa.String(128), nullable=True))

    # Add metadata to chat_messages for tool calls
    op.add_column("chat_messages", sa.Column("message_type", sa.String(32), nullable=True))
    op.add_column("chat_messages", sa.Column("tool_call_id", sa.String(64), nullable=True))
    op.add_column("chat_messages", sa.Column("tool_name", sa.String(128), nullable=True))
    op.add_column("chat_messages", sa.Column("metadata_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    # Remove columns from chat_messages
    op.drop_column("chat_messages", "metadata_json")
    op.drop_column("chat_messages", "tool_name")
    op.drop_column("chat_messages", "tool_call_id")
    op.drop_column("chat_messages", "message_type")

    # Remove columns from chat_sessions
    op.drop_column("chat_sessions", "model")
    op.drop_column("chat_sessions", "provider_type")
    op.drop_column("chat_sessions", "agent_config_id")

    # Drop tables
    op.drop_table("ai_agent_configs")
    op.drop_table("ai_provider_configs")

