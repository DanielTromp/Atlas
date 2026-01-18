"""Add bot platform integration tables.

Revision ID: 20260118_0018
Revises: 20260120_usage
Create Date: 2026-01-18

Tables created:
- bot_platform_accounts: Links external platform users to Atlas users
- bot_conversations: Tracks bot conversations
- bot_messages: Logs all bot messages
- bot_webhook_configs: Platform webhook configurations
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260118_0018"
down_revision: str | None = "20260120_usage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Bot Platform Accounts - links external platform users to Atlas users
    op.create_table(
        "bot_platform_accounts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("platform", sa.String(32), nullable=False, comment="telegram, slack, teams"),
        sa.Column("platform_user_id", sa.String(255), nullable=False, comment="Platform-specific user ID"),
        sa.Column("platform_username", sa.String(255), nullable=True, comment="Display name from platform"),
        # Verification
        sa.Column("verified", sa.Boolean(), default=False, nullable=False),
        sa.Column("verification_code", sa.String(16), nullable=True),
        sa.Column("verification_expires", sa.DateTime(timezone=True), nullable=True),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("platform", "platform_user_id", name="uq_platform_user"),
    )
    op.create_index("ix_bot_platform_accounts_user_id", "bot_platform_accounts", ["user_id"])
    op.create_index("ix_bot_platform_accounts_platform", "bot_platform_accounts", ["platform"])

    # Bot Conversations - tracks conversations for context
    op.create_table(
        "bot_conversations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("platform", sa.String(32), nullable=False, comment="telegram, slack, teams"),
        sa.Column("platform_conversation_id", sa.String(255), nullable=False, comment="Chat/channel ID"),
        sa.Column(
            "platform_account_id",
            sa.Integer(),
            sa.ForeignKey("bot_platform_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Agent/session context
        sa.Column("agent_id", sa.String(255), nullable=True, comment="If direct agent conversation"),
        sa.Column("session_id", sa.String(64), nullable=True, comment="Links to PlaygroundSession"),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("platform", "platform_conversation_id", name="uq_platform_conversation"),
    )
    op.create_index("ix_bot_conversations_platform_account_id", "bot_conversations", ["platform_account_id"])
    op.create_index("ix_bot_conversations_session_id", "bot_conversations", ["session_id"])

    # Bot Messages - logs all messages for debugging and web GUI
    op.create_table(
        "bot_messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "conversation_id",
            sa.Integer(),
            sa.ForeignKey("bot_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Message info
        sa.Column("direction", sa.String(16), nullable=False, comment="inbound or outbound"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("platform_message_id", sa.String(255), nullable=True),
        # Agent context
        sa.Column("agent_id", sa.String(255), nullable=True),
        sa.Column("tool_calls", sa.JSON(), nullable=True),
        # Token and cost tracking
        sa.Column("input_tokens", sa.Integer(), default=0, nullable=False),
        sa.Column("output_tokens", sa.Integer(), default=0, nullable=False),
        sa.Column("cost_usd", sa.Float(), default=0.0, nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        # Error tracking
        sa.Column("error", sa.Text(), nullable=True),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True),
    )
    op.create_index("ix_bot_messages_conversation_id", "bot_messages", ["conversation_id"])

    # Bot Webhook Configs - platform webhook configurations
    op.create_table(
        "bot_webhook_configs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("platform", sa.String(32), nullable=False, comment="telegram, slack, teams"),
        sa.Column("enabled", sa.Boolean(), default=True, nullable=False),
        # Secrets (stored encrypted via SecretStore reference)
        sa.Column("webhook_secret", sa.String(255), nullable=True, comment="For signature verification"),
        sa.Column("bot_token_secret", sa.String(128), nullable=False, comment="SecretStore key for bot token"),
        # Platform-specific settings
        sa.Column("extra_config", sa.JSON(), nullable=True),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("platform", name="uq_bot_webhook_platform"),
    )


def downgrade() -> None:
    op.drop_table("bot_webhook_configs")
    op.drop_table("bot_messages")
    op.drop_table("bot_conversations")
    op.drop_table("bot_platform_accounts")
