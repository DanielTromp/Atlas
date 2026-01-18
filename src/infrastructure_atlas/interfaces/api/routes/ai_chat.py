"""AI Chat API routes with multi-provider support and tool calling."""

from __future__ import annotations

import json
import os
import secrets
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from infrastructure_atlas.ai.admin import get_ai_admin_service
from infrastructure_atlas.ai.chat_agent import create_chat_agent
from infrastructure_atlas.ai.commands import get_command_handler
from infrastructure_atlas.ai.models import (
    ChatMessage as AIChatMessage,
)
from infrastructure_atlas.ai.pricing import calculate_cost
from infrastructure_atlas.ai.usage_service import create_usage_service
from infrastructure_atlas.db.models import ChatMessage, ChatSession, User
from infrastructure_atlas.infrastructure.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/ai", tags=["ai-chat"])


# Lazy imports to avoid circular dependencies
def get_db_session():
    from infrastructure_atlas.api.app import SessionLocal

    return SessionLocal()


def get_current_user(request: Request) -> User | None:
    """Get current user from request state."""
    return getattr(request.state, "user", None)


def require_chat_permission(request: Request) -> None:
    """Require chat.use permission."""
    from infrastructure_atlas.api.app import require_permission

    require_permission(request, "chat.use")


# Pydantic models
class ChatCompletionRequest(BaseModel):
    """Request for chat completion."""

    message: str
    session_id: str | None = None
    provider: str | None = None
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    tools_enabled: bool = True
    streaming: bool = True
    system_prompt: str | None = None
    role: str = "general"  # Agent role: triage, engineer, general


class AgentConfigRequest(BaseModel):
    """Request to configure an agent."""

    provider: str
    model: str
    name: str = "Atlas AI"
    system_prompt: str | None = None
    temperature: float | None = None
    tools_enabled: bool = True
    streaming_enabled: bool = True


class SessionCreateRequest(BaseModel):
    """Request to create a new chat session."""

    title: str | None = None
    provider: str | None = None
    model: str | None = None


