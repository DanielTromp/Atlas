"""Shared role and permission defaults for the Infrastructure Atlas platform."""
from __future__ import annotations

from typing import Any

ROLE_CAPABILITIES: tuple[dict[str, str], ...] = (
    {
        "id": "export.run",
        "label": "Run exports",
        "description": "Allow users to start NetBox export jobs from the Export page.",
    },
    {
        "id": "zabbix.ack",
        "label": "Acknowledge Zabbix alerts",
        "description": "Allow acknowledging problems from the Zabbix dashboard.",
    },
    {
        "id": "tools.use",
        "label": "Access automation tools",
        "description": "Allow running automation utilities from the Tools section.",
    },
    {
        "id": "chat.use",
        "label": "Use chat assistants",
        "description": "Allow opening conversations in the Chat page.",
    },
    {
        "id": "vcenter.view",
        "label": "View vCenter inventory",
        "description": "Allow viewing vCenter data and VM inventory dashboards.",
    },
)

DEFAULT_ROLE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "admin": {
        "label": "Administrator",
        "description": "Full access, including configuration management.",
        "permissions": [cap["id"] for cap in ROLE_CAPABILITIES],
    },
    "member": {
        "label": "Member",
        "description": "Standard operator access to exports, Zabbix acknowledgements, tools, and chat.",
        "permissions": [cap["id"] for cap in ROLE_CAPABILITIES],
    },
    "operator": {
        "label": "Operator",
        "description": "Can run exports and acknowledge Zabbix alerts but cannot access chat or automation tools.",
        "permissions": ["export.run", "zabbix.ack", "vcenter.view"],
    },
    "viewer": {
        "label": "Viewer",
        "description": "Read-only access to dashboards, searches, and downloads.",
        "permissions": ["vcenter.view"],
    },
}

__all__ = ["DEFAULT_ROLE_DEFINITIONS", "ROLE_CAPABILITIES"]
