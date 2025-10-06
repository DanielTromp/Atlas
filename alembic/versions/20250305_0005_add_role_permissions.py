"""add role permissions table

Revision ID: 20250305_0005
Revises: 20250220_0004
Create Date: 2025-03-05 00:05:00.000000
"""
from __future__ import annotations

from datetime import UTC, datetime

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20250305_0005"
down_revision = "20250220_0004"
branch_labels = None
depends_on = None


ROLE_DEFAULTS: dict[str, dict[str, object]] = {
    "admin": {
        "label": "Administrator",
        "description": "Full access, including configuration management.",
        "permissions": ["export.run", "zabbix.ack", "tools.use", "chat.use"],
    },
    "member": {
        "label": "Member",
        "description": "Standard operator access to exports, Zabbix acknowledgements, tools, and chat.",
        "permissions": ["export.run", "zabbix.ack", "tools.use", "chat.use"],
    },
    "operator": {
        "label": "Operator",
        "description": "Can run exports and acknowledge Zabbix alerts but cannot access chat or automation tools.",
        "permissions": ["export.run", "zabbix.ack"],
    },
    "viewer": {
        "label": "Viewer",
        "description": "Read-only access to dashboards, searches, and downloads.",
        "permissions": [],
    },
}


def upgrade() -> None:
    op.create_table(
        "role_permissions",
        sa.Column("role", sa.String(length=32), primary_key=True, nullable=False),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    role_table = sa.table(
        "role_permissions",
        sa.column("role", sa.String(length=32)),
        sa.column("label", sa.String(length=64)),
        sa.column("description", sa.String(length=255)),
        sa.column("permissions", sa.JSON()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )

    now = datetime.now(UTC)
    payload = []
    for role, spec in ROLE_DEFAULTS.items():
        permissions = [str(p).strip() for p in spec.get("permissions", []) if str(p).strip()]
        payload.append(
            {
                "role": role,
                "label": str(spec.get("label") or role).strip() or role,
                "description": spec.get("description"),
                "permissions": permissions,
                "created_at": now,
                "updated_at": now,
            }
        )
    if payload:
        op.bulk_insert(role_table, payload)


def downgrade() -> None:
    op.drop_table("role_permissions")
