"""ESD Triage Workflow Definition.

This workflow handles incoming ESD (Enterprise Service Desk) tickets by:
1. Fetching ticket details from Jira
2. Categorizing and assessing complexity
3. Finding similar tickets and documentation
4. Investigating if needed (for moderate/complex tickets)
5. Preparing response and suggesting assignee
6. Reviewing before execution
7. Applying approved actions

The workflow supports human-in-the-loop at the review stage.
"""

from __future__ import annotations

from typing import Any

from infrastructure_atlas.infrastructure.logging import get_logger
from infrastructure_atlas.workflows.engine import WorkflowEngine
from infrastructure_atlas.workflows.nodes import (
    apply_actions,
    enrich,
    fetch_ticket,
    finalize,
    investigate,
    review,
    should_apply_or_end,
    should_investigate,
    triage,
    wait_for_human,
)

logger = get_logger(__name__)


def create_esd_triage_workflow(engine: WorkflowEngine) -> str:
    """Create and compile the ESD Triage workflow.

    This registers all necessary nodes with the engine and compiles
    the workflow graph.

    Args:
        engine: WorkflowEngine instance

    Returns:
        Workflow ID
    """
    workflow_id = "esd_triage_v1"

    # Register all nodes
    engine.register_node("fetch_ticket", fetch_ticket)
    engine.register_node("triage", triage)
    engine.register_node("enrich", enrich)
    engine.register_node("investigate", investigate)
    engine.register_node("review", review)
    engine.register_node("wait_for_human", wait_for_human)
    engine.register_node("apply_actions", apply_actions)
    engine.register_node("finalize", finalize)

    # Define edges
    # Linear flow: fetch_ticket -> triage -> enrich
    edges = [
        ("fetch_ticket", "triage"),
        ("triage", "enrich"),
        # Review always goes to wait_for_human
        ("review", "wait_for_human"),
        # After actions, always finalize
        ("apply_actions", "finalize"),
        ("finalize", "END"),
    ]

    # Conditional edges
    conditional_edges = [
        # After enrich: investigate if complex, otherwise straight to review
        ("enrich", should_investigate, {
            "investigate": "investigate",
            "review": "review",
        }),
        # After investigate, go to review
        ("investigate", lambda _: "review", {
            "review": "review",
        }),
        # After human input: apply, modify (re-investigate), or end
        ("wait_for_human", should_apply_or_end, {
            "apply_actions": "apply_actions",
            "investigate": "investigate",
            "end": "END",
        }),
    ]

    # Compile with interrupt before wait_for_human
    engine.compile_workflow(
        workflow_id=workflow_id,
        nodes=[
            "fetch_ticket",
            "triage",
            "enrich",
            "investigate",
            "review",
            "wait_for_human",
            "apply_actions",
            "finalize",
        ],
        edges=edges,
        conditional_edges=conditional_edges,
        interrupt_before=["wait_for_human"],
    )

    logger.info(f"Compiled ESD Triage workflow: {workflow_id}")
    return workflow_id


def run_esd_triage(
    ticket_id: str,
    trigger_type: str = "manual",
    trigger_data: dict[str, Any] | None = None,
    db_session: Any | None = None,
) -> str:
    """Convenience function to run the ESD Triage workflow.

    Args:
        ticket_id: Jira ticket ID (e.g., "ESD-1234")
        trigger_type: How the workflow was triggered
        trigger_data: Additional trigger payload
        db_session: Optional database session

    Returns:
        Execution ID
    """
    from infrastructure_atlas.skills.registry import get_skills_registry
    from infrastructure_atlas.workflows.engine import create_workflow_engine

    # Initialize skills
    registry = get_skills_registry()
    registry.load_config()

    # Load and initialize Jira skill
    from infrastructure_atlas.skills.jira.skill import JiraSkill
    jira = JiraSkill()
    jira.initialize()
    registry.register(jira)

    # Create engine and workflow
    engine = create_workflow_engine(db_session)
    workflow_id = create_esd_triage_workflow(engine)

    # Prepare initial state
    initial_state = {
        "ticket_id": ticket_id,
    }

    if trigger_data:
        initial_state.update(trigger_data)

    # Execute workflow
    execution_id = engine.execute(
        workflow_id=workflow_id,
        trigger_type=trigger_type,
        trigger_data=trigger_data or {"ticket_id": ticket_id},
        initial_state=initial_state,
    )

    return execution_id


# Visual workflow definition for React Flow UI
VISUAL_DEFINITION = {
    "nodes": [
        {"id": "fetch_ticket", "type": "action", "position": {"x": 250, "y": 0}, "data": {"label": "Fetch Ticket"}},
        {"id": "triage", "type": "agent", "position": {"x": 250, "y": 100}, "data": {"label": "Triage Agent"}},
        {"id": "enrich", "type": "action", "position": {"x": 250, "y": 200}, "data": {"label": "Enrich Context"}},
        {"id": "investigate", "type": "agent", "position": {"x": 400, "y": 300}, "data": {"label": "Engineer Agent"}},
        {"id": "review", "type": "agent", "position": {"x": 250, "y": 400}, "data": {"label": "Reviewer Agent"}},
        {"id": "wait_for_human", "type": "human", "position": {"x": 250, "y": 500}, "data": {"label": "Human Review"}},
        {"id": "apply_actions", "type": "action", "position": {"x": 100, "y": 600}, "data": {"label": "Apply Actions"}},
        {"id": "finalize", "type": "action", "position": {"x": 100, "y": 700}, "data": {"label": "Finalize"}},
    ],
    "edges": [
        {"id": "e1", "source": "fetch_ticket", "target": "triage"},
        {"id": "e2", "source": "triage", "target": "enrich"},
        {"id": "e3", "source": "enrich", "target": "investigate", "label": "complex"},
        {"id": "e4", "source": "enrich", "target": "review", "label": "simple"},
        {"id": "e5", "source": "investigate", "target": "review"},
        {"id": "e6", "source": "review", "target": "wait_for_human"},
        {"id": "e7", "source": "wait_for_human", "target": "apply_actions", "label": "approve"},
        {"id": "e8", "source": "wait_for_human", "target": "investigate", "label": "modify"},
        {"id": "e9", "source": "apply_actions", "target": "finalize"},
    ],
}


# Graph definition for LangGraph (JSON-serializable)
GRAPH_DEFINITION = {
    "name": "esd_triage_v1",
    "description": "ESD ticket triage and initial response workflow",
    "nodes": [
        "fetch_ticket",
        "triage",
        "enrich",
        "investigate",
        "review",
        "wait_for_human",
        "apply_actions",
        "finalize",
    ],
    "edges": [
        ["fetch_ticket", "triage"],
        ["triage", "enrich"],
        ["review", "wait_for_human"],
        ["apply_actions", "finalize"],
        ["finalize", "END"],
    ],
    "conditional_edges": [
        {
            "source": "enrich",
            "condition": "should_investigate",
            "paths": {"investigate": "investigate", "review": "review"},
        },
        {
            "source": "investigate",
            "condition": "always_review",
            "paths": {"review": "review"},
        },
        {
            "source": "wait_for_human",
            "condition": "should_apply_or_end",
            "paths": {"apply_actions": "apply_actions", "investigate": "investigate", "end": "END"},
        },
    ],
    "interrupt_before": ["wait_for_human"],
    "state_schema": "ESDTriageState",
}
