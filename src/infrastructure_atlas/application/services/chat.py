"""Chat history service implementation."""
from __future__ import annotations

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


def create_chat_history_service(session: Session, repo_factory=None) -> DefaultChatHistoryService:
    if repo_factory is None:
        from infrastructure_atlas.infrastructure.db.repositories import SqlAlchemyChatSessionRepository

        repo_factory = SqlAlchemyChatSessionRepository
    return DefaultChatHistoryService(repo_factory(session))


__all__ = ["DefaultChatHistoryService", "create_chat_history_service"]
