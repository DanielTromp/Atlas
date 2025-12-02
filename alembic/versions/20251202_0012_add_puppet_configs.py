"""Add puppet_configs table for Puppet Git repository integration.

Revision ID: 20251202_0012
Revises: 20251122_0011
Create Date: 2025-12-02

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20251202_0012"
down_revision: str | None = "20251122_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "puppet_configs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("remote_url", sa.String(512), nullable=False),
        sa.Column("branch", sa.String(128), nullable=False, server_default="production"),
        sa.Column("ssh_key_secret", sa.String(128), nullable=True),
        sa.Column("local_path", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("name", name="uq_puppet_config_name"),
    )


def downgrade() -> None:
    op.drop_table("puppet_configs")

