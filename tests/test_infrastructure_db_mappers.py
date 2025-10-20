"""Unit tests for SQLAlchemy-to-domain mappers."""
from datetime import UTC, datetime

from infrastructure_atlas.db import models
from infrastructure_atlas.infrastructure.db import mappers


def _now() -> datetime:
    return datetime.now(UTC)


def test_user_to_entity_roundtrip():
    record = models.User(
        id="user-1",
        username="alice",
        display_name="Alice",
        email="alice@example.com",
        role="admin",
        password_hash=None,
        is_active=True,
        created_at=_now(),
        updated_at=_now(),
    )
    entity = mappers.user_to_entity(record)
    assert entity.username == "alice"
    assert entity.display_name == "Alice"
    assert entity.is_active is True


def test_chat_message_to_entity_preserves_payload():
    record = models.ChatMessage(
        id="msg-1",
        session_id="session-1",
        role="assistant",
        content="Hello!",
        created_at=_now(),
    )
    entity = mappers.chat_message_to_entity(record)
    assert entity.session_id == "session-1"
    assert entity.role == "assistant"
    assert entity.content == "Hello!"
