"""NetBox domain agent."""

from __future__ import annotations

from collections.abc import Mapping
from textwrap import dedent

from langchain.agents import AgentExecutor
from langchain_core.language_models import BaseLanguageModel
from langchain_core.tools import BaseTool

from . import AgentConfig, AgentContext, build_agent_executor
from .utils import select_tools

__all__ = ["NETBOX_TOOL_KEYS", "build_netbox_agent"]

NETBOX_TOOL_KEYS: tuple[str, ...] = ("netbox_live_search",)


def build_netbox_agent(
    llm: BaseLanguageModel,
    context: AgentContext,
    tool_registry: Mapping[str, BaseTool],
) -> AgentExecutor:
    tools = select_tools(tool_registry, NETBOX_TOOL_KEYS)
    if not tools:
        raise ValueError("NetBox agent requires at least one NetBox tool")

    instructions = dedent(
        """
        Focus on inventory accuracy; include device or VM roles, locations and IP details when relevant.
        Honour context.vars defaults such as datasetPref or defaultTeam when choosing filters.
        Emphasise actionable next steps like checking management IPs or linked documentation.
        """
    ).strip()

    config = AgentConfig(
        name="NetBox Agent",
        goal="surface live inventory data",
        instructions=instructions,
        tools=tools,
    )
    return build_agent_executor(llm, config, context)
