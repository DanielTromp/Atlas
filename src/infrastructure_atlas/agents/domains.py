"""Domain agent definitions and metadata."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

try:
    from langchain.agents import AgentExecutor
except ImportError:
    from langchain.agents.agent import AgentExecutor
from langchain_core.language_models import BaseLanguageModel
from langchain_core.tools import BaseTool

from .admin import ADMIN_TOOL_KEYS, build_admin_agent
from .confluence import CONFLUENCE_TOOL_KEYS, build_confluence_agent
from .context import AgentContext
from .jira import JIRA_TOOL_KEYS, build_jira_agent
from .netbox import NETBOX_TOOL_KEYS, build_netbox_agent
from .zabbix import ZABBIX_TOOL_KEYS, build_zabbix_agent

__all__ = ["DOMAIN_SPECS", "DomainBuilder", "DomainSpec"]

DomainBuilder = Callable[[BaseLanguageModel, AgentContext, Mapping[str, BaseTool]], AgentExecutor]


@dataclass(frozen=True)
class DomainSpec:
    key: str
    label: str
    builder: DomainBuilder
    tool_keys: tuple[str, ...]

    def build(
        self,
        llm: BaseLanguageModel,
        context: AgentContext,
        tools: Mapping[str, BaseTool],
    ) -> AgentExecutor:
        relevant = {key: tools[key] for key in self.tool_keys if key in tools} if self.tool_keys else tools
        return self.builder(llm, context, relevant)


DOMAIN_SPECS: tuple[DomainSpec, ...] = (
    DomainSpec(
        key="zabbix",
        label="Zabbix",
        builder=build_zabbix_agent,
        tool_keys=ZABBIX_TOOL_KEYS,
    ),
    DomainSpec(
        key="netbox",
        label="NetBox",
        builder=build_netbox_agent,
        tool_keys=NETBOX_TOOL_KEYS,
    ),
    DomainSpec(
        key="jira",
        label="Jira",
        builder=build_jira_agent,
        tool_keys=JIRA_TOOL_KEYS,
    ),
    DomainSpec(
        key="confluence",
        label="Confluence",
        builder=build_confluence_agent,
        tool_keys=CONFLUENCE_TOOL_KEYS,
    ),
    DomainSpec(
        key="admin",
        label="Admin",
        builder=build_admin_agent,
        tool_keys=ADMIN_TOOL_KEYS,
    ),
)
