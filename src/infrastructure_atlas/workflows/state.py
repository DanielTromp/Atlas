"""Workflow state definitions for LangGraph workflows.

This module defines TypedDict state schemas for different workflow types.
States are used by LangGraph to track workflow progress and enable
checkpointing, human-in-the-loop, and state persistence.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph.message import add_messages

from infrastructure_atlas.agents.workflow_agent import AgentMessage


def _merge_dicts(existing: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Merge two dicts, with new values overwriting existing."""
    return {**existing, **new}


def _append_list(existing: list[Any], new: list[Any]) -> list[Any]:
    """Append new items to existing list."""
    return existing + new


class WorkflowState(TypedDict, total=False):
    """Base workflow state shared by all workflows.

    This state is designed to be checkpoint-friendly and supports
    LangGraph's interrupt/resume functionality.

    Attributes:
        workflow_id: Unique identifier for the workflow definition
        execution_id: Unique identifier for this execution instance
        current_phase: Current phase/stage of the workflow
        trigger_type: How the workflow was triggered (manual, webhook, schedule, event)
        trigger_data: Raw trigger payload

        ticket: Full ticket data from source system
        ticket_id: Ticket identifier (e.g., ESD-1234)
        ticket_type: Type of ticket (incident, request, problem)
        priority: Ticket priority level

        investigation: Results of investigation analysis
        related_systems: List of affected/related systems
        related_tickets: List of similar/related tickets

        messages: Conversation history with agents (using add_messages reducer)
        decisions: Decisions made during workflow
        proposed_actions: Actions proposed by agents

        requires_human: Whether human intervention is needed
        human_prompt: Prompt to show human reviewer
        human_response: Human's response/decision

        summary: Final summary of workflow execution
        actions_taken: List of actions that were executed
        documentation: Generated documentation/notes

        errors: List of errors encountered
        retry_count: Number of retry attempts
    """

    # Identifiers
    workflow_id: str
    execution_id: str
    current_phase: str

    # Trigger info
    trigger_type: str
    trigger_data: dict[str, Any]

    # Ticket context
    ticket: dict[str, Any] | None
    ticket_id: str | None
    ticket_type: str | None
    priority: str | None

    # Investigation
    investigation: Annotated[dict[str, Any], _merge_dicts]
    related_systems: Annotated[list[dict[str, Any]], _append_list]
    related_tickets: Annotated[list[dict[str, Any]], _append_list]

    # Conversation (uses LangGraph's message reducer)
    messages: Annotated[list[AgentMessage], add_messages]

    # Decisions and actions
    decisions: Annotated[list[dict[str, Any]], _append_list]
    proposed_actions: Annotated[list[dict[str, Any]], _append_list]

    # Human-in-the-loop
    requires_human: bool
    human_prompt: str | None
    human_response: dict[str, Any] | None

    # Results
    summary: str | None
    actions_taken: Annotated[list[dict[str, Any]], _append_list]
    documentation: str | None

    # Error handling
    errors: Annotated[list[dict[str, Any]], _append_list]
    retry_count: int


class ESDTriageState(WorkflowState, total=False):
    """Extended state for ESD (Enterprise Service Desk) triage workflow.

    This workflow handles incoming support tickets by:
    1. Fetching ticket details
    2. Categorizing and assessing complexity
    3. Finding similar tickets and documentation
    4. Investigating if needed
    5. Preparing response and suggesting assignee
    6. Reviewing before execution

    Additional attributes specific to ESD triage:
        category: Primary ticket category
        subcategory: Secondary category
        complexity: Assessed complexity level
        estimated_effort: Estimated time to resolve
        suggested_assignee: Recommended assignee username
        suggested_team: Recommended team
        customer_context: Customer information from CMDB
        similar_tickets: Similar resolved tickets
        relevant_documentation: Related KB articles
        investigation_plan: Steps for investigation
        prepared_response: Draft customer response
    """

    # Categorization
    category: str | None
    subcategory: str | None
    complexity: Literal["simple", "moderate", "complex"] | None
    estimated_effort: str | None

    # Assignment
    suggested_assignee: str | None
    suggested_team: str | None

    # Context enrichment
    customer_context: dict[str, Any] | None
    similar_tickets: Annotated[list[dict[str, Any]], _append_list]
    relevant_documentation: Annotated[list[dict[str, Any]], _append_list]

    # Investigation
    investigation_plan: str | None
    prepared_response: str | None


def create_initial_state(
    workflow_id: str,
    execution_id: str,
    trigger_type: str,
    trigger_data: dict[str, Any] | None = None,
) -> WorkflowState:
    """Create an initial workflow state with default values.

    Args:
        workflow_id: ID of the workflow definition
        execution_id: ID for this execution
        trigger_type: How workflow was triggered
        trigger_data: Optional trigger payload

    Returns:
        Initialized WorkflowState
    """
    return WorkflowState(
        workflow_id=workflow_id,
        execution_id=execution_id,
        current_phase="init",
        trigger_type=trigger_type,
        trigger_data=trigger_data or {},
        ticket=None,
        ticket_id=None,
        ticket_type=None,
        priority=None,
        investigation={},
        related_systems=[],
        related_tickets=[],
        messages=[],
        decisions=[],
        proposed_actions=[],
        requires_human=False,
        human_prompt=None,
        human_response=None,
        summary=None,
        actions_taken=[],
        documentation=None,
        errors=[],
        retry_count=0,
    )


def create_esd_triage_state(
    workflow_id: str,
    execution_id: str,
    trigger_type: str,
    trigger_data: dict[str, Any] | None = None,
    ticket_id: str | None = None,
) -> ESDTriageState:
    """Create an initial ESD triage workflow state.

    Args:
        workflow_id: ID of the workflow definition
        execution_id: ID for this execution
        trigger_type: How workflow was triggered
        trigger_data: Optional trigger payload
        ticket_id: Optional ticket ID to process

    Returns:
        Initialized ESDTriageState
    """
    base_state = create_initial_state(workflow_id, execution_id, trigger_type, trigger_data)

    return ESDTriageState(
        **base_state,
        ticket_id=ticket_id,
        category=None,
        subcategory=None,
        complexity=None,
        estimated_effort=None,
        suggested_assignee=None,
        suggested_team=None,
        customer_context=None,
        similar_tickets=[],
        relevant_documentation=[],
        investigation_plan=None,
        prepared_response=None,
    )
