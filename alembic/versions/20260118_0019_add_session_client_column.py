"""Add client column to playground_sessions and playground_usage.

Revision ID: 20260118_0019
Revises: 20260118_0018
Create Date: 2026-01-18 16:30:00

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260118_0019"
down_revision: str | None = "20260118_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add client column to track request source (web, telegram, slack, teams)."""
    # Add to playground_sessions
    op.add_column(
        "playground_sessions",
        sa.Column("client", sa.String(50), nullable=True, server_default="web"),
    )
    # Add to playground_usage
    op.add_column(
        "playground_usage",
        sa.Column("client", sa.String(50), nullable=True, server_default="web"),
    )


def downgrade() -> None:
    """Remove client columns."""
    op.drop_column("playground_sessions", "client")
    op.drop_column("playground_usage", "client")
