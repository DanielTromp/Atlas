"""Reusable workflow node functions.

These node functions can be used to build workflows by registering
them with the WorkflowEngine and connecting them via edges.
"""

from __future__ import annotations

from typing import Any

from infrastructure_atlas.infrastructure.logging import get_logger

logger = get_logger(__name__)


def fetch_ticket(state: dict[str, Any]) -> dict[str, Any]:
    """Node: Fetch ticket details from Jira.

    Expects:
        state["ticket_id"]: Ticket key like "ESD-1234"

    Updates:
        state["ticket"]: Full ticket data
        state["current_phase"]: "ticket_fetched"
    """
    from infrastructure_atlas.skills.registry import get_skills_registry

    ticket_id = state.get("ticket_id")
    if not ticket_id:
        # Try to get from trigger data
        ticket_id = state.get("trigger_data", {}).get("ticket_id")

    if not ticket_id:
        return {
            "errors": [{"phase": "fetch_ticket", "message": "No ticket_id provided"}],
            "current_phase": "error",
        }

    registry = get_skills_registry()
    jira = registry.get("jira")

    if not jira:
        return {
            "errors": [{"phase": "fetch_ticket", "message": "Jira skill not available"}],
            "current_phase": "error",
        }

    try:
        ticket = jira.execute("get_issue", {"issue_key": ticket_id})
        logger.info(f"Fetched ticket: {ticket_id}")

        return {
            "ticket": ticket,
            "ticket_id": ticket_id,
            "ticket_type": ticket.get("issue_type"),
            "priority": ticket.get("priority"),
            "current_phase": "ticket_fetched",
        }

    except Exception as e:
        logger.error(f"Failed to fetch ticket {ticket_id}: {e!s}")
        return {
            "errors": [{"phase": "fetch_ticket", "message": str(e)}],
            "current_phase": "error",
        }


def triage(state: dict[str, Any]) -> dict[str, Any]:
    """Node: Run triage agent to categorize and assess ticket.

    Expects:
        state["ticket"]: Ticket data

    Updates:
        state["category"], state["subcategory"]: Categorization
        state["complexity"]: simple/moderate/complex
        state["suggested_assignee"], state["suggested_team"]: Assignment suggestion
        state["current_phase"]: "triaged"
    """
    from infrastructure_atlas.agents.workers.triage import TriageAgent
    from infrastructure_atlas.agents.workflow_agent import AgentConfig
    from infrastructure_atlas.skills.registry import get_skills_registry

    ticket = state.get("ticket")
    if not ticket:
        return {
            "errors": [{"phase": "triage", "message": "No ticket data available"}],
            "current_phase": "error",
        }

    # Create triage agent
    config = AgentConfig(
        name="Triage Agent",
        role="ticket categorization specialist",
        prompt_file="triage.md",
        model="claude-sonnet-4-5-20250929",
        temperature=0.3,  # Low temperature for consistent categorization
        tools=["jira", "confluence"],
    )

    registry = get_skills_registry()

    try:
        agent = TriageAgent(config, registry)
        result = agent.process(state)

        logger.info(
            f"Triaged ticket: {state.get('ticket_id')}",
            extra={
                "category": result.get("category"),
                "complexity": result.get("complexity"),
            },
        )

        return {
            **result,
            "current_phase": "triaged",
        }

    except Exception as e:
        logger.error(f"Triage failed: {e!s}")
        return {
            "errors": [{"phase": "triage", "message": str(e)}],
            "current_phase": "error",
        }


def enrich(state: dict[str, Any]) -> dict[str, Any]:
    """Node: Enrich ticket with customer context and SLA info.

    Expects:
        state["ticket"]: Ticket data

    Updates:
        state["customer_context"]: Customer information from CMDB
        state["current_phase"]: "enriched"
    """
    # TODO: Implement customer context lookup from NetBox/CMDB
    # For now, return minimal enrichment

    ticket = state.get("ticket", {})
    reporter = ticket.get("reporter", {})

    customer_context = {
        "reporter_name": reporter.get("display_name"),
        "reporter_email": reporter.get("email"),
        # These would come from CMDB lookup
        "department": None,
        "sla_tier": "standard",
        "vip_customer": False,
    }

    return {
        "customer_context": customer_context,
        "current_phase": "enriched",
    }


def investigate(state: dict[str, Any]) -> dict[str, Any]:
    """Node: Run engineer agent to investigate the issue.

    Expects:
        state["ticket"]: Ticket data
        state["category"]: Ticket category

    Updates:
        state["investigation"]: Investigation results
        state["investigation_plan"]: Steps taken/planned
        state["related_systems"]: Affected systems
        state["prepared_response"]: Draft customer response
        state["current_phase"]: "investigated"
    """
    from infrastructure_atlas.agents.workers.engineer import EngineerAgent
    from infrastructure_atlas.agents.workflow_agent import AgentConfig
    from infrastructure_atlas.skills.registry import get_skills_registry

    ticket = state.get("ticket")
    if not ticket:
        return {
            "errors": [{"phase": "investigate", "message": "No ticket data"}],
            "current_phase": "error",
        }

    config = AgentConfig(
        name="Engineer Agent",
        role="senior infrastructure engineer",
        prompt_file="engineer.md",
        model="claude-sonnet-4-5-20250929",
        temperature=0.5,
        tools=["jira", "zabbix", "netbox", "vcenter", "confluence"],
    )

    registry = get_skills_registry()

    try:
        agent = EngineerAgent(config, registry)
        result = agent.process(state)

        logger.info(f"Investigation complete for: {state.get('ticket_id')}")

        return {
            **result,
            "current_phase": "investigated",
        }

    except Exception as e:
        logger.error(f"Investigation failed: {e!s}")
        return {
            "errors": [{"phase": "investigate", "message": str(e)}],
            "current_phase": "error",
        }


