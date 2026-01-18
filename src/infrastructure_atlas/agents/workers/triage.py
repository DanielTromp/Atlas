"""Triage Agent for categorizing and assessing incoming tickets.

The TriageAgent is responsible for:
- Categorizing tickets into predefined categories
- Assessing complexity (simple/moderate/complex)
- Finding similar resolved tickets
- Suggesting assignee based on category and workload
"""

from __future__ import annotations

from typing import Any

from infrastructure_atlas.agents.workflow_agent import AgentConfig, BaseAgent
from infrastructure_atlas.infrastructure.logging import get_logger
from infrastructure_atlas.skills import SkillsRegistry

logger = get_logger(__name__)

# Predefined ticket categories
TICKET_CATEGORIES = [
    "Infrastructure/Server",
    "Monitoring/Alert",
    "Network",
    "Security",
    "Backup/Recovery",
    "Database",
    "Application",
    "Documentation",
    "Other",
]


class TriageAgent(BaseAgent):
    """Agent specialized in ticket categorization and triage.

    This agent analyzes incoming tickets and:
    1. Categorizes them into predefined categories
    2. Assesses complexity based on description and history
    3. Searches for similar resolved tickets
    4. Suggests appropriate team/assignee
    """

    def __init__(
        self,
        config: AgentConfig | None = None,
        skills_registry: SkillsRegistry | None = None,
    ):
        if config is None:
            config = AgentConfig(
                name="Triage Agent",
                role="ticket categorization specialist",
                prompt_file="triage.md",
                model="claude-sonnet-4-5-20250929",
                temperature=0.3,
                tools=["jira", "confluence"],
            )
        super().__init__(config, skills_registry)

    def process(self, state: dict[str, Any]) -> dict[str, Any]:
        """Process a ticket for triage.

        Args:
            state: Workflow state containing ticket data

        Returns:
            Updated state with categorization and assessment
        """
        ticket = state.get("ticket", {})

        if not ticket:
            logger.warning("Triage: No ticket data provided")
            return {"errors": [{"phase": "triage", "message": "No ticket data"}]}

        # Build analysis context
        ticket_context = self._build_ticket_context(ticket)

        # Step 1: Categorize the ticket
        categorization = self._categorize_ticket(ticket_context)

        # Step 2: Assess complexity
        complexity = self._assess_complexity(ticket_context, categorization)

        # Step 3: Find similar tickets
        similar_tickets = self._find_similar_tickets(ticket)

        # Step 4: Suggest assignee
        assignment = self._suggest_assignment(categorization, complexity)

        logger.info(
            f"Triaged ticket {ticket.get('key')}",
            extra={
                "category": categorization.get("category"),
                "complexity": complexity.get("level"),
            },
        )

        return {
            "category": categorization.get("category"),
            "subcategory": categorization.get("subcategory"),
            "complexity": complexity.get("level"),
            "estimated_effort": complexity.get("estimated_effort"),
            "suggested_assignee": assignment.get("assignee"),
            "suggested_team": assignment.get("team"),
            "similar_tickets": similar_tickets,
            "decisions": [
                {
                    "type": "categorization",
                    "value": categorization,
                    "confidence": categorization.get("confidence", "medium"),
                },
                {
                    "type": "complexity",
                    "value": complexity,
                    "confidence": complexity.get("confidence", "medium"),
                },
            ],
        }

    def _build_ticket_context(self, ticket: dict[str, Any]) -> str:
        """Build context string from ticket data."""
        parts = [
            f"Ticket: {ticket.get('key')}",
            f"Summary: {ticket.get('summary', 'N/A')}",
            f"Type: {ticket.get('issue_type', 'N/A')}",
            f"Priority: {ticket.get('priority', 'N/A')}",
        ]

        description = ticket.get("description")
        if description:
            # Truncate long descriptions
            parts.append(f"Description: {description[:1000]}...")

        labels = ticket.get("labels", [])
        if labels:
            parts.append(f"Labels: {', '.join(labels)}")

        return "\n".join(parts)

    def _categorize_ticket(self, context: str) -> dict[str, Any]:
        """Determine ticket category using LLM."""
        question = f"""Based on the ticket information, categorize this ticket.
Available categories: {', '.join(TICKET_CATEGORIES)}

Respond with:
1. Primary category (exactly one from the list)
2. Optional subcategory if applicable
3. Confidence level (high/medium/low)
4. Brief reasoning"""

        response = self.think(context=context, question=question)

        # Parse response (simplified - in production, use structured output)
        category = self._extract_category_from_response(response)

        return {
            "category": category.get("primary", "Other"),
            "subcategory": category.get("secondary"),
            "confidence": category.get("confidence", "medium"),
            "reasoning": response,
        }

    def _assess_complexity(
        self,
        context: str,
        categorization: dict[str, Any],
    ) -> dict[str, Any]:
        """Assess ticket complexity."""
        question = """Assess the complexity of this ticket:
- Simple (<30 min): Clear issue, known solution, single system
- Moderate (30 min - 2 hr): Multiple systems, some investigation needed
- Complex (>2 hr): Unknown root cause, cross-team coordination, potential outage

Provide:
1. Complexity level (simple/moderate/complex)
2. Estimated effort
3. Key factors affecting complexity"""

        full_context = f"{context}\n\nCategory: {categorization.get('category')}"
        response = self.think(context=full_context, question=question)

        # Extract complexity (simplified parsing)
        level = "moderate"  # default
        if "simple" in response.lower():
            level = "simple"
        elif "complex" in response.lower():
            level = "complex"

        effort_map = {
            "simple": "<30 minutes",
            "moderate": "30 min - 2 hours",
            "complex": ">2 hours",
        }

        return {
            "level": level,
            "estimated_effort": effort_map.get(level, "Unknown"),
            "confidence": "medium",
            "reasoning": response,
        }

    def _find_similar_tickets(self, ticket: dict[str, Any]) -> list[dict[str, Any]]:
        """Find similar resolved tickets."""
        if not self.skills_registry:
            return []

        jira = self.skills_registry.get("jira")
        if not jira:
            return []

        try:
            summary = ticket.get("summary", "")
            if not summary:
                return []

            similar = jira.execute(
                "get_similar_issues",
                {
                    "text": summary,
                    "project": ticket.get("project", {}).get("key"),
                    "max_results": 5,
                },
            )

            return similar

        except Exception as e:
            logger.warning(f"Failed to find similar tickets: {e!s}")
            return []

    def _suggest_assignment(
        self,
        categorization: dict[str, Any],
        complexity: dict[str, Any],
    ) -> dict[str, Any]:
        """Suggest team and assignee based on category."""
        # This would be enhanced with workload balancing in production
        category = categorization.get("category", "Other")

        # Simple category-to-team mapping
        team_mapping = {
            "Infrastructure/Server": "infrastructure-team",
            "Monitoring/Alert": "monitoring-team",
            "Network": "network-team",
            "Security": "security-team",
            "Backup/Recovery": "backup-team",
            "Database": "dba-team",
            "Application": "app-support-team",
            "Documentation": "documentation-team",
            "Other": "general-support",
        }

        return {
            "team": team_mapping.get(category, "general-support"),
            "assignee": None,  # Would be filled by workload balancer
        }

    def _extract_category_from_response(self, response: str) -> dict[str, Any]:
        """Extract category from LLM response."""
        response_lower = response.lower()

        for category in TICKET_CATEGORIES:
            if category.lower() in response_lower:
                return {"primary": category, "confidence": "high"}

        # Fallback to "Other"
        return {"primary": "Other", "confidence": "low"}
