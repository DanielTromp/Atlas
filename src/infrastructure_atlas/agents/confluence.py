"""Confluence domain agent."""

from __future__ import annotations

from collections.abc import Mapping
from textwrap import dedent

try:
    from langchain.agents import AgentExecutor
except ImportError:
    from langchain.agents.agent import AgentExecutor
from langchain_core.language_models import BaseLanguageModel
from langchain_core.tools import BaseTool

from . import AgentConfig, AgentContext, build_agent_executor
from .utils import select_tools

__all__ = ["CONFLUENCE_TOOL_KEYS", "build_confluence_agent"]

CONFLUENCE_TOOL_KEYS: tuple[str, ...] = (
    "confluence_search",
    "confluence_get_page_content",
    "confluence_get_page_by_title",
    "confluence_update_page",
    "confluence_create_page",
    "confluence_append_to_page",
    "confluence_convert_markdown_to_storage",
    "confluence_delete_page",
)


def build_confluence_agent(
    llm: BaseLanguageModel,
    context: AgentContext,
    tool_registry: Mapping[str, BaseTool],
) -> AgentExecutor:
    tools = select_tools(tool_registry, CONFLUENCE_TOOL_KEYS)
    if not tools:
        raise ValueError("Confluence agent requires at least one Confluence tool")

    instructions = dedent(
        """
        Surface the most relevant runbooks or knowledge articles with direct links and modification dates.
        Use context.vars such as defaultTeam or timezone to frame the response in local terms.
        Keep summaries short and emphasise next operational steps the reader can take.
        """
    ).strip()

    config = AgentConfig(
        name="Confluence Agent",
        goal="locate documentation and summarise it",
        instructions=instructions,
        tools=tools,
    )
    return build_agent_executor(llm, config, context)
