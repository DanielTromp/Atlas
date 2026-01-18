"""Base adapter protocol for bot platforms."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BotAdapter(ABC):
    """Base class for bot platform adapters.

    Each platform adapter handles:
    - Sending messages to users
    - Sending typing indicators
    - Verifying webhook signatures
    - Platform-specific authentication
    """

    platform: str

    @abstractmethod
    async def send_message(
        self,
        chat_id: str,
        content: Any,
        reply_to: str | None = None,
    ) -> str:
        """Send a message to a chat.

        Args:
            chat_id: Platform-specific chat/channel ID
            content: Message content (format depends on platform)
            reply_to: Optional message ID to reply to

        Returns:
            Platform message ID
        """

    @abstractmethod
    async def send_typing_indicator(self, chat_id: str) -> None:
        """Send a typing indicator to show the bot is working.

        Args:
            chat_id: Platform-specific chat/channel ID
        """

    @abstractmethod
    def verify_webhook_signature(
        self,
        payload: bytes,
        signature: str,
        **kwargs: Any,
    ) -> bool:
        """Verify the authenticity of a webhook request.

        Args:
            payload: Raw request body
            signature: Signature header value
            **kwargs: Additional platform-specific parameters

        Returns:
            True if signature is valid
        """

    @abstractmethod
    async def get_user_info(self, user_id: str) -> dict[str, Any]:
        """Get information about a user.

        Args:
            user_id: Platform-specific user ID

        Returns:
            Dictionary with user information (id, username, display_name, etc.)
        """
