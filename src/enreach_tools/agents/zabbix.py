"""Zabbix domain agent."""

from __future__ import annotations

from collections.abc import Mapping
from textwrap import dedent

from langchain.agents import AgentExecutor
from langchain_core.language_models import BaseLanguageModel
from langchain_core.tools import BaseTool

from . import AgentConfig, AgentContext, build_agent_executor
from .utils import select_tools

__all__ = ["ZABBIX_TOOL_KEYS", "build_zabbix_agent"]

ZABBIX_TOOL_KEYS: tuple[str, ...] = (
    "zabbix_group_search",
    "zabbix_current_alerts",
    "zabbix_history_search",
)


def build_zabbix_agent(
    llm: BaseLanguageModel,
    context: AgentContext,
    tool_registry: Mapping[str, BaseTool],
) -> AgentExecutor:
    tools = select_tools(tool_registry, ZABBIX_TOOL_KEYS)
    if not tools:
        raise ValueError("Zabbix agent requires at least one registered Zabbix tool")

    instructions = dedent(
        """
        Respond with precise monitoring insight. Highlight severity, acknowledgement state and affected hosts.
        If a request mentions a host group by name, look it up with the group search tool before fetching alerts.
        Cross-reference context.vars filters such as defaultTeam or dateRange when present. Offer guidance on next steps.
        """
    ).strip()

    config = AgentConfig(
        name="Zabbix Agent",
        goal="track live and historical alerts",
        instructions=instructions,
        tools=tools,
    )
    return build_agent_executor(llm, config, context)
