"""Agent Playground API routes for direct agent testing.

This module provides REST API endpoints for the Agent Playground UI:
- Agent management and configuration
- Direct chat with agents
- Skill testing
- Session management
- Configuration presets
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from infrastructure_atlas.agents.playground import (
    AVAILABLE_AGENTS,
    ChatEventType,
    PlaygroundRuntime,
)
from infrastructure_atlas.db.models import PlaygroundPreset, User
from infrastructure_atlas.db.models import PlaygroundSession as DBSession
from infrastructure_atlas.infrastructure.logging import get_logger
from infrastructure_atlas.skills import get_skills_registry

logger = get_logger(__name__)

router = APIRouter(prefix="/playground", tags=["playground"])


# Lazy imports to avoid circular dependencies
def get_db_session() -> Session:
    from infrastructure_atlas.api.app import SessionLocal

    return SessionLocal()


def get_current_user(request: Request) -> User | None:
    """Get current user from request state."""
    return getattr(request.state, "user", None)


def require_playground_permission(request: Request) -> None:
    """Require playground.use permission."""
    from infrastructure_atlas.api.app import require_permission

    require_permission(request, "playground.use")


def get_playground_runtime(db: Session | None = None) -> PlaygroundRuntime:
    """Get a PlaygroundRuntime instance."""
    registry = get_skills_registry()
    return PlaygroundRuntime(registry, db)


# ============================================================================
# Pydantic Request/Response Models
# ============================================================================


class AgentConfigUpdate(BaseModel):
    """Configuration update for an agent."""

    model: str | None = None
    temperature: float | None = Field(None, ge=0.0, le=1.0)
    max_tokens: int | None = Field(None, ge=100, le=8192)
    skills: list[str] | None = None
    system_prompt_override: str | None = None


class ChatRequest(BaseModel):
    """Request for agent chat."""

    message: str
    session_id: str | None = None
    state: dict[str, Any] | None = None
    stream: bool = True
    config_override: AgentConfigUpdate | None = None


class ChatResponse(BaseModel):
    """Response from agent chat (non-streaming)."""

    session_id: str
    agent_id: str
    response: str
    tokens: int
    cost_usd: float
    duration_ms: int
    tool_calls: list[dict[str, Any]] = []


class SkillExecuteRequest(BaseModel):
    """Request to execute a skill action."""

    # Parameters are passed as the body content
    pass


class PresetCreateRequest(BaseModel):
    """Request to create a configuration preset."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    agent_id: str
    config: dict[str, Any]
    is_shared: bool = False


class SessionResponse(BaseModel):
    """Response containing session data."""

    session_id: str
    agent_id: str
    messages: list[dict[str, Any]]
    state: dict[str, Any]
    config_override: dict[str, Any]
    total_tokens: int
    total_cost_usd: float
    created_at: str
    updated_at: str


# ============================================================================
# Agent Endpoints
# ============================================================================


@router.get("/agents")
def list_agents(request: Request) -> list[dict[str, Any]]:
    """List all available agents with their configurations."""
    require_playground_permission(request)

    return [agent.to_dict() for agent in AVAILABLE_AGENTS.values()]


@router.get("/agents/{agent_id}")
def get_agent(agent_id: str, request: Request) -> dict[str, Any]:
    """Get details about a specific agent."""
    require_playground_permission(request)

    agent = AVAILABLE_AGENTS.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    return agent.to_dict()


