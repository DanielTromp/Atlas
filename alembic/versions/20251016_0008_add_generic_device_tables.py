"""add generic device tables

Revision ID: 20251016_0008
Revises: 20250325_0007
Create Date: 2025-10-16 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20251016_0008"
down_revision = "20250325_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create devices table - central table for all infrastructure devices
    op.create_table(
        "devices",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("device_type", sa.String(length=50), nullable=False),
        sa.Column("source_system", sa.String(length=50), nullable=False),
        sa.Column("source_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("metadata", sa.Text(), nullable=True),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("source_system", "source_id", name="uq_device_source"),
    )

    # Create indexes for devices table
    op.create_index("ix_devices_device_type", "devices", ["device_type"])
    op.create_index("ix_devices_name", "devices", ["name"])
    op.create_index("ix_devices_status", "devices", ["status"])
    op.create_index("ix_devices_last_seen", "devices", ["last_seen"])

    # Create device_relationships table
    op.create_table(
        "device_relationships",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("parent_device_id", sa.Integer(), nullable=False),
        sa.Column("child_device_id", sa.Integer(), nullable=False),
        sa.Column("relationship_type", sa.String(length=50), nullable=False),
        sa.Column("metadata", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["parent_device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["child_device_id"], ["devices.id"], ondelete="CASCADE"),
    )

    # Create indexes for device_relationships
    op.create_index("ix_device_relationships_parent", "device_relationships", ["parent_device_id"])
    op.create_index("ix_device_relationships_child", "device_relationships", ["child_device_id"])
    op.create_index("ix_device_relationships_type", "device_relationships", ["relationship_type"])

    # Create sync_metadata table
    op.create_table(
        "sync_metadata",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_system", sa.String(length=50), nullable=False),
        sa.Column("source_identifier", sa.String(length=255), nullable=True),
        sa.Column("last_sync_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_complete", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_status", sa.String(length=20), nullable=True),
        sa.Column("sync_duration_seconds", sa.Float(), nullable=True),
        sa.Column("devices_added", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("devices_updated", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("devices_removed", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("source_system", "source_identifier", name="uq_sync_metadata_source"),
    )

    # Create index for sync_metadata
    op.create_index("ix_sync_metadata_last_sync_complete", "sync_metadata", ["last_sync_complete"])


def downgrade() -> None:
    op.drop_index("ix_sync_metadata_last_sync_complete", "sync_metadata")
    op.drop_table("sync_metadata")

    op.drop_index("ix_device_relationships_type", "device_relationships")
    op.drop_index("ix_device_relationships_child", "device_relationships")
    op.drop_index("ix_device_relationships_parent", "device_relationships")
    op.drop_table("device_relationships")

    op.drop_index("ix_devices_last_seen", "devices")
    op.drop_index("ix_devices_status", "devices")
    op.drop_index("ix_devices_name", "devices")
    op.drop_index("ix_devices_device_type", "devices")
    op.drop_table("devices")