# Session management
def _get_or_create_session(
    db: Session,
    session_id: str | None,
    user: User | None,
    provider: str | None = None,
    model: str | None = None,
) -> ChatSession:
    """Get existing session or create a new one."""
    if session_id:
        stmt = select(ChatSession).where(ChatSession.session_id == session_id)
        session = db.execute(stmt).scalar_one_or_none()
        if session:
            return session

    # Create new session
    new_session_id = session_id or f"ai_{secrets.token_hex(8)}"
    session = ChatSession(
        session_id=new_session_id,
        title="New AI Chat",
        user_id=user.id if user else None,
        provider_type=provider,
        model=model,
        context_variables={},
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def _save_message(
    db: Session,
    session: ChatSession,
    role: str,
    content: str,
    message_type: str = "text",
    tool_call_id: str | None = None,
    tool_name: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ChatMessage:
    """Save a message to the database."""
    message = ChatMessage(
        session_id=session.id,
        role=role,
        content=content,
        message_type=message_type,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        metadata_json=metadata,
    )
    db.add(message)
    session.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(message)
    return message


def _load_chat_history(db: Session, session: ChatSession) -> list[AIChatMessage]:
    """Load chat history from database into AI message format."""
    messages = []
    for msg in session.messages:
        role_map = {
            "user": AIChatMessage.user,
            "assistant": AIChatMessage.assistant,
            "system": AIChatMessage.system,
        }

        if msg.role in role_map:
            messages.append(role_map[msg.role](msg.content))
        elif msg.role == "tool":
            messages.append(
                AIChatMessage.tool(
                    content=msg.content,
                    tool_call_id=msg.tool_call_id or "",
                    name=msg.tool_name,
                )
            )

    return messages


# Routes
@router.get("/providers")
async def list_providers(request: Request):
    """List available AI providers and their status."""
    require_chat_permission(request)
    admin_service = get_ai_admin_service()
    return {"providers": admin_service.list_providers()}


@router.get("/providers/{provider_name}/models")
async def list_provider_models(request: Request, provider_name: str):
    """List available models for a provider."""
    require_chat_permission(request)
    admin_service = get_ai_admin_service()
    models = admin_service.get_provider_models(provider_name)
    return {"provider": provider_name, "models": models}


@router.post("/providers/{provider_name}/test")
async def test_provider(request: Request, provider_name: str):
    """Test a provider connection."""
    import os

    require_chat_permission(request)

    # Use global registry directly to pick up latest env config
    from infrastructure_atlas.ai.providers import get_provider_registry

    registry = get_provider_registry()

    # Clear cached provider to force reload from env
    if provider_name in registry._providers:
        del registry._providers[provider_name]
    if provider_name in registry._configs:
        del registry._configs[provider_name]

    # Debug: Log env var status
    env_key = {
        "openrouter": "OPENROUTER_API_KEY",
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "azure_openai": "AZURE_OPENAI_API_KEY",
        "gemini": "GOOGLE_API_KEY",
    }.get(provider_name, "")

    key_value = os.environ.get(env_key, "")
    logger.info(
        f"Testing provider {provider_name}",
        extra={"env_key": env_key, "has_key": bool(key_value), "key_prefix": key_value[:15] if key_value else ""},
    )

    result = await registry.test_provider(provider_name)
    # Normalize response for UI
    result["success"] = result.get("status") == "connected"
    return result


@router.get("/tools")
async def list_tools(request: Request, category: str | None = None):
    """List available tools for AI chat."""
    require_chat_permission(request)
    admin_service = get_ai_admin_service()

    if category:
        tools_by_cat = admin_service.get_tools_by_category()
        return {"category": category, "tools": tools_by_cat.get(category, [])}

    return {"tools": admin_service.list_tools()}


@router.get("/config")
async def get_default_config(request: Request):
    """Get default AI chat configuration."""
    require_chat_permission(request)
    admin_service = get_ai_admin_service()
    return admin_service.get_default_agent_config()


@router.put("/config/{provider}")
async def save_provider_config(
    request: Request,
    provider: str,
    config: dict,
):
    """Save AI provider configuration.

    This saves the provider config and updates environment variables
    for immediate use by the provider registry.
    """
    from infrastructure_atlas.api.app import require_permission
    import os

    require_permission(request, "admin.write")

    # Map provider to environment variable names
    provider_env_map = {
        "azure_openai": {
            "api_key": "AZURE_OPENAI_API_KEY",
            "endpoint": "AZURE_OPENAI_ENDPOINT",
            "deployment": "AZURE_OPENAI_DEPLOYMENT",
        },
        "openai": {
            "api_key": "OPENAI_API_KEY",
            "default_model": "OPENAI_DEFAULT_MODEL",
        },
        "openrouter": {
            "api_key": "OPENROUTER_API_KEY",
            "default_model": "OPENROUTER_DEFAULT_MODEL",
        },
        "anthropic": {
            "api_key": "ANTHROPIC_API_KEY",
            "default_model": "ANTHROPIC_DEFAULT_MODEL",
        },
        "gemini": {
            "api_key": "GOOGLE_API_KEY",
            "default_model": "GEMINI_DEFAULT_MODEL",
        },
    }

    if provider not in provider_env_map:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    try:
        env_map = provider_env_map[provider]
        saved_keys = []

        for config_key, env_var in env_map.items():
            if config_key in config and config[config_key]:
                value = config[config_key]
                # Set in environment for immediate use
                os.environ[env_var] = value
                saved_keys.append(env_var)

        # Persist API keys to encrypted database storage
        if saved_keys:
            from infrastructure_atlas.infrastructure.security.secret_store import sync_secure_settings

            sync_secure_settings(saved_keys)

        # Clear provider cache to pick up new config
        from infrastructure_atlas.ai.providers import get_provider_registry

        registry = get_provider_registry()
        if provider in registry._providers:
            del registry._providers[provider]
        if provider in registry._configs:
            del registry._configs[provider]

        return {"status": "saved", "provider": provider, "keys": saved_keys}

    except Exception as e:
        logger.error("Failed to save provider config", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail=str(e))


# In-memory storage for AI settings (would be database in production)
_ai_settings: dict = {
    "default_provider": "openrouter",
    "max_tokens": 4096,
    "temperature": 0.7,
    "system_prompt": "",
    "tools_enabled": True,
    "streaming_enabled": True,
}


@router.get("/settings")
async def get_ai_settings(request: Request):
    """Get AI chat default settings."""
    require_chat_permission(request)
    return _ai_settings.copy()


@router.put("/settings")
async def save_ai_settings(request: Request, settings: dict):
    """Save AI chat default settings."""
    from infrastructure_atlas.api.app import require_permission

    require_permission(request, "admin.write")

    # Validate and update settings
    if "default_provider" in settings:
        _ai_settings["default_provider"] = settings["default_provider"]
    if "max_tokens" in settings:
        _ai_settings["max_tokens"] = max(100, min(128000, int(settings["max_tokens"])))
    if "temperature" in settings:
        _ai_settings["temperature"] = max(0.0, min(2.0, float(settings["temperature"])))
    if "system_prompt" in settings:
        _ai_settings["system_prompt"] = str(settings.get("system_prompt", ""))[:4000]
    if "tools_enabled" in settings:
        _ai_settings["tools_enabled"] = bool(settings["tools_enabled"])
    if "streaming_enabled" in settings:
        _ai_settings["streaming_enabled"] = bool(settings["streaming_enabled"])

    logger.info("AI settings updated", extra={"settings": _ai_settings})
    return {"status": "saved", "settings": _ai_settings}


def get_ai_settings() -> dict:
    """Get current AI settings (for use by other routes)."""
    return _ai_settings.copy()


@router.get("/status")
async def get_ai_status(request: Request):
    """Get AI system status."""
    require_chat_permission(request)
    admin_service = get_ai_admin_service()
    return await admin_service.get_system_status()


@router.post("/sessions")
async def create_session(
    request: Request,
    req: SessionCreateRequest,
):
    """Create a new AI chat session."""
    require_chat_permission(request)
    user = get_current_user(request)
    db = get_db_session()

    try:
        session = _get_or_create_session(
            db,
            session_id=None,
            user=user,
            provider=req.provider,
            model=req.model,
        )

        if req.title:
            session.title = req.title
            db.commit()

        return {
            "session_id": session.session_id,
            "title": session.title,
            "provider": session.provider_type,
            "model": session.model,
            "created_at": session.created_at.isoformat(),
        }
    finally:
        db.close()


@router.get("/sessions")
async def list_sessions(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
):
    """List AI chat sessions for the current user."""
    require_chat_permission(request)
    user = get_current_user(request)
    db = get_db_session()

    try:
        stmt = select(ChatSession).order_by(ChatSession.updated_at.desc())
        if user:
            stmt = stmt.where(ChatSession.user_id == user.id)
        stmt = stmt.limit(limit)

        sessions = db.execute(stmt).scalars().all()

        return {
            "sessions": [
                {
                    "session_id": s.session_id,
                    "title": s.title,
                    "provider": s.provider_type,
                    "model": s.model,
                    "message_count": len(s.messages),
                    "created_at": s.created_at.isoformat(),
                    "updated_at": s.updated_at.isoformat(),
                }
                for s in sessions
            ]
        }
    finally:
        db.close()


@router.get("/sessions/{session_id}")
async def get_session(request: Request, session_id: str):
    """Get a specific chat session with its messages."""
    require_chat_permission(request)
    db = get_db_session()

    try:
        stmt = select(ChatSession).where(ChatSession.session_id == session_id)
        session = db.execute(stmt).scalar_one_or_none()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # Calculate session totals
        total_tokens = 0
        total_cost = 0.0
        for msg in session.messages:
            if msg.metadata_json and "usage" in msg.metadata_json:
                usage = msg.metadata_json["usage"]
                total_tokens += usage.get("total_tokens", 0)
            if msg.metadata_json and "cost" in msg.metadata_json:
                cost = msg.metadata_json["cost"]
                total_cost += cost.get("cost_usd", 0.0)

        return {
            "session_id": session.session_id,
            "title": session.title,
            "provider": session.provider_type,
            "model": session.model,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost, 6),
            "messages": [
                {
                    "role": msg.role,
                    "content": msg.content,
                    "message_type": msg.message_type,
                    "tool_name": msg.tool_name,
                    "created_at": msg.created_at.isoformat(),
                    "usage": msg.metadata_json.get("usage") if msg.metadata_json else None,
                    "cost": msg.metadata_json.get("cost") if msg.metadata_json else None,
                    "tool_calls": msg.metadata_json.get("tool_calls") if msg.metadata_json else None,
                }
                for msg in session.messages
            ],
        }
    finally:
        db.close()


class UpdateSessionRequest(BaseModel):
    """Request to update session settings."""
    title: str | None = None
    provider: str | None = None
    model: str | None = None


@router.patch("/sessions/{session_id}")
async def update_session(request: Request, session_id: str, req: UpdateSessionRequest):
    """Update a chat session's settings (title, provider, model)."""
    require_chat_permission(request)
    user = get_current_user(request)
    db = get_db_session()

    try:
        stmt = select(ChatSession).where(ChatSession.session_id == session_id)
        session = db.execute(stmt).scalar_one_or_none()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # Check ownership
        if user and session.user_id and session.user_id != user.id:
            raise HTTPException(status_code=403, detail="Access denied")

        # Update fields if provided (use model_fields_set to detect explicit null)
        if req.title is not None:
            session.title = req.title
        if req.provider is not None:
            session.provider_type = req.provider
        # Allow model to be explicitly set to None/empty (for "Default" selection)
        if "model" in req.model_fields_set:
            session.model = req.model or None  # Normalize empty string to None

        db.commit()

        return {
            "session_id": session.session_id,
            "title": session.title,
            "provider": session.provider_type,
            "model": session.model,
            "updated_at": session.updated_at.isoformat(),
        }
    finally:
        db.close()


@router.delete("/sessions/{session_id}")
async def delete_session(request: Request, session_id: str):
    """Delete a chat session."""
    require_chat_permission(request)
    user = get_current_user(request)
    db = get_db_session()

    try:
        stmt = select(ChatSession).where(ChatSession.session_id == session_id)
        session = db.execute(stmt).scalar_one_or_none()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # Check ownership
        if user and session.user_id and session.user_id != user.id:
            raise HTTPException(status_code=403, detail="Access denied")

        db.delete(session)
        db.commit()

        return {"status": "deleted", "session_id": session_id}
    finally:
        db.close()


@router.post("/chat")
async def chat_completion(
    request: Request,
    req: ChatCompletionRequest,
):
    """Send a message and get a response (non-streaming)."""
    require_chat_permission(request)
    user = get_current_user(request)
    db = get_db_session()

    try:
        # Check for slash command
        command_handler = get_command_handler()
        if command_handler.is_command(req.message):
            result = await command_handler.execute(req.message)
            return {
                "type": "command",
                "command_result": result.to_dict(),
            }

        # Get or create session
        session = _get_or_create_session(
            db,
            session_id=req.session_id,
            user=user,
            provider=req.provider,
            model=req.model,
        )

        # Update session title from first message
        if session.title == "New AI Chat" and req.message:
            session.title = req.message[:60]
            db.commit()

        # Determine provider and model (use saved defaults)
        ai_defaults = get_ai_settings()
        provider_type = req.provider or session.provider_type or ai_defaults["default_provider"]
        model = req.model or session.model

        # Get session cookie for authenticated tool calls
        # Note: Session cookie is named 'atlas_ui' (see SESSION_COOKIE_NAME in app.py)
        session_cookie = request.cookies.get("atlas_ui")

        # Create chat agent with defaults
        agent = create_chat_agent(
            name="Atlas AI",
            provider_type=provider_type,
            model=model,
            system_prompt=req.system_prompt or ai_defaults.get("system_prompt"),
            temperature=req.temperature if req.temperature is not None else ai_defaults.get("temperature"),
            max_tokens=req.max_tokens or ai_defaults.get("max_tokens", 16384),
            tools_enabled=req.tools_enabled
            if req.tools_enabled is not None
            else ai_defaults.get("tools_enabled", True),
            streaming_enabled=False,
            api_token=os.getenv("ATLAS_API_TOKEN"),
            session_cookie=session_cookie,
            role=req.role,
        )

        # Get the actual model used (agent resolves default if not specified)
        actual_model = agent.config.model

        # Load history
        history = _load_chat_history(db, session)
        agent.set_history(history)

        # Get completion
        response = await agent.chat(req.message)

        # Calculate cost
        cost_info = None
        if response.usage:
            cost_info = calculate_cost(
                model=response.model or model or "unknown",
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
            )

        # Save messages to database
        _save_message(db, session, "user", req.message)
        usage_metadata = None
        if response.usage:
            usage_metadata = {
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                },
                "cost": cost_info.to_dict() if cost_info else None,
                "model": response.model,
                "provider": response.provider,
            }
        _save_message(
            db,
            session,
            "assistant",
            response.content,
            metadata=usage_metadata,
        )

        # Log activity for usage tracking
        if response.usage:
            try:
                usage_service = create_usage_service(db)
                usage_service.log_activity(
                    provider=response.provider or provider_type or "unknown",
                    model=response.model or actual_model or "unknown",
                    tokens_prompt=response.usage.prompt_tokens,
                    tokens_completion=response.usage.completion_tokens,
                    tokens_reasoning=getattr(response.usage, "reasoning_tokens", 0) or 0,
                    generation_time_ms=response.duration_ms,
                    streamed=False,
                    finish_reason=response.finish_reason or "stop",
                    user_id=user.id if user else None,
                    session_id=session.session_id,
                    app_name="atlas-chat",
                )
            except Exception as log_err:
                logger.warning(f"Failed to log AI activity: {log_err}")

        return {
            "type": "message",
            "session_id": session.session_id,
            "content": response.content,
            "model": response.model,
            "provider": response.provider,
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                "total_tokens": response.usage.total_tokens if response.usage else 0,
                "cost_usd": cost_info.cost_usd if cost_info else 0.0,
            },
            "duration_ms": response.duration_ms,
        }

    except Exception as e:
        logger.error(
            "Chat completion failed",
            extra={"event": "chat_error", "error": str(e)},
        )
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.post("/chat/stream")
async def chat_stream(
    request: Request,
    req: ChatCompletionRequest,
):
    """Send a message and stream the response."""
    require_chat_permission(request)
    user = get_current_user(request)

    # Check for slash command
    command_handler = get_command_handler()
    if command_handler.is_command(req.message):
        result = await command_handler.execute(req.message)

        async def command_stream():
            yield f"data: {json.dumps({'type': 'command', 'result': result.to_dict()})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            command_stream(),
            media_type="text/event-stream",
        )

    db = get_db_session()

    try:
        # Get or create session
        session = _get_or_create_session(
            db,
            session_id=req.session_id,
            user=user,
            provider=req.provider,
            model=req.model,
        )
        session_id = session.session_id

        # Update session title
        if session.title == "New AI Chat" and req.message:
            session.title = req.message[:60]
            db.commit()

        # Determine provider and model (use saved defaults)
        ai_defaults = get_ai_settings()
        provider_type = req.provider or session.provider_type or ai_defaults["default_provider"]
        model = req.model or session.model

        # Load history before closing db
        history = _load_chat_history(db, session)

        # Save user message
        _save_message(db, session, "user", req.message)

    finally:
        db.close()

    # Get session cookie for authenticated tool calls
    # Note: Session cookie is named 'atlas_ui' (see SESSION_COOKIE_NAME in app.py)
    session_cookie = request.cookies.get("atlas_ui")

    # Create chat agent with defaults
    agent = create_chat_agent(
        name="Atlas AI",
        provider_type=provider_type,
        model=model,
        system_prompt=req.system_prompt or ai_defaults.get("system_prompt"),
        temperature=req.temperature if req.temperature is not None else ai_defaults.get("temperature"),
        max_tokens=req.max_tokens or ai_defaults.get("max_tokens", 4096),
        tools_enabled=req.tools_enabled if req.tools_enabled is not None else ai_defaults.get("tools_enabled", True),
        streaming_enabled=ai_defaults.get("streaming_enabled", True),
        api_token=os.getenv("ATLAS_API_TOKEN"),
        session_cookie=session_cookie,
        role=req.role,
    )
    agent.set_history(history)

    # Get the actual model used (agent resolves default if not specified)
    actual_model = agent.config.model

    async def stream_response():
        accumulated_content = ""
        final_usage = None
        finish_reason = "stop"
        tool_calls = []  # Track tool calls for persistence

        try:
            async for chunk in agent.stream_chat(req.message):
                # Handle StreamChunk
                if hasattr(chunk, "content"):
                    if chunk.content:
                        accumulated_content += chunk.content
                        yield f"data: {json.dumps({'type': 'content', 'content': chunk.content})}\n\n"

                    if chunk.is_complete:
                        if chunk.usage:
                            final_usage = chunk.usage
                        if chunk.finish_reason:
                            finish_reason = chunk.finish_reason
                        yield f"data: {json.dumps({'type': 'done', 'finish_reason': chunk.finish_reason})}\n\n"

                # Handle ToolStart (tool execution beginning)
                elif hasattr(chunk, "tool_name") and hasattr(chunk, "arguments") and not hasattr(chunk, "success"):
                    tool_calls.append({
                        "tool_call_id": chunk.tool_call_id,
                        "tool_name": chunk.tool_name,
                        "status": "running",
                    })
                    yield f"data: {json.dumps({'type': 'tool_start', 'tool_name': chunk.tool_name, 'tool_call_id': chunk.tool_call_id})}\n\n"

                # Handle ToolResult (tool execution complete)
                elif hasattr(chunk, "tool_name") and hasattr(chunk, "success"):
                    # Update the tool call status
                    for tc in tool_calls:
                        if tc["tool_call_id"] == chunk.tool_call_id or tc["tool_name"] == chunk.tool_name:
                            tc["status"] = "success" if chunk.success else "error"
                            tc["success"] = chunk.success
                            break
                    else:
                        # Tool wasn't tracked yet (shouldn't happen, but handle gracefully)
                        tool_calls.append({
                            "tool_call_id": chunk.tool_call_id,
                            "tool_name": chunk.tool_name,
                            "status": "success" if chunk.success else "error",
                            "success": chunk.success,
                        })
                    yield f"data: {json.dumps({'type': 'tool_result', 'tool_name': chunk.tool_name, 'tool_call_id': chunk.tool_call_id, 'success': chunk.success})}\n\n"

            # Calculate cost
            cost_info = None
            if final_usage:
                cost_info = calculate_cost(
                    model=model or "unknown",
                    prompt_tokens=final_usage.prompt_tokens,
                    completion_tokens=final_usage.completion_tokens,
                )

            # Save assistant message
            db = get_db_session()
            try:
                stmt = select(ChatSession).where(ChatSession.session_id == session_id)
                session = db.execute(stmt).scalar_one_or_none()
                if session:
                    usage_metadata = {}
                    if final_usage:
                        usage_metadata = {
                            "usage": {
                                "prompt_tokens": final_usage.prompt_tokens,
                                "completion_tokens": final_usage.completion_tokens,
                                "total_tokens": final_usage.total_tokens,
                            },
                            "cost": cost_info.to_dict() if cost_info else None,
                            "model": model,
                            "provider": provider_type,
                        }
                    # Include tool calls in metadata for persistence
                    if tool_calls:
                        usage_metadata["tool_calls"] = tool_calls
                    _save_message(
                        db,
                        session,
                        "assistant",
                        accumulated_content,
                        metadata=usage_metadata if usage_metadata else None,
                    )

                # Log activity for usage tracking
                if final_usage:
                    try:
                        usage_service = create_usage_service(db)
                        usage_service.log_activity(
                            provider=provider_type or "unknown",
                            model=actual_model or "unknown",
                            tokens_prompt=final_usage.prompt_tokens,
                            tokens_completion=final_usage.completion_tokens,
                            tokens_reasoning=getattr(final_usage, "reasoning_tokens", 0) or 0,
                            streamed=True,
                            finish_reason=finish_reason,
                            user_id=user.id if user else None,
                            session_id=session_id,
                            app_name="atlas-chat",
                        )
                    except Exception as log_err:
                        logger.warning(f"Failed to log AI activity: {log_err}")
            finally:
                db.close()

            # Send final usage info
            if final_usage:
                usage_dict = final_usage.__dict__.copy()
                if cost_info:
                    usage_dict["cost_usd"] = cost_info.cost_usd
                usage_dict["finish_reason"] = finish_reason
                yield f"data: {json.dumps({'type': 'usage', 'usage': usage_dict})}\n\n"

            yield "data: [DONE]\n\n"

        except Exception as e:
            import traceback

            logger.error(
                "Streaming error",
                extra={"event": "stream_error", "error": str(e), "traceback": traceback.format_exc()},
            )
            logger.error(f"Streaming traceback:\n{traceback.format_exc()}")
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        stream_response(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/command")
async def execute_command(
    request: Request,
    command: str = Body(..., embed=True),
):
    """Execute a slash command."""
    require_chat_permission(request)

    command_handler = get_command_handler()

    if not command_handler.is_command(command):
        # Add slash if not present
        command = f"/{command}"

    result = await command_handler.execute(command)
    return result.to_dict()


@router.get("/commands")
async def list_commands(request: Request):
    """List available slash commands."""
    require_chat_permission(request)

    from infrastructure_atlas.ai.commands.definitions import get_all_commands

    commands = get_all_commands()
    return {
        "commands": [
            {
                "name": cmd.name,
                "description": cmd.description,
                "usage": cmd.usage,
                "aliases": cmd.aliases,
            }
            for cmd in commands
        ]
    }


@router.get("/stats")
async def get_ai_stats(request: Request):
    """Get AI chat usage statistics."""
    require_chat_permission(request)
    user = get_current_user(request)
    db = get_db_session()

    try:
        # Get all sessions for user
        stmt = select(ChatSession)
        if user:
            stmt = stmt.where(ChatSession.user_id == user.id)
        sessions = db.execute(stmt).scalars().all()

        # Aggregate statistics
        total_sessions = len(sessions)
        total_messages = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_tokens = 0
        total_cost_usd = 0.0
        model_usage: dict[str, dict[str, Any]] = {}
        provider_usage: dict[str, dict[str, Any]] = {}

        for session in sessions:
            for msg in session.messages:
                total_messages += 1
                if msg.metadata_json:
                    usage = msg.metadata_json.get("usage")
                    cost = msg.metadata_json.get("cost")
                    model = msg.metadata_json.get("model", "unknown")
                    provider = msg.metadata_json.get("provider", "unknown")

                    if usage:
                        prompt_tokens = usage.get("prompt_tokens", 0)
                        completion_tokens = usage.get("completion_tokens", 0)
                        tokens = usage.get("total_tokens", 0)

                        total_prompt_tokens += prompt_tokens
                        total_completion_tokens += completion_tokens
                        total_tokens += tokens

                        # Track by model
                        if model not in model_usage:
                            model_usage[model] = {
                                "prompt_tokens": 0,
                                "completion_tokens": 0,
                                "total_tokens": 0,
                                "messages": 0,
                                "cost_usd": 0.0,
                            }
                        model_usage[model]["prompt_tokens"] += prompt_tokens
                        model_usage[model]["completion_tokens"] += completion_tokens
                        model_usage[model]["total_tokens"] += tokens
                        model_usage[model]["messages"] += 1

                        # Track by provider
                        if provider not in provider_usage:
                            provider_usage[provider] = {
                                "prompt_tokens": 0,
                                "completion_tokens": 0,
                                "total_tokens": 0,
                                "messages": 0,
                                "cost_usd": 0.0,
                            }
                        provider_usage[provider]["prompt_tokens"] += prompt_tokens
                        provider_usage[provider]["completion_tokens"] += completion_tokens
                        provider_usage[provider]["total_tokens"] += tokens
                        provider_usage[provider]["messages"] += 1

                    if cost:
                        cost_usd = cost.get("cost_usd", 0.0)
                        total_cost_usd += cost_usd
                        if model in model_usage:
                            model_usage[model]["cost_usd"] += cost_usd
                        if provider in provider_usage:
                            provider_usage[provider]["cost_usd"] += cost_usd

        return {
            "total_sessions": total_sessions,
            "total_messages": total_messages,
            "total_prompt_tokens": total_prompt_tokens,
            "total_completion_tokens": total_completion_tokens,
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost_usd, 6),
            "by_model": {k: {**v, "cost_usd": round(v["cost_usd"], 6)} for k, v in model_usage.items()},
            "by_provider": {k: {**v, "cost_usd": round(v["cost_usd"], 6)} for k, v in provider_usage.items()},
        }
    finally:
        db.close()
