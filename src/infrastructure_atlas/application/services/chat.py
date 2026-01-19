"""Chat history service implementation."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from infrastructure_atlas.domain.repositories import ChatSessionRepository


class DefaultChatHistoryService:
    def __init__(self, chat_repo: ChatSessionRepository) -> None:
        self._chat_repo = chat_repo

    def list_sessions(self, user_id: str | None = None):
        return self._chat_repo.list_sessions(user_id=user_id)

    def list_messages(self, session_id: str):
        return self._chat_repo.get_messages(session_id)

    def get_session(self, session_slug: str):
        return self._chat_repo.get_session(session_slug)


def create_chat_history_service(session: Session | None = None, repo_factory=None) -> DefaultChatHistoryService:
    """Create a chat history service.

    Uses the configured storage backend (MongoDB or SQLite) unless an explicit
    repository factory is provided.

    Args:
        session: SQLAlchemy session (only used for SQLite backend).
        repo_factory: Optional factory for chat repository.

    Returns:
        Configured chat history service instance.
    """
    from infrastructure_atlas.infrastructure.repository_factory import (
        get_chat_session_repository,
        get_storage_backend,
    )

    # If custom factory provided, use it (for testing)
    if repo_factory is not None:
        return DefaultChatHistoryService(repo_factory(session))

    backend = get_storage_backend()

    if backend == "mongodb":
        return DefaultChatHistoryService(get_chat_session_repository())

    # SQLite backend
    if session is None:
        from infrastructure_atlas.db import get_sessionmaker

        Sessionmaker = get_sessionmaker()
        session = Sessionmaker()

    from infrastructure_atlas.infrastructure.db.repositories import SqlAlchemyChatSessionRepository

    return DefaultChatHistoryService(SqlAlchemyChatSessionRepository(session))


__all__ = ["DefaultChatHistoryService", "create_chat_history_service"]
