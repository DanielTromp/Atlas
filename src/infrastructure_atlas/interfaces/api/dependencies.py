"""Shared FastAPI dependencies for the Infrastructure Atlas API layer."""

from __future__ import annotations

from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from infrastructure_atlas.application.context import ServiceContext
from infrastructure_atlas.application.services import (
    AdminService,
    DefaultChatHistoryService,
    DefaultUserService,
    ForemanService,
    VCenterService,
    create_admin_service,
    create_chat_history_service,
    create_foreman_service,
    create_user_service,
    create_vcenter_service,
)
from infrastructure_atlas.application.services.profile import (
    ProfileServiceProtocol,
    create_profile_service,
)
from infrastructure_atlas.db.models import User
from infrastructure_atlas.infrastructure.repository_factory import get_storage_backend


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


def admin_user(user: CurrentUserDep) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


CurrentUserDep = Annotated[User, Depends(current_user)]
OptionalUserDep = Annotated[User | None, Depends(optional_user)]
AdminUserDep = Annotated[User, Depends(admin_user)]


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
]
