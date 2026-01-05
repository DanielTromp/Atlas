"""API route exports."""

from . import (
    admin,
    auth,
    commvault,
    confluence,
    core,
    foreman,
    jira,
    netbox,
    profile,
    search,
    tasks,
    tools,
    vcenter,
    zabbix,
)

# Note: chat, export, and ai_chat are imported lazily in __init__.py to avoid circular imports
__all__ = [
    "admin",
    "ai_chat",
    "auth",
    "commvault",
    "confluence",
    "core",
    "foreman",
    "jira",
    "netbox",
    "profile",
    "search",
    "tasks",
    "tools",
    "vcenter",
    "zabbix",
]
