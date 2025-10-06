"""Tests for DTO conversion convenience functions."""
from datetime import UTC, datetime

from enreach_tools.application.dto import (
    chat_message_to_dto,
    chat_messages_to_dto,
    chat_session_to_dto,
    chat_sessions_to_dto,
    global_key_to_dto,
    user_key_to_dto,
    user_keys_to_dto,
    user_to_dto,
    users_to_dto,
)
from enreach_tools.domain.entities import (
    ChatMessageEntity,
    ChatSessionEntity,
    GlobalAPIKeyEntity,
    UserAPIKeyEntity,
    UserEntity,
)


def _now() -> datetime:
    return datetime.now(UTC)


def test_user_dto_conversions_roundtrip():
    entity = UserEntity(
        id="user-1",
        username="alice",
        display_name="Alice",
        email="alice@example.com",
        role="admin",
        permissions=frozenset({"chat.use"}),
        is_active=True,
        created_at=_now(),
        updated_at=_now(),
    )
    dto = user_to_dto(entity)
    assert dto.username == "alice"
    assert dto.dict_clean()["role"] == "admin"
    assert users_to_dto([entity])[0].username == "alice"


def test_api_key_dto_helpers():
    entity = UserAPIKeyEntity(
        id="key-1",
        user_id="user-1",
        provider="netbox",
        label="NetBox",
        secret="secret",
        created_at=_now(),
        updated_at=_now(),
    )
    dto = user_key_to_dto(entity)
    assert dto.provider == "netbox"
    assert user_keys_to_dto([entity])[0].provider == "netbox"


def test_global_key_dto_helper():
    entity = GlobalAPIKeyEntity(
        id="global-1",
        provider="openai",
        label="OpenAI",
        secret="secret",
        created_at=_now(),
        updated_at=_now(),
    )
    assert global_key_to_dto(entity).provider == "openai"


def test_chat_dto_helpers():
    session_entity = ChatSessionEntity(
        id="session-1",
        session_id="slug",
        user_id="user-1",
        title="Chat",
        created_at=_now(),
        updated_at=_now(),
    )
    message_entity = ChatMessageEntity(
        id="msg-1",
        session_id="session-1",
        role="assistant",
        content="Hello",
        created_at=_now(),
    )
    assert chat_session_to_dto(session_entity).title == "Chat"
    assert chat_sessions_to_dto([session_entity])[0].session_id == "slug"
    assert chat_message_to_dto(message_entity).role == "assistant"
    assert chat_messages_to_dto([message_entity])[0].content == "Hello"
