"""Tests for application service implementations."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy.orm import Session

from enreach_tools.application.services.chat import DefaultChatHistoryService, create_chat_history_service
from enreach_tools.application.services.users import DefaultUserService, create_user_service
from enreach_tools.domain.entities import (
    ChatMessageEntity,
    ChatSessionEntity,
    GlobalAPIKeyEntity,
    UserAPIKeyEntity,
    UserEntity,
)


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class _StubUserRepository:
    user: UserEntity

    def get_by_id(self, user_id: str):
        return self.user if self.user.id == user_id else None

    def get_by_username(self, username: str):
        return self.user if self.user.username == username else None

    def list_all(self):
        return [self.user]


@dataclass(slots=True)
class _StubUserKeyRepository:
    key: UserAPIKeyEntity

    def list_for_user(self, user_id: str):
        return [self.key] if self.key.user_id == user_id else []

    def get(self, user_id: str, provider: str):
        if self.key.user_id == user_id and self.key.provider == provider:
            return self.key
        return None


@dataclass(slots=True)
class _StubGlobalKeyRepository:
    key: GlobalAPIKeyEntity

    def list_all(self):
        return [self.key]

    def get(self, provider: str):
        return self.key if self.key.provider == provider else None


@dataclass(slots=True)
class _StubChatRepository:
    session: ChatSessionEntity
    messages: list[ChatMessageEntity]

    def list_sessions(self, user_id: str | None = None):
        if user_id is None or self.session.user_id == user_id:
            return [self.session]
        return []

    def get_session(self, session_id: str):
        return self.session if self.session.session_id == session_id else None

    def get_messages(self, session_id: str):
        return self.messages if self.session.id == session_id else []

    def iter_messages(self, session_id: str):
        yield from self.get_messages(session_id)


def test_user_service_exposes_repositories():
    now = _now()
    user = UserEntity(
        id="user-1",
        username="alice",
        display_name="Alice",
        email="alice@example.com",
        role="admin",
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    user_key = UserAPIKeyEntity(
        id="key-1",
        user_id="user-1",
        provider="netbox",
        label="NetBox",
        secret="secret",
        created_at=now,
        updated_at=now,
    )
    global_key = GlobalAPIKeyEntity(
        id="global-1",
        provider="openai",
        label="OpenAI",
        secret="secret",
        created_at=now,
        updated_at=now,
    )

    service = DefaultUserService(
        user_repo=_StubUserRepository(user=user),
        user_key_repo=_StubUserKeyRepository(key=user_key),
        global_key_repo=_StubGlobalKeyRepository(key=global_key),
    )

    assert service.get_current_user("user-1").username == "alice"
    assert service.get_user_by_username("alice").id == "user-1"
    assert service.list_users()[0].id == "user-1"
    assert service.list_api_keys("user-1")[0].provider == "netbox"
    assert service.get_global_api_key("openai").label == "OpenAI"


def test_chat_history_service_uses_repository():
    now = _now()
    session_entity = ChatSessionEntity(
        id="session-db-1",
        session_id="slug",
        user_id="user-1",
        title="Chat",
        created_at=now,
        updated_at=now + timedelta(seconds=10),
    )
    messages = [
        ChatMessageEntity(
            id="msg-1",
            session_id="session-db-1",
            role="user",
            content="Hi",
            created_at=now,
        )
    ]

    service = DefaultChatHistoryService(_StubChatRepository(session=session_entity, messages=messages))

    assert service.list_sessions("user-1")[0].title == "Chat"
    assert service.list_messages("session-db-1")[0].content == "Hi"
    assert service.get_session("slug").id == "session-db-1"


def test_create_user_service_accepts_custom_factories():
    now = _now()
    user = UserEntity(
        id="user-1",
        username="alice",
        display_name="Alice",
        email="alice@example.com",
        role="admin",
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    user_repo = _StubUserRepository(user=user)
    user_key_repo = _StubUserKeyRepository(
        key=UserAPIKeyEntity(
            id="key-1",
            user_id="user-1",
            provider="netbox",
            label="NetBox",
            secret="secret",
            created_at=now,
            updated_at=now,
        )
    )
    global_repo = _StubGlobalKeyRepository(
        key=GlobalAPIKeyEntity(
            id="global-1",
            provider="openai",
            label="OpenAI",
            secret="secret",
            created_at=now,
            updated_at=now,
        )
    )

    session = cast(Session, object())

    service = create_user_service(
        session,
        user_repo_factory=lambda s: user_repo,
        user_key_repo_factory=lambda s: user_key_repo,
        global_key_repo_factory=lambda s: global_repo,
    )

    assert service.list_users()[0].id == "user-1"


def test_create_chat_history_service_accepts_custom_factory():
    now = _now()
    session_entity = ChatSessionEntity(
        id="session-db-1",
        session_id="slug",
        user_id="user-1",
        title="Chat",
        created_at=now,
        updated_at=now,
    )
    repo = _StubChatRepository(
        session=session_entity,
        messages=[
            ChatMessageEntity(
                id="msg-1",
                session_id="session-db-1",
                role="user",
                content="Hi",
                created_at=now,
            )
        ],
    )

    session = cast(Session, object())
    service = create_chat_history_service(session, repo_factory=lambda s: repo)
    assert service.get_session("slug").id == "session-db-1"
