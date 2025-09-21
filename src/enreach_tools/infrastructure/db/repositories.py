"""SQLAlchemy-backed repository implementations."""
from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from enreach_tools.db import models
from enreach_tools.domain.repositories import (
    ChatSessionRepository,
    GlobalAPIKeyRepository,
    UserAPIKeyRepository,
    UserRepository,
)

from . import mappers


class SqlAlchemyUserRepository(UserRepository):
    """Read-only user repository backed by SQLAlchemy."""

    def __init__(self, session: Session):
        self._session = session

    def get_by_id(self, user_id: str):
        record = self._session.get(models.User, user_id)
        return mappers.user_to_entity(record) if record else None

    def get_by_username(self, username: str):
        stmt = select(models.User).where(models.User.username == username)
        record = self._session.execute(stmt).scalar_one_or_none()
        return mappers.user_to_entity(record) if record else None

    def list_all(self):
        stmt = select(models.User).order_by(models.User.created_at.asc())
        records = self._session.execute(stmt).scalars().all()
        return [mappers.user_to_entity(record) for record in records]


class SqlAlchemyUserAPIKeyRepository(UserAPIKeyRepository):
    """Repository for user-scoped API keys."""

    def __init__(self, session: Session):
        self._session = session

    def list_for_user(self, user_id: str):
        stmt = select(models.UserAPIKey).where(models.UserAPIKey.user_id == user_id)
        records = self._session.execute(stmt).scalars().all()
        return [mappers.user_api_key_to_entity(record) for record in records]

    def get(self, user_id: str, provider: str):
        stmt = select(models.UserAPIKey).where(
            models.UserAPIKey.user_id == user_id,
            models.UserAPIKey.provider == provider,
        )
        record = self._session.execute(stmt).scalar_one_or_none()
        return mappers.user_api_key_to_entity(record) if record else None


class SqlAlchemyGlobalAPIKeyRepository(GlobalAPIKeyRepository):
    """Repository for globally-scoped API keys."""

    def __init__(self, session: Session):
        self._session = session

    def list_all(self):
        stmt = select(models.GlobalAPIKey).order_by(models.GlobalAPIKey.provider.asc())
        records = self._session.execute(stmt).scalars().all()
        return [mappers.global_api_key_to_entity(record) for record in records]

    def get(self, provider: str):
        stmt = select(models.GlobalAPIKey).where(models.GlobalAPIKey.provider == provider)
        record = self._session.execute(stmt).scalar_one_or_none()
        return mappers.global_api_key_to_entity(record) if record else None


class SqlAlchemyChatSessionRepository(ChatSessionRepository):
    """Repository for chat sessions and messages."""

    def __init__(self, session: Session):
        self._session = session

    def list_sessions(self, user_id: str | None = None):
        stmt = select(models.ChatSession).order_by(models.ChatSession.updated_at.desc())
        if user_id:
            stmt = stmt.where(models.ChatSession.user_id == user_id)
        records = self._session.execute(stmt).scalars().all()
        return [mappers.chat_session_to_entity(record) for record in records]

    def get_session(self, session_id: str):
        stmt = select(models.ChatSession).where(models.ChatSession.session_id == session_id)
        record = self._session.execute(stmt).scalar_one_or_none()
        return mappers.chat_session_to_entity(record) if record else None

    def get_messages(self, session_id: str):
        stmt = (
            select(models.ChatMessage)
            .where(models.ChatMessage.session_id == session_id)
            .order_by(models.ChatMessage.created_at.asc())
        )
        records = self._session.execute(stmt).scalars().all()
        return [mappers.chat_message_to_entity(record) for record in records]

    def iter_messages(self, session_id: str):
        stmt = (
            select(models.ChatMessage)
            .where(models.ChatMessage.session_id == session_id)
            .order_by(models.ChatMessage.created_at.asc())
        )
        result: Iterable[models.ChatMessage] = self._session.execute(stmt).scalars()
        return mappers.iter_chat_messages(result)


__all__ = [
    "SqlAlchemyChatSessionRepository",
    "SqlAlchemyGlobalAPIKeyRepository",
    "SqlAlchemyUserAPIKeyRepository",
    "SqlAlchemyUserRepository",
]
