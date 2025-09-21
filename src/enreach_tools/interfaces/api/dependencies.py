"""Shared FastAPI dependencies for the Enreach API layer."""
from __future__ import annotations

from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from enreach_tools.application.context import ServiceContext
from enreach_tools.application.services import (
    AdminService,
    DefaultChatHistoryService,
    DefaultUserService,
    create_admin_service,
    create_chat_history_service,
    create_user_service,
)
from enreach_tools.application.services.profile import ProfileService, create_profile_service
from enreach_tools.db import get_sessionmaker
from enreach_tools.db.models import User

Sessionmaker = get_sessionmaker()


def get_service_context() -> ServiceContext:
    """Return a per-request service context bound to the global sessionmaker."""
    return ServiceContext(session_factory=Sessionmaker)


def get_db_session(context: ServiceContext = Depends(get_service_context)) -> Generator[Session, None, None]:
    """Provide a SQLAlchemy session for FastAPI dependencies."""
    with context.session_scope() as session:
        yield session


def get_user_service(session: Session = Depends(get_db_session)) -> DefaultUserService:
    """Return a user service bound to the active session."""
    return create_user_service(session)


def get_chat_history_service(session: Session = Depends(get_db_session)) -> DefaultChatHistoryService:
    """Return a chat history service bound to the active session."""
    return create_chat_history_service(session)


def get_profile_service(session: Session = Depends(get_db_session)) -> ProfileService:
    """Return a profile service for the active session."""
    return create_profile_service(session)


def get_admin_service(session: Session = Depends(get_db_session)) -> AdminService:
    """Return the admin service bound to the active session."""
    return create_admin_service(session)


def current_user(request: Request) -> User:
    user = getattr(request.state, "user", None)
    if not isinstance(user, User):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def optional_user(request: Request) -> User | None:
    user = getattr(request.state, "user", None)
    return user if isinstance(user, User) else None


def admin_user(user: CurrentUserDep) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


CurrentUserDep = Annotated[User, Depends(current_user)]
OptionalUserDep = Annotated[User | None, Depends(optional_user)]
AdminUserDep = Annotated[User, Depends(admin_user)]
DbSessionDep = Annotated[Session, Depends(get_db_session)]


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
]
