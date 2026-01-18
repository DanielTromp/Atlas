"""Skills system for the Atlas Agents Platform.

Skills are modular capabilities that agents can use to interact with external systems.
Each skill provides a set of actions that can be called as tools.

Available skills:
- JiraSkill: Jira ticket management
- ZabbixSkill: Zabbix monitoring operations
- NetBoxSkill: NetBox DCIM/IPAM queries
- VCenterSkill: vCenter VM management
- ConfluenceSkill: Confluence documentation search
"""

from __future__ import annotations

__all__ = [
    "BaseSkill",
    "SkillAction",
    "SkillsRegistry",
]


def __getattr__(name: str):
    if name == "SkillsRegistry":
        from .registry import SkillsRegistry
        return SkillsRegistry
    elif name == "BaseSkill":
        from .base import BaseSkill
        return BaseSkill
    elif name == "SkillAction":
        from .base import SkillAction
        return SkillAction
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
