"""Export domain agent."""

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

__all__ = ["EXPORT_TOOL_KEYS", "build_export_agent"]

# Allow router to inject any export-related tools; defaults to all provided.
EXPORT_TOOL_KEYS: tuple[str, ...] = (
    "export_run_job",
    "export_status_overview",
)


def build_export_agent(
    llm: BaseLanguageModel,
    context: AgentContext,
    tool_registry: Mapping[str, BaseTool],
) -> AgentExecutor:
    tools = select_tools(tool_registry, EXPORT_TOOL_KEYS)

    instructions = dedent(
        """
        Coordinate data export tasks such as NetBox CSV refreshes or merge jobs.
        Reflect progress, expected output paths and follow-up steps the operator should take.
        Use context.vars for preferences like datasetPref or defaultTeam when present.
        """
    ).strip()

    config = AgentConfig(
        name="Export Agent",
        goal="manage data exports and summarise results",
        instructions=instructions,
        tools=tools,
    )
    return build_agent_executor(llm, config, context)
