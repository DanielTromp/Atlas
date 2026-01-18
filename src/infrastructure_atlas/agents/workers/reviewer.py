"""Reviewer Agent for quality assurance of agent decisions.

The ReviewerAgent is responsible for:
- Reviewing categorization accuracy
- Validating proposed actions for safety
- Reviewing customer response quality
- Determining if human approval is needed
"""

from __future__ import annotations

from typing import Any

from infrastructure_atlas.agents.workflow_agent import AgentConfig, BaseAgent
from infrastructure_atlas.infrastructure.logging import get_logger
from infrastructure_atlas.skills import SkillsRegistry

logger = get_logger(__name__)


class ReviewerAgent(BaseAgent):
    """Agent specialized in quality assurance and validation.

    This agent reviews:
    1. Categorization accuracy
    2. Proposed actions for safety
    3. Customer response quality
    4. Determines if human approval is required
    """

    def __init__(
        self,
        config: AgentConfig | None = None,
        skills_registry: SkillsRegistry | None = None,
    ):
        if config is None:
            config = AgentConfig(
                name="Reviewer Agent",
                role="quality assurance reviewer",
                prompt_file="reviewer.md",
                model="claude-sonnet-4-5-20250929",
                temperature=0.3,  # Low temperature for consistent review
                tools=["jira", "confluence"],
            )
        super().__init__(config, skills_registry)

    def process(self, state: dict[str, Any]) -> dict[str, Any]:
        """Review the workflow state and validate decisions.

        Args:
            state: Workflow state with categorization, investigation, and proposed actions

        Returns:
            Updated state with review decisions
        """
        ticket = state.get("ticket", {})

        # Build comprehensive review context
        context = self._build_review_context(state)

        # Step 1: Review categorization
        categorization_review = self._review_categorization(context, state)

        # Step 2: Review proposed actions
        actions_review = self._review_actions(context, state)

        # Step 3: Review customer response
        response_review = self._review_response(context, state)

        # Step 4: Determine overall assessment
        overall_assessment = self._assess_overall(
            categorization_review,
            actions_review,
            response_review,
        )

        # Determine if human approval is needed
        requires_human = self._requires_human_approval(state, overall_assessment)

        human_prompt = None
        if requires_human:
            human_prompt = self._generate_human_prompt(state, overall_assessment)

        logger.info(
            f"Review complete for {ticket.get('key')}",
            extra={
                "decision": overall_assessment.get("decision"),
                "requires_human": requires_human,
            },
        )

        return {
            "decisions": [
                {
                    "type": "review",
                    "categorization_review": categorization_review,
                    "actions_review": actions_review,
                    "response_review": response_review,
                    "overall": overall_assessment,
                    "requires_human": requires_human,
                }
            ],
            "requires_human": requires_human,
            "human_prompt": human_prompt,
        }

    def _build_review_context(self, state: dict[str, Any]) -> str:
        """Build context for review."""
        ticket = state.get("ticket", {})
        parts = [
            "=== Ticket ===",
            f"Key: {ticket.get('key')}",
            f"Summary: {ticket.get('summary')}",
            f"Priority: {ticket.get('priority')}",
            "",
            "=== Triage Results ===",
            f"Category: {state.get('category')}",
            f"Complexity: {state.get('complexity')}",
            f"Suggested Team: {state.get('suggested_team')}",
        ]

        if state.get("investigation"):
            parts.append("")
            parts.append("=== Investigation ===")
            parts.append(str(state.get("investigation", {}).get("summary", "")))

        if state.get("proposed_actions"):
            parts.append("")
            parts.append("=== Proposed Actions ===")
            for action in state.get("proposed_actions", []):
                parts.append(f"- {action.get('skill')}.{action.get('action')}: {action.get('description')}")

        if state.get("prepared_response"):
            parts.append("")
            parts.append("=== Prepared Response ===")
            parts.append(state.get("prepared_response", ""))

        return "\n".join(parts)

    def _review_categorization(
        self,
        context: str,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        """Review the ticket categorization."""
        question = """Review the ticket categorization:
1. Does the category match the ticket content?
2. Is the complexity assessment reasonable?
3. Is the team assignment appropriate?

Provide: APPROVE, SUGGEST_CHANGE, or FLAG with reasoning."""

        response = self.think(context=context, question=question)

        # Determine decision from response
        decision = "approve"
        if "suggest" in response.lower() or "change" in response.lower():
            decision = "suggest_change"
        elif "flag" in response.lower() or "reject" in response.lower():
            decision = "flag"

        return {
            "decision": decision,
            "reasoning": response,
            "category_verified": decision == "approve",
        }

    def _review_actions(
        self,
        context: str,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        """Review proposed actions for safety and appropriateness."""
        proposed_actions = state.get("proposed_actions", [])

        if not proposed_actions:
            return {"decision": "approve", "reasoning": "No actions proposed"}

        question = """Review the proposed actions for:
1. Are they appropriate for the issue?
2. Are there any destructive operations that need caution?
3. Is the scope appropriate (not too broad)?
4. Are rollback procedures needed?

For each action, provide: SAFE, NEEDS_CONFIRMATION, or REJECT."""

        response = self.think(context=context, question=question)

        # Check for any dangerous actions
        has_destructive = any(a.get("is_destructive") for a in proposed_actions)

        decision = "approve"
        if "reject" in response.lower():
            decision = "reject"
        elif has_destructive or "confirm" in response.lower():
            decision = "needs_confirmation"

        return {
            "decision": decision,
            "reasoning": response,
            "has_destructive_actions": has_destructive,
            "actions_reviewed": len(proposed_actions),
        }

    def _review_response(
        self,
        context: str,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        """Review the prepared customer response."""
        prepared_response = state.get("prepared_response")

        if not prepared_response:
            return {"decision": "skip", "reasoning": "No response prepared"}

        question = """Review the customer response for:
1. Is the language professional and clear?
2. Is the technical content accurate?
3. Are expectations properly set?
4. Could anything confuse the customer?

Provide: APPROVE, NEEDS_EDIT, or REWRITE."""

        response = self.think(context=context, question=question)

        decision = "approve"
        if "rewrite" in response.lower():
            decision = "rewrite"
        elif "edit" in response.lower() or "change" in response.lower():
            decision = "needs_edit"

        return {
            "decision": decision,
            "reasoning": response,
        }

    def _assess_overall(
        self,
        categorization_review: dict[str, Any],
        actions_review: dict[str, Any],
        response_review: dict[str, Any],
    ) -> dict[str, Any]:
        """Determine overall assessment."""
        decisions = [
            categorization_review.get("decision"),
            actions_review.get("decision"),
            response_review.get("decision"),
        ]

        # Any rejection means overall reject
        if "reject" in decisions or "flag" in decisions:
            return {
                "decision": "reject",
                "summary": "Issues found that require human intervention",
            }

        # Any modification needed
        if any(d in decisions for d in ["suggest_change", "needs_edit", "rewrite", "needs_confirmation"]):
            return {
                "decision": "modify",
                "summary": "Changes recommended before proceeding",
            }

        return {
            "decision": "approve",
            "summary": "All checks passed, ready to proceed",
        }

    def _requires_human_approval(
        self,
        state: dict[str, Any],
        assessment: dict[str, Any],
    ) -> bool:
        """Determine if human approval is required."""
        # Always require human for complex tickets
        if state.get("complexity") == "complex":
            return True

        # Require human if any actions are destructive
        for action in state.get("proposed_actions", []):
            if action.get("requires_confirmation"):
                return True

        # Require human if assessment is not approve
        if assessment.get("decision") != "approve":
            return True

        # Require human for high priority tickets
        priority = state.get("priority", "").lower()
        if priority in ("critical", "highest", "blocker"):
            return True

        return False

    def _generate_human_prompt(
        self,
        state: dict[str, Any],
        assessment: dict[str, Any],
    ) -> str:
        """Generate the prompt to show to human reviewer."""
        ticket = state.get("ticket", {})
        parts = [
            f"## Review Required: {ticket.get('key')}",
            "",
            f"**Summary:** {ticket.get('summary')}",
            f"**Category:** {state.get('category')}",
            f"**Complexity:** {state.get('complexity')}",
            "",
            "### Assessment",
            assessment.get("summary", ""),
            "",
            "### Proposed Actions",
        ]

        for action in state.get("proposed_actions", []):
            status = "[DESTRUCTIVE] " if action.get("is_destructive") else ""
            parts.append(f"- {status}{action.get('description')}")

        parts.extend([
            "",
            "### Options",
            "- **Approve**: Execute proposed actions",
            "- **Modify**: Return to investigation with feedback",
            "- **Reject**: Cancel workflow",
        ])

        return "\n".join(parts)