def review(state: dict[str, Any]) -> dict[str, Any]:
    """Node: Run reviewer agent to validate decisions.

    Expects:
        state: Full workflow state

    Updates:
        state["decisions"]: Review decisions (approve/modify/reject)
        state["requires_human"]: Whether human approval needed
        state["human_prompt"]: Prompt for human if needed
        state["current_phase"]: "reviewed"
    """
    from infrastructure_atlas.agents.workers.reviewer import ReviewerAgent
    from infrastructure_atlas.agents.workflow_agent import AgentConfig
    from infrastructure_atlas.skills.registry import get_skills_registry

    config = AgentConfig(
        name="Reviewer Agent",
        role="quality assurance reviewer",
        prompt_file="reviewer.md",
        model="claude-sonnet-4-5-20250929",
        temperature=0.3,
        tools=["jira", "confluence"],
    )

    registry = get_skills_registry()

    try:
        agent = ReviewerAgent(config, registry)
        result = agent.process(state)

        # Determine if human approval is needed
        decisions = result.get("decisions", [])
        needs_human = any(d.get("requires_human", False) for d in decisions)

        logger.info(
            f"Review complete for: {state.get('ticket_id')}",
            extra={"requires_human": needs_human},
        )

        return {
            **result,
            "requires_human": needs_human,
            "human_prompt": result.get("human_prompt") if needs_human else None,
            "current_phase": "reviewed",
        }

    except Exception as e:
        logger.error(f"Review failed: {e!s}")
        return {
            "errors": [{"phase": "review", "message": str(e)}],
            "current_phase": "error",
        }


def wait_for_human(state: dict[str, Any]) -> dict[str, Any]:
    """Node: Checkpoint for human approval.

    This node is configured as an interrupt point - the workflow
    pauses here until resumed with human input.

    Expects:
        state["requires_human"]: True
        state["human_prompt"]: What to ask the human

    Updates:
        state["current_phase"]: "waiting_human"
    """
    logger.info(f"Waiting for human input on: {state.get('ticket_id')}")

    return {
        "current_phase": "waiting_human",
    }


def apply_actions(state: dict[str, Any]) -> dict[str, Any]:
    """Node: Apply approved actions.

    Expects:
        state["proposed_actions"]: Actions to apply
        state["human_response"]: Human approval/modifications

    Updates:
        state["actions_taken"]: Results of applied actions
        state["current_phase"]: "actions_applied"
    """
    from infrastructure_atlas.skills.registry import get_skills_registry

    human_response = state.get("human_response", {})
    approved = human_response.get("approved", False)

    if not approved:
        logger.info("Actions not approved by human")
        return {
            "current_phase": "actions_rejected",
        }

    proposed_actions = state.get("proposed_actions", [])
    actions_taken = []
    registry = get_skills_registry()

    for action in proposed_actions:
        skill_name = action.get("skill")
        action_name = action.get("action")
        params = action.get("params", {})

        skill = registry.get(skill_name)
        if not skill:
            actions_taken.append({
                **action,
                "status": "error",
                "error": f"Skill '{skill_name}' not found",
            })
            continue

        try:
            result = skill.execute(action_name, params)
            actions_taken.append({
                **action,
                "status": "success",
                "result": result,
            })
            logger.info(f"Applied action: {skill_name}.{action_name}")

        except Exception as e:
            actions_taken.append({
                **action,
                "status": "error",
                "error": str(e),
            })
            logger.error(f"Action failed: {skill_name}.{action_name}: {e!s}")

    return {
        "actions_taken": actions_taken,
        "current_phase": "actions_applied",
    }


def finalize(state: dict[str, Any]) -> dict[str, Any]:
    """Node: Generate final summary and documentation.

    Expects:
        state: Full workflow state

    Updates:
        state["summary"]: Execution summary
        state["documentation"]: Generated documentation
        state["current_phase"]: "completed"
    """
    ticket_id = state.get("ticket_id", "unknown")
    category = state.get("category", "unknown")
    complexity = state.get("complexity", "unknown")
    actions_taken = state.get("actions_taken", [])

    # Generate summary
    summary_parts = [
        f"Workflow completed for ticket: {ticket_id}",
        f"Category: {category}",
        f"Complexity: {complexity}",
        f"Actions taken: {len(actions_taken)}",
    ]

    errors = state.get("errors", [])
    if errors:
        summary_parts.append(f"Errors encountered: {len(errors)}")

    summary = "\n".join(summary_parts)

    logger.info(f"Finalized workflow for: {ticket_id}")

    return {
        "summary": summary,
        "current_phase": "completed",
    }


def should_investigate(state: dict[str, Any]) -> str:
    """Conditional edge: Determine if investigation is needed.

    Args:
        state: Current workflow state

    Returns:
        "investigate" if complex ticket, "review" if simple
    """
    complexity = state.get("complexity", "moderate")

    if complexity in ("moderate", "complex"):
        return "investigate"
    return "review"


def should_apply_or_end(state: dict[str, Any]) -> str:
    """Conditional edge: Determine next step after human input.

    Args:
        state: Current workflow state

    Returns:
        "apply_actions" if approved, "investigate" if modify, "end" if rejected
    """
    human_response = state.get("human_response", {})

    decision = human_response.get("decision", "reject")

    if decision == "approve":
        return "apply_actions"
    elif decision == "modify":
        return "investigate"
    else:
        return "end"
