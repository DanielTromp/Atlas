"""Ops Agent for day-to-day operations and quick responses.

The OpsAgent is responsible for:
- Answering operational queries quickly
- Investigating reported issues
- Performing routine operations
- Coordinating incident responses
- Uses Haiku model for fast, cost-effective responses
"""

from __future__ import annotations

from typing import Any

from infrastructure_atlas.agents.workflow_agent import AgentConfig, BaseAgent
from infrastructure_atlas.infrastructure.logging import get_logger
from infrastructure_atlas.skills import SkillsRegistry

logger = get_logger(__name__)


class OpsAgent(BaseAgent):
    """Agent specialized in day-to-day operations and quick responses.

    This agent:
    1. Answers operational queries quickly using infrastructure tools
    2. Investigates reported issues with system queries
    3. Performs routine operations (acknowledge alerts, update tickets)
    4. Coordinates incident responses across systems
    5. Uses Haiku model for speed and cost efficiency
    """

    def __init__(
        self,
        config: AgentConfig | None = None,
        skills_registry: SkillsRegistry | None = None,
    ):
        if config is None:
            config = AgentConfig(
                name="Ops Agent",
                role="Operations Engineer",
                prompt_file="ops.md",
                model="claude-haiku-4-5-20251001",
                temperature=0.4,
                tools=["jira", "netbox", "zabbix", "vcenter", "confluence", "export"],
            )
        super().__init__(config, skills_registry)

    def process(self, state: dict[str, Any]) -> dict[str, Any]:
        """Process an operational query or task.

        Args:
            state: Workflow state containing query/ticket data

        Returns:
            Updated state with operational response
        """
        # Support both query-based and ticket-based workflows
        query = state.get("query", "")
        ticket = state.get("ticket", {})

        if not query and ticket:
            query = ticket.get("summary", "")

        if not query:
            logger.warning("Ops: No query or ticket data provided")
            return {"errors": [{"phase": "ops", "message": "No query or ticket data"}]}

        # Build context
        context = self._build_ops_context(query, ticket, state)

        # Execute the operational task
        response = self._execute_ops_task(context, state)

        logger.info(
            "Ops task completed",
            extra={
                "query_length": len(query),
                "has_ticket": bool(ticket),
            },
        )

        return {
            "ops_result": response.get("result", ""),
            "actions_taken": response.get("actions", []),
            "systems_queried": response.get("systems", []),
        }

    def _build_ops_context(
        self,
        query: str,
        ticket: dict[str, Any],
        state: dict[str, Any],
    ) -> str:
        """Build context for operational task."""
        parts = ["=== Operational Query ===", query]

        if ticket:
            parts.extend([
                "\n=== Related Ticket ===",
                f"Key: {ticket.get('key', 'N/A')}",
                f"Summary: {ticket.get('summary', 'N/A')}",
                f"Status: {ticket.get('status', 'N/A')}",
                f"Priority: {ticket.get('priority', 'N/A')}",
            ])

        # Add any additional context from state
        if state.get("additional_context"):
            parts.extend([
                "\n=== Additional Context ===",
                str(state.get("additional_context")),
            ])

        return "\n".join(parts)

    def _execute_ops_task(
        self,
        context: str,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute the operational task using available tools."""
        question = """Process this operational request:
1. Identify what information or action is needed
2. Use available tools to gather information or take action
3. Provide a clear, concise response

Be efficient - prefer quick, accurate responses over lengthy investigation."""

        # Use the execute_with_tools method for tool-enabled processing
        result = self.execute_with_tools(
            state={"context": context, **state},
            task=question,
            max_iterations=10,
        )

        # Extract any actions taken from the result
        actions = []
        systems = []

        # Parse tool usage from result if available
        if hasattr(result, "tool_calls"):
            for call in result.tool_calls:
                actions.append({
                    "tool": call.get("name"),
                    "status": "completed",
                })
                systems.append(call.get("name", "").split("_")[0])

        return {
            "result": result.output.get("response", ""),
            "actions": actions,
            "systems": list(set(systems)),
        }
