"""Domain entities and value objects shared across the application layer.

These dataclasses capture the business-facing shape of our data without tying it
to persistence or transport concerns. They will progressively replace direct
usage of SQLAlchemy models throughout the application and interface layers.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class UserEntity:
    """Domain representation of a user account."""

    id: str
    username: str
    display_name: str | None
    email: str | None
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class UserAPIKeyEntity:
    """Domain representation of a user-scoped API key."""

    id: str
    user_id: str
    provider: str
    label: str | None
    secret: str
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class GlobalAPIKeyEntity:
    """Domain representation of a global API key owned by the system."""

    id: str
    provider: str
    label: str | None
    secret: str
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class ChatSessionEntity:
    """Summary of a chat session for UI/API presentation."""

    id: str
    session_id: str
    user_id: str | None
    title: str
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class ChatMessageEntity:
    """Represents a single chat message in chronological order."""

    id: str
    session_id: str
    role: str
    content: str
    created_at: datetime
