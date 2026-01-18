"""Telegram bot adapter using the Telegram Bot API.

This adapter handles:
- Sending messages with MarkdownV2 formatting
- Typing indicators
- Webhook signature verification
- User info retrieval
"""

from __future__ import annotations

import hmac
import os
from typing import Any

import httpx

from infrastructure_atlas.bots.adapters.base import BotAdapter
from infrastructure_atlas.bots.formatters import TelegramFormatter
from infrastructure_atlas.infrastructure.logging import get_logger

logger = get_logger(__name__)


class TelegramAdapter(BotAdapter):
    """Telegram Bot API adapter.

    Uses the Telegram Bot API directly via HTTP requests.
    Supports MarkdownV2 formatting and inline keyboards.
    """

    platform = "telegram"

    def __init__(self, bot_token: str | None = None):
        """Initialize the Telegram adapter.

        Args:
            bot_token: Telegram bot token. If not provided, uses TELEGRAM_BOT_TOKEN env var.
        """
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.api_base = f"https://api.telegram.org/bot{self.bot_token}"
        self.formatter = TelegramFormatter()

    async def send_message(
        self,
        chat_id: str,
        content: Any,
        reply_to: str | None = None,
    ) -> str:
        """Send a message to a Telegram chat.

        Args:
            chat_id: Telegram chat ID
            content: Message content (string for text, already formatted)
            reply_to: Optional message ID to reply to

        Returns:
            Telegram message ID
        """
        url = f"{self.api_base}/sendMessage"

        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": content if isinstance(content, str) else str(content),
            "parse_mode": "MarkdownV2",
        }

        if reply_to:
            payload["reply_to_message_id"] = reply_to

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=30.0)
            data = response.json()

            if not data.get("ok"):
                error_desc = data.get("description", "Unknown error")
                logger.error(f"Telegram send_message failed: {error_desc}")

                # If MarkdownV2 parsing failed, retry without formatting
                if "can't parse entities" in error_desc.lower():
                    del payload["parse_mode"]  # Remove parse_mode entirely
                    # Unescape markdown characters for plain text
                    payload["text"] = self._unescape_markdown(payload["text"])
                    response = await client.post(url, json=payload, timeout=30.0)
                    data = response.json()

            if data.get("ok"):
                return str(data["result"]["message_id"])
            else:
                raise RuntimeError(f"Failed to send Telegram message: {data.get('description')}")

    def _unescape_markdown(self, text: str) -> str:
        """Remove MarkdownV2 escaping from text."""
        import re

        # Remove backslash escapes
        return re.sub(r"\\(.)", r"\1", text)

    async def send_typing_indicator(self, chat_id: str) -> None:
        """Send a typing indicator to show the bot is working.

        Args:
            chat_id: Telegram chat ID
        """
        url = f"{self.api_base}/sendChatAction"
        payload = {
            "chat_id": chat_id,
            "action": "typing",
        }

        async with httpx.AsyncClient() as client:
            await client.post(url, json=payload, timeout=10.0)

    def verify_webhook_signature(
        self,
        payload: bytes,
        signature: str,
        **kwargs: Any,
    ) -> bool:
        """Verify Telegram webhook signature.

        Telegram uses a different approach - it sends a secret_token header
        that must match the configured webhook secret.

        Args:
            payload: Raw request body (unused for Telegram)
            signature: The X-Telegram-Bot-Api-Secret-Token header value
            **kwargs: Additional parameters (webhook_secret required)

        Returns:
            True if signature matches the configured secret
        """
        webhook_secret = kwargs.get("webhook_secret", "")
        if not webhook_secret:
            # No secret configured, accept all requests (not recommended for production)
            logger.warning("Telegram webhook secret not configured")
            return True

        return hmac.compare_digest(signature, webhook_secret)

    async def get_user_info(self, user_id: str) -> dict[str, Any]:
        """Get information about a Telegram user.

        Note: Telegram doesn't provide a direct getUserInfo endpoint.
        This returns limited info based on what we have.

        Args:
            user_id: Telegram user ID

        Returns:
            Dictionary with user information
        """
        # Telegram doesn't have a direct user lookup API
        # We can only get user info from incoming messages
        return {
            "id": user_id,
            "platform": "telegram",
        }

    async def get_bot_info(self) -> dict[str, Any]:
        """Get information about the bot itself.

        Returns:
            Dictionary with bot information
        """
        url = f"{self.api_base}/getMe"

        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10.0)
            data = response.json()

            if data.get("ok"):
                return data["result"]
            else:
                raise RuntimeError(f"Failed to get bot info: {data.get('description')}")

    async def set_webhook(
        self,
        webhook_url: str,
        secret_token: str | None = None,
        drop_pending_updates: bool = False,
    ) -> bool:
        """Set the webhook URL for receiving updates.

        Args:
            webhook_url: HTTPS URL to receive webhook updates
            secret_token: Optional secret token for webhook verification
            drop_pending_updates: Whether to drop pending updates

        Returns:
            True if webhook was set successfully
        """
        url = f"{self.api_base}/setWebhook"
        payload: dict[str, Any] = {
            "url": webhook_url,
            "drop_pending_updates": drop_pending_updates,
        }

        if secret_token:
            payload["secret_token"] = secret_token

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=30.0)
            data = response.json()

            if data.get("ok"):
                logger.info(f"Telegram webhook set to: {webhook_url}")
                return True
            else:
                logger.error(f"Failed to set Telegram webhook: {data.get('description')}")
                return False

    async def delete_webhook(self, drop_pending_updates: bool = False) -> bool:
        """Delete the current webhook.

        Args:
            drop_pending_updates: Whether to drop pending updates

        Returns:
            True if webhook was deleted successfully
        """
        url = f"{self.api_base}/deleteWebhook"
        payload = {"drop_pending_updates": drop_pending_updates}

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=30.0)
            data = response.json()

            if data.get("ok"):
                logger.info("Telegram webhook deleted")
                return True
            else:
                logger.error(f"Failed to delete Telegram webhook: {data.get('description')}")
                return False

    async def get_webhook_info(self) -> dict[str, Any]:
        """Get current webhook information.

        Returns:
            Dictionary with webhook information
        """
        url = f"{self.api_base}/getWebhookInfo"

        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10.0)
            data = response.json()

            if data.get("ok"):
                return data["result"]
            else:
                raise RuntimeError(f"Failed to get webhook info: {data.get('description')}")


