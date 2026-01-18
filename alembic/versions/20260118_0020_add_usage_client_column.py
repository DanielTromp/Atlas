"""Add client column to playground_usage.

Revision ID: 20260118_0020
Revises: 20260118_0019
Create Date: 2026-01-18 16:35:00

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260118_0020"
down_revision: str | None = "20260118_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add client column to track request source (web, telegram, slack, teams)."""
    op.add_column(
        "playground_usage",
        sa.Column("client", sa.String(50), nullable=True, server_default="web"),
    )


def downgrade() -> None:
    """Remove client column."""
    op.drop_column("playground_usage", "client")
