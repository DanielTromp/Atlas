"""Admin domain agent."""

from __future__ import annotations

from collections.abc import Mapping
from textwrap import dedent

from langchain.agents import AgentExecutor
from langchain_core.language_models import BaseLanguageModel
from langchain_core.tools import BaseTool

from . import AgentConfig, AgentContext, build_agent_executor
from .utils import select_tools

__all__ = ["ADMIN_TOOL_KEYS", "build_admin_agent"]

ADMIN_TOOL_KEYS: tuple[str, ...] = (
    "admin_config_overview",
    "admin_backup_status",
)


def build_admin_agent(
    llm: BaseLanguageModel,
    context: AgentContext,
    tool_registry: Mapping[str, BaseTool],
) -> AgentExecutor:
    tools = select_tools(tool_registry, ADMIN_TOOL_KEYS)

    instructions = dedent(
        """
        Handle administrative operations including user management, configuration and backups.
        Highlight safety considerations and confirm before proposing disruptive actions.
        Leverage context.vars for scope such as defaultTeam or timezone.
        """
    ).strip()

    config = AgentConfig(
        name="Admin Agent",
        goal="assist with platform administration",
        instructions=instructions,
        tools=tools,
    )
    return build_agent_executor(llm, config, context)
