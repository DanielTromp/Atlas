"""Execution API routes - workflow execution management.

Provides endpoints for:
- Getting execution details and status
- Listing execution steps
- Resuming paused executions with human input
- Canceling running executions
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from infrastructure_atlas.db.models import (
    ExecutionStep,
    HumanIntervention,
    WorkflowExecution,
)
from infrastructure_atlas.infrastructure.logging import get_logger
from infrastructure_atlas.interfaces.api.dependencies import DbSessionDep

router = APIRouter(prefix="/executions", tags=["executions"])
logger = get_logger(__name__)


# ============================================================================
# Pydantic Models
# ============================================================================


class ResumeExecutionRequest(BaseModel):
    """Request model for resuming a paused execution."""

    decision: str = Field(..., pattern="^(approve|modify|reject)$")
    feedback: str | None = None
    modifications: dict[str, Any] | None = None


class ExecutionDetailResponse(BaseModel):
    """Detailed response model for an execution."""

    id: str
    workflow_id: str
    status: str
    trigger_data: dict[str, Any] | None
    current_state: dict[str, Any] | None
    current_node: str | None
    started_at: str
    completed_at: str | None
    error_message: str | None
    steps: list[dict[str, Any]]
    pending_intervention: dict[str, Any] | None


class StepResponse(BaseModel):
    """Response model for an execution step."""

    id: str
    execution_id: str
    node_id: str
    node_type: str
    status: str
    input_data: dict[str, Any] | None
    output_data: dict[str, Any] | None
    tokens_used: int | None
    duration_ms: int | None
    error_message: str | None
    created_at: str


# ============================================================================
# Helper Functions
# ============================================================================


def require_permission(request: Request, permission: str) -> None:
    """Require user to have a specific permission."""
    user = getattr(request.state, "user", None)
    if user is None:
        return
    if getattr(user, "role", "") == "admin":
        return
    permissions = getattr(request.state, "permissions", frozenset())
    if permission not in permissions:
        raise HTTPException(status_code=403, detail="Forbidden: missing permission")


def step_to_response(step: ExecutionStep) -> dict[str, Any]:
    """Convert an ExecutionStep model to response dict."""
    return {
        "id": step.id,
        "execution_id": step.execution_id,
        "node_id": step.node_id,
        "node_type": step.node_type,
        "status": step.status,
        "input_data": step.input_data,
        "output_data": step.output_data,
        "tokens_used": step.tokens_used,
        "duration_ms": step.duration_ms,
        "error_message": step.error_message,
        "created_at": step.created_at.isoformat() if step.created_at else None,
    }


def intervention_to_response(intervention: HumanIntervention) -> dict[str, Any]:
    """Convert a HumanIntervention model to response dict."""
    return {
        "id": intervention.id,
        "execution_id": intervention.execution_id,
        "step_id": intervention.step_id,
        "intervention_type": intervention.intervention_type,
        "prompt": intervention.prompt,
        "options": intervention.options,
        "assigned_to": intervention.assigned_to,
        "response": intervention.response,
        "responded_at": intervention.responded_at.isoformat() if intervention.responded_at else None,
        "created_at": intervention.created_at.isoformat() if intervention.created_at else None,
    }


# ============================================================================
# Execution Routes
# ============================================================================


@router.get("")
def list_executions(
    request: Request,
    session: DbSessionDep,
    workflow_id: str | None = None,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """List all workflow executions with optional filtering."""
    require_permission(request, "workflows.read")

    query = select(WorkflowExecution)

    if workflow_id:
        query = query.where(WorkflowExecution.workflow_id == workflow_id)
    if status:
        query = query.where(WorkflowExecution.status == status)

    query = query.order_by(WorkflowExecution.started_at.desc()).offset(offset).limit(limit)

    executions = session.execute(query).scalars().all()

    return {
        "executions": [
            {
                "id": e.id,
                "workflow_id": e.workflow_id,
                "status": e.status,
                "current_node": e.current_node,
                "started_at": e.started_at.isoformat() if e.started_at else None,
                "completed_at": e.completed_at.isoformat() if e.completed_at else None,
            }
            for e in executions
        ],
        "count": len(executions),
        "offset": offset,
        "limit": limit,
    }


@router.get("/{execution_id}")
def get_execution(
    request: Request,
    session: DbSessionDep,
    execution_id: str,
) -> dict[str, Any]:
    """Get detailed execution information including steps."""
    require_permission(request, "workflows.read")

    execution = session.get(WorkflowExecution, execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")

    # Get steps
    steps = session.execute(
        select(ExecutionStep)
        .where(ExecutionStep.execution_id == execution_id)
        .order_by(ExecutionStep.created_at)
    ).scalars().all()

    # Get pending intervention if waiting for human
    pending_intervention = None
    if execution.status == "waiting_human":
        intervention = session.execute(
            select(HumanIntervention)
            .where(
                HumanIntervention.execution_id == execution_id,
                HumanIntervention.response.is_(None),
            )
            .order_by(HumanIntervention.created_at.desc())
        ).scalar()

        if intervention:
            pending_intervention = intervention_to_response(intervention)

    return {
        "id": execution.id,
        "workflow_id": execution.workflow_id,
        "status": execution.status,
        "trigger_data": execution.trigger_data,
        "current_state": execution.current_state,
        "current_node": execution.current_node,
        "started_at": execution.started_at.isoformat() if execution.started_at else None,
        "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
        "error_message": execution.error_message,
        "steps": [step_to_response(s) for s in steps],
        "pending_intervention": pending_intervention,
    }


@router.get("/{execution_id}/steps")
def get_execution_steps(
    request: Request,
    session: DbSessionDep,
    execution_id: str,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Get all steps for an execution."""
    require_permission(request, "workflows.read")

    execution = session.get(WorkflowExecution, execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")

    steps = session.execute(
        select(ExecutionStep)
        .where(ExecutionStep.execution_id == execution_id)
        .order_by(ExecutionStep.created_at)
        .offset(offset)
        .limit(limit)
    ).scalars().all()

    return {
        "steps": [step_to_response(s) for s in steps],
        "count": len(steps),
        "execution_id": execution_id,
        "offset": offset,
        "limit": limit,
    }


@router.get("/{execution_id}/state")
def get_execution_state(
    request: Request,
    session: DbSessionDep,
    execution_id: str,
) -> dict[str, Any]:
    """Get the current state snapshot of an execution."""
    require_permission(request, "workflows.read")

    execution = session.get(WorkflowExecution, execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")

    return {
        "execution_id": execution_id,
        "status": execution.status,
        "current_node": execution.current_node,
        "state": execution.current_state or {},
    }


@router.post("/{execution_id}/resume")
def resume_execution(
    request: Request,
    session: DbSessionDep,
    execution_id: str,
    body: ResumeExecutionRequest,
) -> dict[str, Any]:
    """Resume a paused execution with human input."""
    require_permission(request, "workflows.execute")

    execution = session.get(WorkflowExecution, execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")

    if execution.status != "waiting_human":
        raise HTTPException(
            status_code=400,
            detail=f"Execution is not waiting for human input (status: {execution.status})",
        )

    # Find the pending intervention
    intervention = session.execute(
        select(HumanIntervention)
        .where(
            HumanIntervention.execution_id == execution_id,
            HumanIntervention.response.is_(None),
        )
        .order_by(HumanIntervention.created_at.desc())
    ).scalar()

    if intervention:
        # Record the human response
        intervention.response = {
            "decision": body.decision,
            "feedback": body.feedback,
            "modifications": body.modifications,
        }
        intervention.responded_at = datetime.now(UTC)

    # Update execution state with human response
    current_state = execution.current_state or {}
    current_state["human_response"] = {
        "decision": body.decision,
        "feedback": body.feedback,
        "modifications": body.modifications,
        "approved": body.decision == "approve",
    }
    execution.current_state = current_state

    # Update status based on decision
    if body.decision == "reject":
        execution.status = "completed"
        execution.completed_at = datetime.now(UTC)
    else:
        execution.status = "running"

    session.commit()
    session.refresh(execution)

    logger.info(
        f"Resumed execution with decision: {body.decision}",
        extra={
            "execution_id": execution_id,
            "decision": body.decision,
        },
    )

    # TODO: Dispatch continuation to background worker

    return {
        "execution_id": execution_id,
        "status": execution.status,
        "decision": body.decision,
        "message": f"Execution {'completed' if body.decision == 'reject' else 'resumed'}",
    }


@router.post("/{execution_id}/cancel")
def cancel_execution(
    request: Request,
    session: DbSessionDep,
    execution_id: str,
) -> dict[str, Any]:
    """Cancel a running or paused execution."""
    require_permission(request, "workflows.execute")

    execution = session.get(WorkflowExecution, execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")

    if execution.status in ("completed", "failed"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel execution in status: {execution.status}",
        )

    execution.status = "failed"
    execution.error_message = "Cancelled by user"
    execution.completed_at = datetime.now(UTC)

    session.commit()

    logger.info(f"Cancelled execution: {execution_id}")

    return {
        "execution_id": execution_id,
        "status": "failed",
        "message": "Execution cancelled",
    }


@router.get("/{execution_id}/interventions")
def get_execution_interventions(
    request: Request,
    session: DbSessionDep,
    execution_id: str,
) -> dict[str, Any]:
    """Get all human interventions for an execution."""
    require_permission(request, "workflows.read")

    execution = session.get(WorkflowExecution, execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")

    interventions = session.execute(
        select(HumanIntervention)
        .where(HumanIntervention.execution_id == execution_id)
        .order_by(HumanIntervention.created_at)
    ).scalars().all()

    return {
        "interventions": [intervention_to_response(i) for i in interventions],
        "count": len(interventions),
        "execution_id": execution_id,
    }


__all__ = ["router"]
