"""Add AI usage tracking tables.

Revision ID: 20251213_0014
Revises: 20251212_0013
Create Date: 2024-12-13

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20251213_0014"
down_revision: str | None = "20251212_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # AI Activity Logs - tracks all API calls
    op.create_table(
        "ai_activity_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("generation_id", sa.String(64), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True),
        # Provider and model info
        sa.Column("provider", sa.String(32), nullable=False, index=True),
        sa.Column("model", sa.String(128), nullable=False, index=True),
        sa.Column("model_provider", sa.String(64), nullable=True),
        # Token usage
        sa.Column("tokens_prompt", sa.Integer(), default=0, nullable=False),
        sa.Column("tokens_completion", sa.Integer(), default=0, nullable=False),
        sa.Column("tokens_reasoning", sa.Integer(), default=0, nullable=False),
        sa.Column("tokens_total", sa.Integer(), default=0, nullable=False),
        # Cost tracking
        sa.Column("cost_usd", sa.Float(), default=0.0, nullable=False),
        # Performance metrics
        sa.Column("generation_time_ms", sa.Integer(), nullable=True),
        sa.Column("time_to_first_token_ms", sa.Integer(), nullable=True),
        sa.Column("tokens_per_second", sa.Float(), nullable=True),
        # Request info
        sa.Column("streamed", sa.Boolean(), default=True, nullable=False),
        sa.Column("finish_reason", sa.String(32), nullable=True),
        sa.Column("cancelled", sa.Boolean(), default=False, nullable=False),
        # Context
        sa.Column("user_id", sa.String(36), nullable=True),
        sa.Column("session_id", sa.String(64), nullable=True, index=True),
        sa.Column("app_name", sa.String(64), nullable=True),
    )

    # AI Model Configurations - custom pricing and settings
    op.create_table(
        "ai_model_configs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=True),
        # Pricing per 1M tokens
        sa.Column("price_input_per_million", sa.Float(), default=0.0, nullable=False),
        sa.Column("price_output_per_million", sa.Float(), default=0.0, nullable=False),
        # Model capabilities
        sa.Column("context_window", sa.Integer(), nullable=True),
        sa.Column("supports_tools", sa.Boolean(), default=True, nullable=False),
        sa.Column("supports_streaming", sa.Boolean(), default=True, nullable=False),
        sa.Column("supports_vision", sa.Boolean(), default=False, nullable=False),
        # Status
        sa.Column("is_active", sa.Boolean(), default=True, nullable=False),
        sa.Column("is_preferred", sa.Boolean(), default=False, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("provider", "model_id", name="uq_provider_model"),
    )


def downgrade() -> None:
    op.drop_table("ai_model_configs")
    op.drop_table("ai_activity_logs")
