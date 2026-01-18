"""Concrete agent implementations for the Atlas Agents Platform.

This module provides the specialized agents that handle specific tasks:
- TriageAgent: Analyzes and categorizes incoming tickets
- EngineerAgent: Investigates technical issues
- ReviewerAgent: Reviews and validates solutions
"""

from __future__ import annotations

from typing import Any

from infrastructure_atlas.agents.workflow_agent import AgentConfig, AgentResult, BaseAgent
from infrastructure_atlas.infrastructure.logging import get_logger
from infrastructure_atlas.skills import SkillsRegistry

logger = get_logger(__name__)


class TriageAgent(BaseAgent):
    """Agent specialized in ticket categorization and initial assessment.

    The Triage Agent:
    - Analyzes incoming tickets
    - Determines category and complexity
    - Identifies key entities (hosts, systems)
    - Suggests appropriate assignees
    """

    def __init__(
        self,
        config: AgentConfig | None = None,
        skills_registry: SkillsRegistry | None = None,
    ):
        if config is None:
            config = AgentConfig(
                name="Triage Agent",
                role="Ticket categorization specialist",
                prompt_file="triage.md",
                model="claude-sonnet-4-5-20250929",
                temperature=0.3,
                tools=["jira", "confluence"],
            )
        super().__init__(config, skills_registry)

    def process(self, state: dict[str, Any]) -> dict[str, Any]:
        """Analyze a ticket and return triage information.

        Expected state keys:
            - ticket_id: The ticket identifier
            - ticket_summary: Ticket summary text
            - ticket_description: Full ticket description

        Returns state with added keys:
            - category: Ticket category
            - complexity: Estimated complexity (1-5)
            - entities: Identified entities (hosts, systems, etc.)
            - suggested_assignee: Recommended assignee
        """
        ticket_id = state.get("ticket_id", "unknown")
        summary = state.get("ticket_summary", "")
        description = state.get("ticket_description", "")

        # Use LLM to analyze the ticket
        context = f"""
Ticket ID: {ticket_id}
Summary: {summary}

Description:
{description}
"""

        task = """
Analyze this ticket and provide:
1. Category (e.g., hardware, software, network, access, monitoring)
2. Complexity rating (1-5, where 5 is most complex)
3. Key entities mentioned (hostnames, systems, applications)
4. Suggested next steps

Format your response as structured analysis.
"""

        result = self.execute_with_tools(state, task, max_iterations=5)

        # Update state with analysis
        state["triage_result"] = result.output.get("response", "")
        state["triage_tokens"] = result.tokens_used
        state["triage_complete"] = True

        return state


class EngineerAgent(BaseAgent):
    """Agent specialized in technical investigation and troubleshooting.

    The Engineer Agent:
    - Investigates technical issues using infrastructure tools
    - Queries systems like NetBox, Zabbix, vCenter
    - Analyzes monitoring data and system states
    - Proposes solutions based on findings
    """

    def __init__(
        self,
        config: AgentConfig | None = None,
        skills_registry: SkillsRegistry | None = None,
    ):
        if config is None:
            config = AgentConfig(
                name="Engineer Agent",
                role="Technical investigation specialist",
                prompt_file="engineer.md",
                model="claude-sonnet-4-5-20250929",
                temperature=0.5,
                tools=["jira", "netbox", "zabbix", "vcenter", "commvault"],
            )
        super().__init__(config, skills_registry)

    def process(self, state: dict[str, Any]) -> dict[str, Any]:
        """Investigate a technical issue and propose solutions.

        Expected state keys:
            - ticket_id: The ticket identifier
            - ticket_summary: Ticket summary
            - triage_result: Output from triage (optional)
            - entities: Identified entities to investigate

        Returns state with added keys:
            - investigation: Investigation findings
            - related_systems: Systems involved
            - proposed_solution: Recommended solution
        """
        ticket_id = state.get("ticket_id", "unknown")
        summary = state.get("ticket_summary", "")
        triage = state.get("triage_result", "No triage performed")
        entities = state.get("entities", [])

        context = f"""
Ticket ID: {ticket_id}
Summary: {summary}

Triage Analysis:
{triage}

Entities to investigate: {', '.join(entities) if entities else 'None identified'}
"""

        task = """
Investigate this issue:
1. Query relevant systems for information about the entities
2. Check monitoring status and recent alerts
3. Look for related configuration or documentation
4. Analyze findings and identify root cause
5. Propose a solution or next steps

Use the available tools to gather information.
"""

        result = self.execute_with_tools(state, task, max_iterations=10)

        state["investigation"] = result.output.get("response", "")
        state["investigation_tokens"] = result.tokens_used
        state["investigation_complete"] = True

        return state


class ReviewerAgent(BaseAgent):
    """Agent specialized in validating solutions and quality assurance.

    The Reviewer Agent:
    - Reviews proposed solutions for completeness
    - Validates technical accuracy
    - Checks for potential issues or risks
    - Ensures quality before actions are taken
    """

    def __init__(
        self,
        config: AgentConfig | None = None,
        skills_registry: SkillsRegistry | None = None,
    ):
        if config is None:
            config = AgentConfig(
                name="Reviewer Agent",
                role="Quality assurance specialist",
                prompt_file="reviewer.md",
                model="claude-sonnet-4-5-20250929",
                temperature=0.2,
                tools=["jira", "confluence"],
            )
        super().__init__(config, skills_registry)

    def process(self, state: dict[str, Any]) -> dict[str, Any]:
        """Review investigation findings and proposed solutions.

        Expected state keys:
            - ticket_id: The ticket identifier
            - investigation: Investigation findings
            - proposed_solution: Proposed solution to review

        Returns state with added keys:
            - review_approved: Whether the solution is approved
            - review_notes: Review comments and suggestions
            - risks: Identified risks or concerns
        """
        ticket_id = state.get("ticket_id", "unknown")
        investigation = state.get("investigation", "No investigation")
        solution = state.get("proposed_solution", "No solution proposed")

        context = f"""
Ticket ID: {ticket_id}

Investigation Findings:
{investigation}

Proposed Solution:
{solution}
"""

        task = """
Review this investigation and proposed solution:
1. Verify the investigation was thorough
2. Validate the proposed solution is appropriate
3. Identify any risks or concerns
4. Suggest improvements if needed
5. Decide whether to approve or request changes

Provide a detailed review.
"""

        result = self.execute_with_tools(state, task, max_iterations=5)

        state["review_result"] = result.output.get("response", "")
        state["review_tokens"] = result.tokens_used
        state["review_complete"] = True

        return state
