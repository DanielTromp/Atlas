"""add username column to foreman_configs

Revision ID: 20251122_0011
Revises: 20251122_0010
Create Date: 2025-11-22 00:00:01
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20251122_0011"
down_revision = "20251122_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Check if column already exists
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "foreman_configs" in inspector.get_table_names():
        columns = [col["name"] for col in inspector.get_columns("foreman_configs")]
        if "username" not in columns:
            # SQLite requires batch_alter_table for column modifications
            with op.batch_alter_table("foreman_configs", schema=None) as batch_op:
                batch_op.add_column(sa.Column("username", sa.String(length=128), nullable=True))
            # Set a default username for existing rows (users will need to update)
            op.execute("UPDATE foreman_configs SET username = 'admin' WHERE username IS NULL")
            # Make it NOT NULL using batch_alter_table
            with op.batch_alter_table("foreman_configs", schema=None) as batch_op:
                batch_op.alter_column("username", nullable=False)


def downgrade() -> None:
    op.drop_column("foreman_configs", "username")

