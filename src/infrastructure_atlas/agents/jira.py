"""Jira domain agent."""

from __future__ import annotations

from collections.abc import Mapping
from textwrap import dedent

from langchain.agents import AgentExecutor
from langchain_core.language_models import BaseLanguageModel
from langchain_core.tools import BaseTool

from . import AgentConfig, AgentContext, build_agent_executor
from .utils import select_tools

__all__ = ["JIRA_TOOL_KEYS", "build_jira_agent"]

JIRA_TOOL_KEYS: tuple[str, ...] = ("jira_issue_search",)


def build_jira_agent(
    llm: BaseLanguageModel,
    context: AgentContext,
    tool_registry: Mapping[str, BaseTool],
) -> AgentExecutor:
    tools = select_tools(tool_registry, JIRA_TOOL_KEYS)
    if not tools:
        raise ValueError("Jira agent requires at least one Jira tool")

    instructions = dedent(
        """
        Provide concise operational summaries of issues: status, assignee, priority and deadlines.
        Apply context.vars such as defaultProject, defaultTeam or dateRange when selecting filters.
        When informing next steps, reference Jira actions like acknowledging or escalating incidents.
        """
    ).strip()

    config = AgentConfig(
        name="Jira Agent",
        goal="analyse incidents and work queues",
        instructions=instructions,
        tools=tools,
    )
    return build_agent_executor(llm, config, context)