@router.post("/agents/{agent_id}/chat", response_model=None)
async def chat_with_agent(
    agent_id: str,
    request: Request,
    body: ChatRequest = Body(...),  # noqa: B008
):
    """Send a message directly to an agent.

    Supports streaming responses via Server-Sent Events (SSE).
    Returns either a StreamingResponse (SSE) or ChatResponse (JSON).
    """
    require_playground_permission(request)

    if agent_id not in AVAILABLE_AGENTS:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    db = get_db_session()

    try:
        runtime = get_playground_runtime(db)

        # Build config override from request
        config_override = None
        if body.config_override:
            config_override = body.config_override.model_dump(exclude_none=True)

        if body.stream:
            # Streaming response via SSE
            async def event_generator():
                tool_calls = []
                try:
                    async for event in runtime.chat(
                        agent_id=agent_id,
                        message=body.message,
                        session_id=body.session_id,
                        state=body.state,
                        config_override=config_override,
                        stream=True,
                    ):
                        if event.type == ChatEventType.TOOL_START:
                            tool_calls.append(event.data)

                        yield f"data: {json.dumps(event.to_dict(), default=str)}\n\n"

                except Exception as e:
                    logger.error(f"Streaming error: {e!s}")
                    error_event = {"type": "error", "data": {"error": str(e)}}
                    yield f"data: {json.dumps(error_event)}\n\n"

            return StreamingResponse(
                event_generator(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        else:
            # Non-streaming response
            response_content = ""
            tool_calls = []
            tokens = 0
            cost_usd = 0.0
            duration_ms = 0
            session_id = body.session_id or str(uuid.uuid4())

            async for event in runtime.chat(
                agent_id=agent_id,
                message=body.message,
                session_id=session_id,
                state=body.state,
                config_override=config_override,
                stream=False,
            ):
                if event.type == ChatEventType.MESSAGE_DELTA:
                    response_content = event.data.get("content", "")
                elif event.type == ChatEventType.TOOL_END:
                    tool_calls.append(event.data)
                elif event.type == ChatEventType.MESSAGE_END:
                    tokens = event.data.get("tokens", 0)
                    cost_usd = event.data.get("cost_usd", 0.0)
                    duration_ms = event.data.get("duration_ms", 0)
                elif event.type == ChatEventType.MESSAGE_START:
                    session_id = event.data.get("session_id", session_id)
                elif event.type == ChatEventType.ERROR:
                    raise HTTPException(status_code=500, detail=event.data.get("error"))

            return ChatResponse(
                session_id=session_id,
                agent_id=agent_id,
                response=response_content,
                tokens=tokens,
                cost_usd=cost_usd,
                duration_ms=duration_ms,
                tool_calls=tool_calls,
            )

    finally:
        db.close()


@router.post("/agents/{agent_id}/reset")
def reset_agent_session(
    agent_id: str,
    request: Request,
    session_id: str = Query(..., description="Session ID to reset"),
) -> dict[str, str]:
    """Reset an agent's session state and conversation."""
    require_playground_permission(request)

    db = get_db_session()
    try:
        runtime = get_playground_runtime(db)
        session = runtime.get_session(session_id)

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        session.clear()
        runtime._save_session_to_db(session)

        return {"status": "ok", "message": "Session reset successfully"}

    finally:
        db.close()


# ============================================================================
# Skill Endpoints
# ============================================================================


@router.get("/skills")
def list_skills(request: Request) -> list[dict[str, Any]]:
    """List all available skills with their actions."""
    require_playground_permission(request)

    registry = get_skills_registry()
    return registry.list_skills()


@router.get("/skills/{skill_name}")
def get_skill(skill_name: str, request: Request) -> dict[str, Any]:
    """Get details about a specific skill including action schemas."""
    require_playground_permission(request)

    registry = get_skills_registry()
    skill = registry.get(skill_name)

    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")

    return {
        "name": skill.name,
        "category": skill.category,
        "description": skill.description,
        "enabled": skill.is_enabled,
        "actions": [
            {
                "name": action.name,
                "description": action.description,
                "input_schema": action.input_schema,
                "output_schema": action.output_schema,
                "is_destructive": action.is_destructive,
                "requires_approval": action.requires_confirmation,
            }
            for action in skill.get_actions()
        ],
    }


@router.post("/skills/{skill_name}/actions/{action_name}")
async def execute_skill_action(
    skill_name: str,
    action_name: str,
    request: Request,
    params: dict[str, Any] = Body(default={}),  # noqa: B008
) -> dict[str, Any]:
    """Execute a skill action directly."""
    require_playground_permission(request)

    registry = get_skills_registry()
    skill = registry.get(skill_name)

    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")

    # Verify action exists
    actions = {a.name: a for a in skill.get_actions()}
    if action_name not in actions:
        raise HTTPException(status_code=404, detail=f"Action '{action_name}' not found in skill '{skill_name}'")

    # Check if action requires approval
    action = actions[action_name]
    if action.requires_confirmation:
        logger.warning(
            f"Executing action that requires approval: {skill_name}.{action_name}",
            extra={"params": params},
        )

    runtime = PlaygroundRuntime(registry)
    result = await runtime.execute_skill(skill_name, action_name, params)

    return result.to_dict()


# ============================================================================
# Session Endpoints
# ============================================================================


@router.get("/sessions")
def list_sessions(
    request: Request,
    agent_id: str | None = Query(None, description="Filter by agent ID"),
    limit: int = Query(20, ge=1, le=100),
) -> list[dict[str, Any]]:
    """List playground sessions for the current user."""
    require_playground_permission(request)

    user = get_current_user(request)
    db = get_db_session()

    try:
        query = select(DBSession).order_by(DBSession.updated_at.desc()).limit(limit)

        if user:
            query = query.where(DBSession.user_id == user.id)

        if agent_id:
            query = query.where(DBSession.agent_id == agent_id)

        sessions = db.execute(query).scalars().all()

        return [
            {
                "session_id": s.id,
                "agent_id": s.agent_id,
                "message_count": len(s.messages or []),
                "total_tokens": s.total_tokens,
                "total_cost_usd": s.total_cost_usd,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
            }
            for s in sessions
        ]

    finally:
        db.close()


@router.get("/sessions/{session_id}")
def get_session(session_id: str, request: Request) -> SessionResponse:
    """Get a specific playground session with full details."""
    require_playground_permission(request)

    db = get_db_session()
    try:
        session = db.execute(select(DBSession).where(DBSession.id == session_id)).scalar_one_or_none()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        return SessionResponse(
            session_id=session.id,
            agent_id=session.agent_id,
            messages=session.messages or [],
            state=session.state or {},
            config_override=session.config_override or {},
            total_tokens=session.total_tokens or 0,
            total_cost_usd=session.total_cost_usd or 0.0,
            created_at=session.created_at.isoformat() if session.created_at else "",
            updated_at=session.updated_at.isoformat() if session.updated_at else "",
        )

    finally:
        db.close()


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, request: Request) -> dict[str, str]:
    """Delete a playground session."""
    require_playground_permission(request)

    db = get_db_session()
    try:
        result = db.execute(select(DBSession).where(DBSession.id == session_id)).scalar_one_or_none()

        if not result:
            raise HTTPException(status_code=404, detail="Session not found")

        db.delete(result)
        db.commit()

        return {"status": "ok", "message": "Session deleted successfully"}

    finally:
        db.close()


# ============================================================================
# Preset Endpoints
# ============================================================================


@router.get("/presets")
def list_presets(
    request: Request,
    agent_id: str | None = Query(None, description="Filter by agent ID"),
    include_shared: bool = Query(True, description="Include shared presets"),
) -> list[dict[str, Any]]:
    """List configuration presets."""
    require_playground_permission(request)

    user = get_current_user(request)
    db = get_db_session()

    try:
        query = select(PlaygroundPreset).order_by(PlaygroundPreset.name)

        # Build filter conditions
        if user and include_shared:
            # User's own presets plus shared presets
            query = query.where(
                (PlaygroundPreset.user_id == user.id) | (PlaygroundPreset.is_shared == True)  # noqa: E712
            )
        elif user:
            query = query.where(PlaygroundPreset.user_id == user.id)
        else:
            # Only shared presets for anonymous users
            query = query.where(PlaygroundPreset.is_shared == True)  # noqa: E712

        if agent_id:
            query = query.where(PlaygroundPreset.agent_id == agent_id)

        presets = db.execute(query).scalars().all()

        return [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "agent_id": p.agent_id,
                "config": p.config,
                "is_shared": p.is_shared,
                "is_default": p.is_default,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in presets
        ]

    finally:
        db.close()


@router.post("/presets")
def create_preset(
    request: Request,
    body: PresetCreateRequest = Body(...),  # noqa: B008
) -> dict[str, Any]:
    """Create a new configuration preset."""
    require_playground_permission(request)

    user = get_current_user(request)
    db = get_db_session()

    try:
        # Validate agent ID
        if body.agent_id not in AVAILABLE_AGENTS:
            raise HTTPException(status_code=400, detail=f"Invalid agent_id: {body.agent_id}")

        # Check for duplicate name
        existing = db.execute(
            select(PlaygroundPreset).where(
                PlaygroundPreset.name == body.name,
                PlaygroundPreset.user_id == (user.id if user else None),
            )
        ).scalar_one_or_none()

        if existing:
            raise HTTPException(status_code=409, detail=f"Preset with name '{body.name}' already exists")

        preset = PlaygroundPreset(
            id=str(uuid.uuid4()),
            name=body.name,
            description=body.description,
            agent_id=body.agent_id,
            config=body.config,
            user_id=user.id if user else None,
            is_shared=body.is_shared,
            is_default=False,
        )

        db.add(preset)
        db.commit()

        return {
            "id": preset.id,
            "name": preset.name,
            "message": "Preset created successfully",
        }

    finally:
        db.close()


@router.delete("/presets/{preset_id}")
def delete_preset(preset_id: str, request: Request) -> dict[str, str]:
    """Delete a configuration preset."""
    require_playground_permission(request)

    user = get_current_user(request)
    db = get_db_session()

    try:
        preset = db.execute(select(PlaygroundPreset).where(PlaygroundPreset.id == preset_id)).scalar_one_or_none()

        if not preset:
            raise HTTPException(status_code=404, detail="Preset not found")

        # Only owner can delete
        if user and preset.user_id != user.id:
            raise HTTPException(status_code=403, detail="Not authorized to delete this preset")

        db.delete(preset)
        db.commit()

        return {"status": "ok", "message": "Preset deleted successfully"}

    finally:
        db.close()


@router.get("/presets/{preset_id}")
def get_preset(preset_id: str, request: Request) -> dict[str, Any]:
    """Get a specific preset by ID."""
    require_playground_permission(request)

    db = get_db_session()
    try:
        preset = db.execute(select(PlaygroundPreset).where(PlaygroundPreset.id == preset_id)).scalar_one_or_none()

        if not preset:
            raise HTTPException(status_code=404, detail="Preset not found")

        return {
            "id": preset.id,
            "name": preset.name,
            "description": preset.description,
            "agent_id": preset.agent_id,
            "config": preset.config,
            "is_shared": preset.is_shared,
            "is_default": preset.is_default,
            "user_id": preset.user_id,
            "created_at": preset.created_at.isoformat() if preset.created_at else None,
            "updated_at": preset.updated_at.isoformat() if preset.updated_at else None,
        }

    finally:
        db.close()
