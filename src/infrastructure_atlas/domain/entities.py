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
    permissions: frozenset[str]
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
class RolePermissionEntity:
    """Domain representation of an assignable role's capabilities."""

    role: str
    label: str
    description: str | None
    permissions: frozenset[str]
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
    # AI Chat fields
    context_variables: dict | None = None
    agent_config_id: str | None = None
    provider_type: str | None = None
    model: str | None = None


@dataclass(slots=True)
class ChatMessageEntity:
    """Represents a single chat message in chronological order."""

    id: str
    session_id: str
    role: str
    content: str
    created_at: datetime
    # AI Chat fields for tool calls
    message_type: str | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    metadata_json: dict | None = None


@dataclass(slots=True)
class VCenterConfigEntity:
    """Configuration details for connecting to a vCenter instance."""

    id: str
    name: str
    base_url: str
    username: str
    verify_ssl: bool
    is_esxi: bool
    password_secret: str
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class ForemanConfigEntity:
    """Configuration details for connecting to a Foreman instance."""

    id: str
    name: str
    base_url: str
    username: str
    token_secret: str
    verify_ssl: bool
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class PuppetConfigEntity:
    """Configuration details for connecting to a Puppet Git repository."""

    id: str
    name: str
    remote_url: str
    branch: str
    ssh_key_secret: str | None
    local_path: str | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Bot Platform Entities
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class BotPlatformAccountEntity:
    """Links external platform users (Telegram, Slack, Teams) to Atlas users."""

    id: int
    user_id: str
    platform: str  # "telegram", "slack", "teams"
    platform_user_id: str
    platform_username: str | None
    verified: bool
    verification_code: str | None
    verification_expires: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class BotConversationEntity:
    """Tracks bot conversations for context and history."""

    id: int
    platform: str
    platform_conversation_id: str
    platform_account_id: int
    agent_id: str | None
    session_id: str | None
    created_at: datetime
    last_message_at: datetime


@dataclass(slots=True)
class BotMessageEntity:
    """Logs all bot messages for web GUI visibility and debugging."""

    id: int
    conversation_id: int
    direction: str  # "inbound" or "outbound"
    content: str
    platform_message_id: str | None
    agent_id: str | None
    tool_calls: list[dict] | None
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    duration_ms: int | None
    created_at: datetime


@dataclass(slots=True)
class BotWebhookConfigEntity:
    """Platform webhook configurations (admin-managed)."""

    id: int
    platform: str
    enabled: bool
    webhook_secret: str | None
    bot_token_secret: str
    extra_config: dict | None
    created_at: datetime
    updated_at: datetime
