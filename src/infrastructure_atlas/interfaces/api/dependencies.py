"""Shared FastAPI dependencies for the Infrastructure Atlas API layer."""

from __future__ import annotations

import json
import logging
from collections.abc import Generator
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from infrastructure_atlas.application.context import ServiceContext
from infrastructure_atlas.application.services import (
    AdminService,
    DefaultChatHistoryService,
    DefaultUserService,
    VCenterService,
    create_admin_service,
    create_chat_history_service,
    create_user_service,
    create_vcenter_service,
)
from infrastructure_atlas.application.services.profile import (
    ProfileServiceProtocol,
    create_profile_service,
)
from infrastructure_atlas.db.models import User

logger = logging.getLogger(__name__)


def _get_sessionmaker():
    """Lazy load sessionmaker to avoid initialization at import time."""
    from infrastructure_atlas.db import get_sessionmaker

    return get_sessionmaker()


def get_service_context() -> ServiceContext:
    """Return a per-request service context bound to the global sessionmaker."""
    return ServiceContext(session_factory=_get_sessionmaker())


ServiceContextDep = Annotated[ServiceContext, Depends(get_service_context)]


def get_db_session(context: ServiceContextDep) -> Generator[Session, None, None]:
    """Provide a SQLAlchemy session for FastAPI dependencies."""
    with context.session_scope() as session:
        yield session


DbSessionDep = Annotated[Session, Depends(get_db_session)]


def get_user_service() -> DefaultUserService:
    """Return a user service using the configured storage backend."""
    return create_user_service()


def get_chat_history_service() -> DefaultChatHistoryService:
    """Return a chat history service using the configured storage backend."""
    return create_chat_history_service()


def get_profile_service() -> ProfileServiceProtocol:
    """Return a profile service using the configured storage backend."""
    return create_profile_service()


def get_admin_service() -> AdminService:
    """Return the admin service using the configured storage backend."""
    return create_admin_service()


def get_vcenter_service() -> VCenterService:
    """Return the vCenter service using the configured storage backend."""
    return create_vcenter_service()


def current_user(request: Request) -> User:
    """Get the current authenticated user.

    Supports both SQLAlchemy User model and UserEntity from MongoDB.
    """
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    # Accept both User (SQLAlchemy) and UserEntity (MongoDB)
    # Check for required attributes instead of isinstance
    if not hasattr(user, "id") or not hasattr(user, "role") or not hasattr(user, "is_active"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def optional_user(request: Request) -> User | None:
    """Get the current user if authenticated, otherwise None."""
    user = getattr(request.state, "user", None)
    if user is None:
        return None
    if not hasattr(user, "id") or not hasattr(user, "role"):
        return None
    return user


CurrentUserDep = Annotated[User, Depends(current_user)]
OptionalUserDep = Annotated[User | None, Depends(optional_user)]


def admin_user(user: CurrentUserDep) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


AdminUserDep = Annotated[User, Depends(admin_user)]


# ----- Utility functions (moved from api/app.py to break circular imports) -----

_USAGE_FIELD_ALIASES: dict[str, str] = {
    "prompt_tokens": "prompt_tokens",
    "completion_tokens": "completion_tokens",
    "total_tokens": "total_tokens",
    "input_tokens": "prompt_tokens",
    "output_tokens": "completion_tokens",
    "usage_tokens": "total_tokens",
    "input_token_count": "prompt_tokens",
    "output_token_count": "completion_tokens",
    "total_token_count": "total_tokens",
    "promptTokenCount": "prompt_tokens",
    "candidatesTokenCount": "completion_tokens",
    "totalTokens": "total_tokens",
}


def normalise_usage(raw: Any) -> dict[str, int] | None:
    """Normalize token usage from various AI provider formats to a standard format."""
    if raw is None:
        return None
    usage: dict[str, int] = {}
    for source, target in _USAGE_FIELD_ALIASES.items():
        value = None
        if isinstance(raw, dict):
            value = raw.get(source)
        else:
            value = getattr(raw, source, None)
        if isinstance(value, int | float):
            usage[target] = int(value)
    return usage or None


def safe_json_loads(data: str) -> Any | None:
    """Safely parse JSON, returning None on failure."""
    try:
        return json.loads(data)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.debug("Skipping streaming event with invalid JSON", extra={"error": str(exc)})
        return None


def require_permission(request: Request, permission: str) -> None:
    """Check if user has required permission, raise HTTPException if not."""
    user = getattr(request.state, "user", None)
    if user is None:
        return
    if getattr(user, "role", "") == "admin":
        return
    permissions = getattr(request.state, "permissions", frozenset())
    if permission not in permissions:
        raise HTTPException(status_code=403, detail="Forbidden: missing permission")


__all__ = [
    "AdminUserDep",
    "CurrentUserDep",
    "DbSessionDep",
    "OptionalUserDep",
    "get_admin_service",
    "get_chat_history_service",
    "get_db_session",
    "get_profile_service",
    "get_service_context",
    "get_user_service",
    "get_vcenter_service",
    "normalise_usage",
    "require_permission",
    "safe_json_loads",
]
