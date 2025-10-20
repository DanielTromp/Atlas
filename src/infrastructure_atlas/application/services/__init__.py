"""Service interfaces orchestrating domain operations."""
from __future__ import annotations

from typing import Protocol

from infrastructure_atlas.domain.entities import (
    ChatMessageEntity,
    ChatSessionEntity,
    GlobalAPIKeyEntity,
    UserAPIKeyEntity,
    UserEntity,
)

from .admin import AdminService, create_admin_service
from .chat import DefaultChatHistoryService, create_chat_history_service
from .netbox import NetboxExportService
from .users import DefaultUserService, create_user_service
from .vcenter import VCenterService, create_vcenter_service


class UserService(Protocol):
    """High-level operations for user management."""

    def get_current_user(self, user_id: str) -> UserEntity | None:
        ...

    def get_user_by_username(self, username: str) -> UserEntity | None:
        ...

    def list_users(self) -> list[UserEntity]:
        ...

    def list_api_keys(self, user_id: str) -> list[UserAPIKeyEntity]:
        ...

    def get_global_api_key(self, provider: str) -> GlobalAPIKeyEntity | None:
        ...


class ChatHistoryService(Protocol):
    """Read-only operations for chat history retrieval."""

    def list_sessions(self, user_id: str | None = None) -> list[ChatSessionEntity]:
        ...

    def list_messages(self, session_id: str) -> list[ChatMessageEntity]:
        ...

    def get_session(self, session_slug: str) -> ChatSessionEntity | None:
        ...


__all__ = [
    "AdminService",
    "ChatHistoryService",
    "DefaultChatHistoryService",
    "DefaultUserService",
    "NetboxExportService",
    "UserService",
    "VCenterService",
    "create_admin_service",
    "create_chat_history_service",
    "create_user_service",
    "create_vcenter_service",
]
