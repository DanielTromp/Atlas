"""DTOs for chat session and message transport."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from infrastructure_atlas.domain.entities import ChatMessageEntity, ChatSessionEntity

from .base import DomainModel


class ChatSessionDTO(DomainModel):
    id: str
    session_id: str
    user_id: str | None = None
    title: str
    created_at: datetime
    updated_at: datetime


class ChatMessageDTO(DomainModel):
    id: str
    session_id: str
    role: str
    content: str
    created_at: datetime


def chat_session_to_dto(entity: ChatSessionEntity) -> ChatSessionDTO:
    return ChatSessionDTO.model_validate(entity)


def chat_sessions_to_dto(entities: Iterable[ChatSessionEntity]) -> list[ChatSessionDTO]:
    return [chat_session_to_dto(entity) for entity in entities]


def chat_message_to_dto(entity: ChatMessageEntity) -> ChatMessageDTO:
    return ChatMessageDTO.model_validate(entity)


def chat_messages_to_dto(entities: Iterable[ChatMessageEntity]) -> list[ChatMessageDTO]:
    return [chat_message_to_dto(entity) for entity in entities]
