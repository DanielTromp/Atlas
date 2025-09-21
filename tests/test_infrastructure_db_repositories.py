"""Integration-style tests for SQLAlchemy repository implementations."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from enreach_tools.db import models
from enreach_tools.infrastructure.db.repositories import (
    SqlAlchemyChatSessionRepository,
    SqlAlchemyGlobalAPIKeyRepository,
    SqlAlchemyUserAPIKeyRepository,
    SqlAlchemyUserRepository,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _setup_session():
    engine = create_engine("sqlite:///:memory:", future=True)
    models.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    return Session()


def test_user_repository_lookup():
    with _setup_session() as session:
        created = _now()
        user = models.User(
            id="user-1",
            username="alice",
            display_name="Alice",
            email="alice@example.com",
            role="admin",
            password_hash=None,
            is_active=True,
            created_at=created,
            updated_at=created,
        )
        session.add(user)
        session.commit()

        repo = SqlAlchemyUserRepository(session)
        assert repo.get_by_username("alice") is not None
        assert repo.get_by_id("user-1") is not None
        assert repo.get_by_username("missing") is None


def test_user_api_key_repository_filters_by_user():
    with _setup_session() as session:
        now = _now()
        other = now + timedelta(seconds=1)
        user = models.User(
            id="user-1",
            username="alice",
            display_name=None,
            email=None,
            role="member",
            password_hash=None,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        key = models.UserAPIKey(
            id="key-1",
            user_id="user-1",
            provider="netbox",
            label="NetBox",
            secret="secret",
            created_at=now,
            updated_at=other,
        )
        session.add_all([user, key])
        session.commit()

        repo = SqlAlchemyUserAPIKeyRepository(session)
        keys = repo.list_for_user("user-1")
        assert len(keys) == 1 and keys[0].provider == "netbox"
        assert repo.get("user-1", "netbox") is not None
        assert repo.get("user-1", "missing") is None


def test_global_api_key_repository_lookup():
    with _setup_session() as session:
        now = _now()
        key = models.GlobalAPIKey(
            id="global-1",
            provider="openai",
            label="OpenAI",
            secret="secret",
            created_at=now,
            updated_at=now,
        )
        session.add(key)
        session.commit()

        repo = SqlAlchemyGlobalAPIKeyRepository(session)
        assert repo.get("openai") is not None
        assert repo.list_all()[0].provider == "openai"


def test_chat_session_repository_message_order():
    with _setup_session() as session:
        now = _now()
        session_model = models.ChatSession(
            id="session-db-1",
            session_id="session-1",
            user_id="user-1",
            title="Chat",
            created_at=now,
            updated_at=now,
        )
        msg1 = models.ChatMessage(
            id="msg-1",
            session_id="session-db-1",
            role="user",
            content="Hi",
            created_at=now,
        )
        msg2 = models.ChatMessage(
            id="msg-2",
            session_id="session-db-1",
            role="assistant",
            content="Hello",
            created_at=now + timedelta(seconds=1),
        )
        session.add_all([session_model, msg1, msg2])
        session.commit()

        repo = SqlAlchemyChatSessionRepository(session)
        messages = repo.get_messages("session-db-1")
        assert [m.id for m in messages] == ["msg-1", "msg-2"]
        session_entity = repo.get_session("session-1")
        assert session_entity and session_entity.title == "Chat"
