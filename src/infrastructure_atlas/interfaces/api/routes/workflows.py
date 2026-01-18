"""Workflow API routes - workflow management and execution.

Provides endpoints for:
- Listing and managing workflow definitions
- Starting workflow executions
- Checking execution status
- Handling human interventions
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from infrastructure_atlas.db.models import (
    Workflow,
    WorkflowExecution,
)
from infrastructure_atlas.infrastructure.logging import get_logger
from infrastructure_atlas.interfaces.api.dependencies import DbSessionDep

router = APIRouter(prefix="/workflows", tags=["workflows"])
logger = get_logger(__name__)


# ============================================================================
# Pydantic Models
# ============================================================================


class WorkflowCreate(BaseModel):
    """Request model for creating a workflow."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    trigger_type: str = Field(..., pattern="^(manual|webhook|schedule|event)$")
    trigger_config: dict[str, Any] | None = None
    graph_definition: dict[str, Any]
    visual_definition: dict[str, Any]


class WorkflowUpdate(BaseModel):
    """Request model for updating a workflow."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    trigger_type: str | None = Field(None, pattern="^(manual|webhook|schedule|event)$")
    trigger_config: dict[str, Any] | None = None
    graph_definition: dict[str, Any] | None = None
    visual_definition: dict[str, Any] | None = None
    is_active: bool | None = None


class WorkflowExecuteRequest(BaseModel):
    """Request model for starting a workflow execution."""

    trigger_data: dict[str, Any] | None = None
    initial_state: dict[str, Any] | None = None


class WorkflowResponse(BaseModel):
    """Response model for a workflow."""

    id: str
    name: str
    description: str | None
    trigger_type: str
    trigger_config: dict[str, Any] | None
    graph_definition: dict[str, Any]
    visual_definition: dict[str, Any]
    version: int
    is_active: bool
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


class ExecutionResponse(BaseModel):
    """Response model for a workflow execution."""

    id: str
    workflow_id: str
    status: str
    trigger_data: dict[str, Any] | None
    current_node: str | None
    started_at: str
    completed_at: str | None
    error_message: str | None

    class Config:
        from_attributes = True


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


def workflow_to_response(workflow: Workflow) -> dict[str, Any]:
    """Convert a Workflow model to response dict."""
    return {
        "id": workflow.id,
        "name": workflow.name,
        "description": workflow.description,
        "trigger_type": workflow.trigger_type,
        "trigger_config": workflow.trigger_config,
        "graph_definition": workflow.graph_definition,
        "visual_definition": workflow.visual_definition,
        "version": workflow.version,
        "is_active": workflow.is_active,
        "created_at": workflow.created_at.isoformat() if workflow.created_at else None,
        "updated_at": workflow.updated_at.isoformat() if workflow.updated_at else None,
    }


def execution_to_response(execution: WorkflowExecution) -> dict[str, Any]:
    """Convert a WorkflowExecution model to response dict."""
    return {
        "id": execution.id,
        "workflow_id": execution.workflow_id,
        "status": execution.status,
        "trigger_data": execution.trigger_data,
        "current_node": execution.current_node,
        "started_at": execution.started_at.isoformat() if execution.started_at else None,
        "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
        "error_message": execution.error_message,
    }


# ============================================================================
# Workflow CRUD Routes
# ============================================================================


@router.get("")
def list_workflows(
    request: Request,
    session: DbSessionDep,
    is_active: bool | None = None,
    trigger_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """List all workflows with optional filtering."""
    require_permission(request, "workflows.read")

    query = select(Workflow)

    if is_active is not None:
        query = query.where(Workflow.is_active == is_active)
    if trigger_type:
        query = query.where(Workflow.trigger_type == trigger_type)

    query = query.order_by(Workflow.name).offset(offset).limit(limit)

    workflows = session.execute(query).scalars().all()

    return {
        "workflows": [workflow_to_response(w) for w in workflows],
        "count": len(workflows),
        "offset": offset,
        "limit": limit,
    }


@router.post("")
def create_workflow(
    request: Request,
    session: DbSessionDep,
    body: WorkflowCreate,
) -> dict[str, Any]:
    """Create a new workflow definition."""
    require_permission(request, "workflows.write")

    # Check for duplicate name
    existing = session.execute(
        select(Workflow).where(Workflow.name == body.name)
    ).scalar_one_or_none()

    if existing:
        raise HTTPException(status_code=409, detail=f"Workflow '{body.name}' already exists")

    workflow = Workflow(
        id=str(uuid4()),
        name=body.name,
        description=body.description,
        trigger_type=body.trigger_type,
        trigger_config=body.trigger_config,
        graph_definition=body.graph_definition,
        visual_definition=body.visual_definition,
        version=1,
        is_active=True,
    )

    session.add(workflow)
    session.commit()
    session.refresh(workflow)

    logger.info(f"Created workflow: {workflow.name}", extra={"workflow_id": workflow.id})

    return workflow_to_response(workflow)


@router.get("/{workflow_id}")
def get_workflow(
    request: Request,
    session: DbSessionDep,
    workflow_id: str,
) -> dict[str, Any]:
    """Get a specific workflow by ID."""
    require_permission(request, "workflows.read")

    workflow = session.get(Workflow, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    return workflow_to_response(workflow)


@router.put("/{workflow_id}")
def update_workflow(
    request: Request,
    session: DbSessionDep,
    workflow_id: str,
    body: WorkflowUpdate,
) -> dict[str, Any]:
    """Update a workflow definition."""
    require_permission(request, "workflows.write")

    workflow = session.get(Workflow, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Update fields if provided
    if body.name is not None:
        # Check for duplicate name
        existing = session.execute(
            select(Workflow).where(Workflow.name == body.name, Workflow.id != workflow_id)
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail=f"Workflow '{body.name}' already exists")
        workflow.name = body.name

    if body.description is not None:
        workflow.description = body.description
    if body.trigger_type is not None:
        workflow.trigger_type = body.trigger_type
    if body.trigger_config is not None:
        workflow.trigger_config = body.trigger_config
    if body.graph_definition is not None:
        workflow.graph_definition = body.graph_definition
        workflow.version += 1  # Increment version on graph change
    if body.visual_definition is not None:
        workflow.visual_definition = body.visual_definition
    if body.is_active is not None:
        workflow.is_active = body.is_active

    session.commit()
    session.refresh(workflow)

    logger.info(f"Updated workflow: {workflow.name}", extra={"workflow_id": workflow.id})

    return workflow_to_response(workflow)


@router.delete("/{workflow_id}")
def delete_workflow(
    request: Request,
    session: DbSessionDep,
    workflow_id: str,
) -> dict[str, Any]:
    """Delete a workflow definition."""
    require_permission(request, "workflows.write")

    workflow = session.get(Workflow, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Check for active executions
    active_executions = session.execute(
        select(WorkflowExecution).where(
            WorkflowExecution.workflow_id == workflow_id,
            WorkflowExecution.status.in_(["running", "paused", "waiting_human"]),
        )
    ).scalars().all()

    if active_executions:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete workflow with {len(active_executions)} active executions",
        )

    session.delete(workflow)
    session.commit()

    logger.info(f"Deleted workflow: {workflow.name}", extra={"workflow_id": workflow_id})

    return {"success": True, "message": f"Workflow '{workflow.name}' deleted"}


# ============================================================================
# Workflow Execution Routes
# ============================================================================


@router.post("/{workflow_id}/execute")
def execute_workflow(
    request: Request,
    session: DbSessionDep,
    workflow_id: str,
    body: WorkflowExecuteRequest,
) -> dict[str, Any]:
    """Start a new workflow execution."""
    require_permission(request, "workflows.execute")

    workflow = session.get(Workflow, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    if not workflow.is_active:
        raise HTTPException(status_code=400, detail="Workflow is not active")

    # Create execution record
    execution = WorkflowExecution(
        id=str(uuid4()),
        workflow_id=workflow_id,
        status="running",
        trigger_data=body.trigger_data,
        current_state=body.initial_state,
        current_node=None,
        started_at=datetime.now(UTC),
    )

    session.add(execution)
    session.commit()
    session.refresh(execution)

    logger.info(
        f"Started workflow execution: {workflow.name}",
        extra={
            "workflow_id": workflow_id,
            "execution_id": execution.id,
        },
    )

    # TODO: Actually run the workflow asynchronously
    # For now, just return the execution record
    # In production, this would dispatch to a background worker

    return {
        "execution": execution_to_response(execution),
        "message": "Workflow execution started",
    }


@router.get("/{workflow_id}/executions")
def list_workflow_executions(
    request: Request,
    session: DbSessionDep,
    workflow_id: str,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """List executions for a specific workflow."""
    require_permission(request, "workflows.read")

    workflow = session.get(Workflow, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    query = select(WorkflowExecution).where(WorkflowExecution.workflow_id == workflow_id)

    if status:
        query = query.where(WorkflowExecution.status == status)

    query = query.order_by(WorkflowExecution.started_at.desc()).offset(offset).limit(limit)

    executions = session.execute(query).scalars().all()

    return {
        "executions": [execution_to_response(e) for e in executions],
        "count": len(executions),
        "workflow_id": workflow_id,
        "offset": offset,
        "limit": limit,
    }


__all__ = ["router"]