class TelegramWebhookHandler:
    """Handler for Telegram webhook updates.

    Processes incoming Telegram updates and routes them appropriately:
    - /start, /help, /link commands
    - Regular messages to the bot orchestrator
    - Callback queries from inline keyboards
    """

    def __init__(
        self,
        adapter: TelegramAdapter,
        orchestrator: Any,  # BotOrchestrator - avoid circular import
        linking_service: Any,  # UserLinkingService
    ):
        """Initialize the webhook handler.

        Args:
            adapter: Telegram adapter for sending responses
            orchestrator: Bot orchestrator for processing messages
            linking_service: User linking service for account management
        """
        self.adapter = adapter
        self.orchestrator = orchestrator
        self.linking = linking_service

    async def handle_update(self, update: dict[str, Any]) -> None:
        """Process a Telegram webhook update.

        Args:
            update: Telegram Update object
        """
        # Handle different update types
        if "message" in update:
            await self._handle_message(update["message"])
        elif "callback_query" in update:
            await self._handle_callback_query(update["callback_query"])
        else:
            logger.debug(f"Ignoring update type: {list(update.keys())}")

    async def _handle_message(self, message: dict[str, Any]) -> None:
        """Handle an incoming message.

        Args:
            message: Telegram Message object
        """
        chat_id = str(message["chat"]["id"])
        user_id = str(message["from"]["id"])
        username = message["from"].get("username")
        text = message.get("text", "")
        message_id = str(message["message_id"])

        # Handle commands
        if text.startswith("/"):
            await self._handle_command(chat_id, user_id, username, text, message_id)
            return

        # Regular message - route to orchestrator
        try:
            async for response in self.orchestrator.process_message(
                platform="telegram",
                platform_user_id=user_id,
                platform_conversation_id=chat_id,
                message=text,
                platform_message_id=message_id,
                platform_username=username,
            ):
                if response.type.value == "typing":
                    await self.adapter.send_typing_indicator(chat_id)
                elif response.type.value == "text" and response.formatted:
                    await self.adapter.send_message(
                        chat_id=chat_id,
                        content=response.formatted.content,
                        reply_to=message_id,
                    )
                elif response.type.value == "error" and response.formatted:
                    await self.adapter.send_message(
                        chat_id=chat_id,
                        content=response.formatted.content,
                        reply_to=message_id,
                    )
                elif response.type.value == "unauthorized":
                    await self.adapter.send_message(
                        chat_id=chat_id,
                        content=response.formatted.content if response.formatted else response.content,
                        reply_to=message_id,
                    )

        except Exception as e:
            logger.error(f"Error processing Telegram message: {e}", exc_info=True)
            error_msg = self.adapter.formatter.format_error(f"An error occurred: {e}")
            await self.adapter.send_message(chat_id, error_msg.content, reply_to=message_id)

    async def _handle_command(
        self,
        chat_id: str,
        user_id: str,
        username: str | None,
        text: str,
        message_id: str,
    ) -> None:
        """Handle a bot command.

        Args:
            chat_id: Telegram chat ID
            user_id: Telegram user ID
            username: Telegram username
            text: Full message text (starting with /)
            message_id: Message ID for replies
        """
        # Parse command and arguments
        parts = text.split(maxsplit=1)
        command = parts[0].lower().split("@")[0]  # Remove @botname suffix
        args = parts[1] if len(parts) > 1 else ""

        if command == "/start":
            await self._cmd_start(chat_id, user_id, username, message_id)
        elif command == "/help":
            await self._cmd_help(chat_id, message_id)
        elif command == "/link":
            await self._cmd_link(chat_id, user_id, username, args, message_id)
        elif command == "/agents":
            await self._cmd_agents(chat_id, message_id)
        elif command == "/status":
            await self._cmd_status(chat_id, user_id, message_id)
        else:
            # Unknown command - send help
            await self._cmd_help(chat_id, message_id)

    async def _cmd_start(
        self,
        chat_id: str,
        user_id: str,
        username: str | None,
        message_id: str,
    ) -> None:
        """Handle /start command."""
        # Check if user is already linked
        account = self.linking.get_linked_account("telegram", user_id)

        if account:
            welcome = (
                "Welcome back\\! Your account is linked to Atlas\\.\n\n"
                "You can chat with me directly or mention an agent:\n"
                "• `@triage <message>` \\- Ticket analysis\n"
                "• `@engineer <message>` \\- Technical investigation\n"
                "• `@reviewer <message>` \\- Quality review\n\n"
                "Type /help for more information\\."
            )
        else:
            welcome = (
                "Welcome to Atlas Bot\\!\n\n"
                "To use this bot, you need to link your Telegram account to Atlas\\.\n\n"
                "1\\. Log in to Atlas web UI\n"
                "2\\. Go to your profile settings\n"
                "3\\. Generate a verification code for Telegram\n"
                "4\\. Send /link <code> here\n\n"
                "Example: `/link 123456`"
            )

        await self.adapter.send_message(chat_id, welcome, reply_to=message_id)

    async def _cmd_help(self, chat_id: str, message_id: str) -> None:
        """Handle /help command."""
        help_text = (
            "*Atlas Bot Help*\n\n"
            "*Commands:*\n"
            "• `/start` \\- Welcome message\n"
            "• `/help` \\- Show this help\n"
            "• `/link <code>` \\- Link your account\n"
            "• `/agents` \\- List available agents\n"
            "• `/status` \\- Check your account status\n\n"
            "*Chatting with Agents:*\n"
            "• Send a message directly to chat with the default agent\n"
            "• Use `@agent\\_name <message>` to chat with a specific agent\n\n"
            "*Examples:*\n"
            "• `What new tickets are there\\?`\n"
            "• `@triage analyze ticket ESD\\-123`\n"
            "• `@engineer check server status for web\\-01`"
        )
        await self.adapter.send_message(chat_id, help_text, reply_to=message_id)

    async def _cmd_link(
        self,
        chat_id: str,
        user_id: str,
        username: str | None,
        code: str,
        message_id: str,
    ) -> None:
        """Handle /link command."""
        if not code.strip():
            error = (
                "Please provide a verification code\\.\n\n"
                "Usage: `/link <code>`\n"
                "Example: `/link 123456`"
            )
            await self.adapter.send_message(chat_id, error, reply_to=message_id)
            return

        # Try to verify the code
        account = self.linking.verify_code(
            platform="telegram",
            platform_user_id=user_id,
            code=code.strip(),
            platform_username=username,
        )

        if account:
            success = (
                "Your Telegram account has been successfully linked to Atlas\\!\n\n"
                "You can now chat with Atlas agents\\. Try asking a question or use "
                "`@agent\\_name <message>` to chat with a specific agent\\."
            )
            await self.adapter.send_message(chat_id, success, reply_to=message_id)
        else:
            error = (
                "Invalid or expired verification code\\.\n\n"
                "Please generate a new code from the Atlas web UI and try again\\."
            )
            await self.adapter.send_message(chat_id, error, reply_to=message_id)

    async def _cmd_agents(self, chat_id: str, message_id: str) -> None:
        """Handle /agents command."""
        agents = self.orchestrator.get_available_agents()

        lines = ["*Available Agents:*\n"]
        for agent in agents:
            # Escape special characters for MarkdownV2
            desc = agent["description"].replace("-", "\\-").replace(".", "\\.").replace("(", "\\(").replace(")", "\\)")
            lines.append(f"• *{agent['id']}* \\- {desc}")

        lines.append("\nUse `@agent\\\\_id <message>` to chat with a specific agent\\.")

        await self.adapter.send_message(chat_id, "\n".join(lines), reply_to=message_id)

    async def _cmd_status(self, chat_id: str, user_id: str, message_id: str) -> None:
        """Handle /status command."""
        account = self.linking.get_linked_account("telegram", user_id)

        if account:
            username = account.user.username if account.user else "Unknown"
            date_str = account.created_at.strftime("%Y-%m-%d").replace("-", "\\-")
            status = (
                "*Account Status:* Linked\n"
                f"*Atlas User:* {username}\n"
                f"*Linked Since:* {date_str}"
            )
        else:
            status = (
                "*Account Status:* Not Linked\n\n"
                "Use `/link <code>` to link your account\\."
            )

        await self.adapter.send_message(chat_id, status, reply_to=message_id)

    async def _handle_callback_query(self, callback_query: dict[str, Any]) -> None:
        """Handle a callback query from an inline keyboard.

        Args:
            callback_query: Telegram CallbackQuery object
        """
        # For now, just acknowledge the callback
        # Future: handle interactive buttons
        query_id = callback_query["id"]
        data = callback_query.get("data", "")

        logger.debug(f"Received callback query: {data}")

        # Acknowledge the callback
        url = f"{self.adapter.api_base}/answerCallbackQuery"
        payload = {"callback_query_id": query_id}

        async with httpx.AsyncClient() as client:
            await client.post(url, json=payload, timeout=10.0)
