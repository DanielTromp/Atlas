"""Repository protocol definitions for core domain aggregates."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from .entities import (
    ChatMessageEntity,
    ChatSessionEntity,
    GlobalAPIKeyEntity,
    RolePermissionEntity,
    UserAPIKeyEntity,
    UserEntity,
)


class UserRepository(Protocol):
    """Data access abstraction for user records."""

    def get_by_id(self, user_id: str) -> UserEntity | None:
        ...

    def get_by_username(self, username: str) -> UserEntity | None:
        ...

    def list_all(self) -> list[UserEntity]:
        ...


class UserAPIKeyRepository(Protocol):
    """Access to user-scoped API keys."""

    def list_for_user(self, user_id: str) -> list[UserAPIKeyEntity]:
        ...

    def get(self, user_id: str, provider: str) -> UserAPIKeyEntity | None:
        ...


class GlobalAPIKeyRepository(Protocol):
    """Access to globally-scoped API keys."""

    def list_all(self) -> list[GlobalAPIKeyEntity]:
        ...

    def get(self, provider: str) -> GlobalAPIKeyEntity | None:
        ...


class ChatSessionRepository(Protocol):
    """Access patterns for chat sessions and related messages."""

    def list_sessions(self, user_id: str | None = None) -> list[ChatSessionEntity]:
        ...

    def get_session(self, session_id: str) -> ChatSessionEntity | None:
        ...

    def get_messages(self, session_id: str) -> list[ChatMessageEntity]:
        ...

    def iter_messages(self, session_id: str) -> Iterable[ChatMessageEntity]:
        ...


class RolePermissionRepository(Protocol):
    """Access patterns for role permission definitions."""

    def list_all(self) -> list[RolePermissionEntity]:
        ...

    def get(self, role: str) -> RolePermissionEntity | None:
        ...

    def upsert(self, role: str, label: str, description: str | None, permissions: Iterable[str]) -> RolePermissionEntity:
        ...

__all__ = [
    "ChatSessionRepository",
    "GlobalAPIKeyRepository",
    "RolePermissionRepository",
    "UserAPIKeyRepository",
    "UserRepository",
]
