"""Slack bot adapter using Socket Mode (no public endpoints required).

This module provides a Slack bot implementation using Socket Mode which
creates a WebSocket connection from the server to Slack, eliminating the
need for public webhook URLs.

Required Slack App permissions (OAuth Scopes):
- Bot Token Scopes:
  - app_mentions:read - Receive @mentions
  - chat:write - Send messages
  - im:history - Read DMs
  - im:read - View basic DM info
  - im:write - Start DMs
  - users:read - Get user info

- Event Subscriptions (Socket Mode):
  - message.im - DMs to the bot
  - app_mention - @mentions in channels
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from infrastructure_atlas.bots.adapters.base import BotAdapter
from infrastructure_atlas.bots.formatters import SlackFormatter
from infrastructure_atlas.infrastructure.logging import get_logger

if TYPE_CHECKING:
    from slack_sdk import WebClient
    from slack_sdk.socket_mode import SocketModeClient

logger = get_logger(__name__)


class SlackAdapter(BotAdapter):
    """Slack bot adapter using Web API.

    Handles sending messages and managing Slack-specific operations.
    """

    platform = "slack"

    def __init__(
        self,
        bot_token: str | None = None,
        app_token: str | None = None,
    ):
        """Initialize the Slack adapter.

        Args:
            bot_token: Bot User OAuth Token (xoxb-...). Uses SLACK_BOT_TOKEN env var if not provided.
            app_token: App-Level Token for Socket Mode (xapp-...). Uses SLACK_APP_TOKEN env var if not provided.
        """
        self.bot_token = bot_token or os.getenv("SLACK_BOT_TOKEN", "")
        self.app_token = app_token or os.getenv("SLACK_APP_TOKEN", "")
        self.formatter = SlackFormatter()
        self._client: WebClient | None = None
        self._bot_user_id: str | None = None

    def _get_client(self) -> "WebClient":
        """Get or create Slack WebClient."""
        if self._client is None:
            from slack_sdk import WebClient

            self._client = WebClient(token=self.bot_token)
        return self._client

    async def send_message(
        self,
        chat_id: str,
        content: Any,
        reply_to: str | None = None,
    ) -> str:
        """Send a message to a Slack channel/DM.

        Args:
            chat_id: Channel ID or user ID
            content: Message content (text string or Block Kit dict)
            reply_to: Optional thread timestamp to reply to

        Returns:
            Message timestamp (Slack's message ID)
        """
        client = self._get_client()

        kwargs: dict[str, Any] = {"channel": chat_id}

        if reply_to:
            kwargs["thread_ts"] = reply_to

        # Handle different content formats
        if isinstance(content, dict):
            if "blocks" in content:
                kwargs["blocks"] = content["blocks"]
                # Extract text fallback from blocks for notifications
                kwargs["text"] = self._extract_text_fallback(content["blocks"])
            else:
                kwargs["text"] = str(content)
        else:
            kwargs["text"] = str(content)

        try:
            response = client.chat_postMessage(**kwargs)
            return response.get("ts", "")
        except Exception as e:
            logger.error(f"Failed to send Slack message: {e}")
            raise

    def _extract_text_fallback(self, blocks: list[dict]) -> str:
        """Extract plain text fallback from Block Kit blocks."""
        texts = []
        for block in blocks:
            if block.get("type") == "section":
                text_obj = block.get("text", {})
                if isinstance(text_obj, dict):
                    texts.append(text_obj.get("text", ""))
            elif block.get("type") == "header":
                text_obj = block.get("text", {})
                if isinstance(text_obj, dict):
                    texts.append(text_obj.get("text", ""))
        return " ".join(texts)[:150] or "New message"

    async def send_typing_indicator(self, chat_id: str) -> None:
        """Slack doesn't have a typing indicator API like Telegram.

        We could potentially use a reaction or ephemeral message,
        but for now we'll just pass.
        """
        # Slack doesn't support typing indicators for bots
        pass

    def verify_webhook_signature(
        self,
        payload: bytes,
        signature: str,
        **kwargs: Any,
    ) -> bool:
        """Verify Slack request signature.

        For Socket Mode, signature verification is handled by the SDK.
        This method is kept for webhook fallback compatibility.
        """
        from slack_sdk.signature import SignatureVerifier

        signing_secret = kwargs.get("signing_secret") or os.getenv("SLACK_SIGNING_SECRET", "")
        timestamp = kwargs.get("timestamp", "")

        if not signing_secret:
            logger.warning("SLACK_SIGNING_SECRET not set, skipping signature verification")
            return True

        verifier = SignatureVerifier(signing_secret)
        return verifier.is_valid(
            body=payload.decode("utf-8"),
            timestamp=timestamp,
            signature=signature,
        )

    async def get_user_info(self, user_id: str) -> dict[str, Any]:
        """Get information about a Slack user.

        Args:
            user_id: Slack user ID (U...)

        Returns:
            Dictionary with user information
        """
        client = self._get_client()

        try:
            response = client.users_info(user=user_id)
            user = response.get("user", {})
            profile = user.get("profile", {})

            return {
                "id": user.get("id", ""),
                "username": user.get("name", ""),
                "display_name": profile.get("display_name") or profile.get("real_name") or user.get("name", ""),
                "email": profile.get("email", ""),
                "is_bot": user.get("is_bot", False),
            }
        except Exception as e:
            logger.error(f"Failed to get Slack user info: {e}")
            return {"id": user_id, "username": "", "display_name": "Unknown"}

    async def get_bot_info(self) -> dict[str, Any]:
        """Get information about this bot.

        Returns:
            Dictionary with bot user ID, name, etc.
        """
        client = self._get_client()

        try:
            response = client.auth_test()
            self._bot_user_id = response.get("user_id", "")

            return {
                "user_id": response.get("user_id", ""),
                "bot_id": response.get("bot_id", ""),
                "team_id": response.get("team_id", ""),
                "team": response.get("team", ""),
                "username": response.get("user", ""),
                "url": response.get("url", ""),
            }
        except Exception as e:
            logger.error(f"Failed to get bot info: {e}")
            raise

    def get_bot_user_id(self) -> str:
        """Get the bot's user ID (cached after first call)."""
        if not self._bot_user_id:
            import asyncio
            asyncio.get_event_loop().run_until_complete(self.get_bot_info())
        return self._bot_user_id or ""


class SlackWebhookHandler:
    """Handler for processing Slack events.

    This class processes incoming Slack events (messages, mentions)
    and coordinates with the orchestrator to generate responses.
    """

    def __init__(
        self,
        adapter: SlackAdapter,
        orchestrator: Any,  # BotOrchestrator
        linking_service: Any,  # UserLinkingService
    ):
        """Initialize the handler.

        Args:
            adapter: Slack adapter for sending messages
            orchestrator: Bot orchestrator for processing messages
            linking_service: Service for user account linking
        """
        self.adapter = adapter
        self.orchestrator = orchestrator
        self.linking = linking_service
        self.formatter = SlackFormatter()

    async def handle_message(self, event: dict[str, Any], say: Any) -> None:
        """Handle an incoming message event.

        Args:
            event: Slack message event
            say: Function to send messages back
        """
        # Ignore bot messages to prevent loops
        if event.get("bot_id") or event.get("subtype") == "bot_message":
            return

        user_id = event.get("user", "")
        channel_id = event.get("channel", "")
        text = event.get("text", "").strip()
        thread_ts = event.get("thread_ts") or event.get("ts")

        if not text or not user_id:
            return

        logger.info(f"Slack message from {user_id} in {channel_id}: {text[:50]}...")

        # Check for commands
        if text.startswith("/"):
            await self._handle_command(text, user_id, channel_id, say, thread_ts)
            return

        # Process regular message through orchestrator
        await self._process_message(text, user_id, channel_id, say, thread_ts)

    async def handle_app_mention(self, event: dict[str, Any], say: Any) -> None:
        """Handle an @mention of the bot.

        Args:
            event: Slack app_mention event
            say: Function to send messages back
        """
        user_id = event.get("user", "")
        channel_id = event.get("channel", "")
        text = event.get("text", "").strip()
        thread_ts = event.get("thread_ts") or event.get("ts")

        # Remove the bot mention from the text
        bot_user_id = self.adapter.get_bot_user_id()
        if bot_user_id:
            text = text.replace(f"<@{bot_user_id}>", "").strip()

        if not text or not user_id:
            return

        logger.info(f"Slack mention from {user_id} in {channel_id}: {text[:50]}...")

        await self._process_message(text, user_id, channel_id, say, thread_ts)

    async def _handle_command(
        self,
        text: str,
        user_id: str,
        channel_id: str,
        say: Any,
        thread_ts: str | None,
    ) -> None:
        """Handle slash-like commands (starting with /).

        Note: These aren't actual Slack slash commands, just message patterns.
        """
        parts = text.split(maxsplit=1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if command == "/help":
            help_text = (
                "*Atlas Bot Commands*\n\n"
                "• `/help` - Show this help message\n"
                "• `/link <code>` - Link your Slack account to Atlas\n"
                "• `/status` - Check your account linking status\n"
                "• `/agents` - List available AI agents\n\n"
                "*Talking to Agents*\n"
                "• Just send a message to chat with the default agent\n"
                "• Use `@agent_name message` to talk to a specific agent\n"
                "• Example: `@triage analyze ticket ESD-123`"
            )
            await say(text=help_text, thread_ts=thread_ts)

        elif command == "/link":
            if not args:
                await say(
                    text="Please provide a verification code: `/link <code>`\n"
                         "Get a code from your Atlas admin or the web UI.",
                    thread_ts=thread_ts,
                )
                return

            # Try to verify the code
            result = self.linking.verify_code(args.strip(), user_id, "slack")
            if result.get("success"):
                username = result.get("username", "user")
                await say(
                    text=f":white_check_mark: *Account linked successfully!*\n"
                         f"Your Slack account is now linked to Atlas user `{username}`.\n"
                         f"You can now use all Atlas bot features.",
                    thread_ts=thread_ts,
                )
            else:
                error = result.get("error", "Invalid or expired code")
                await say(
                    text=f":x: *Linking failed:* {error}\n"
                         f"Please check your code and try again.",
                    thread_ts=thread_ts,
                )

        elif command == "/status":
            account = self.linking.get_platform_account(user_id, "slack")
            if account and account.verified:
                username = account.user.username if account.user else "Unknown"
                await say(
                    text=f":white_check_mark: *Account linked*\n"
                         f"Slack → Atlas user: `{username}`",
                    thread_ts=thread_ts,
                )
            else:
                await say(
                    text=":x: *Account not linked*\n"
                         "Use `/link <code>` to link your account.",
                    thread_ts=thread_ts,
                )

        elif command == "/agents":
            from infrastructure_atlas.agents.playground import AVAILABLE_AGENTS

            agent_lines = []
            for agent in AVAILABLE_AGENTS:
                agent_lines.append(f"• *{agent.id}* - {agent.description}")

            await say(
                text="*Available Agents*\n\n" + "\n".join(agent_lines) + "\n\n"
                     "_Use `@agent_name message` to talk to a specific agent_",
                thread_ts=thread_ts,
            )

        else:
            await say(
                text=f"Unknown command: `{command}`\nUse `/help` for available commands.",
                thread_ts=thread_ts,
            )

    async def _process_message(
        self,
        text: str,
        user_id: str,
        channel_id: str,
        say: Any,
        thread_ts: str | None,
    ) -> None:
        """Process a message through the AI orchestrator.

        Args:
            text: Message text
            user_id: Slack user ID
            channel_id: Channel ID
            say: Function to send responses
            thread_ts: Thread timestamp for replies
        """
        from infrastructure_atlas.bots.orchestrator import BotResponse, BotResponseType

        try:
            async for response in self.orchestrator.process_message(
                platform="slack",
                platform_user_id=user_id,
                platform_conversation_id=channel_id,
                message=text,
            ):
                if response.type == BotResponseType.TYPING:
                    # Slack doesn't support typing indicators for bots
                    pass

                elif response.type == BotResponseType.TEXT:
                    # Format and send the response
                    formatted = self.formatter.format_agent_response(
                        agent_id=response.data.get("agent_id", "assistant"),
                        response=response.data.get("content", ""),
                        tool_calls=response.data.get("tool_calls"),
                    )
                    await say(
                        blocks=formatted.content.get("blocks", []),
                        text=response.data.get("content", "")[:150],  # Fallback text
                        thread_ts=thread_ts,
                    )

                elif response.type == BotResponseType.ERROR:
                    formatted = self.formatter.format_error(response.data.get("error", "An error occurred"))
                    await say(
                        blocks=formatted.content.get("blocks", []),
                        text=f"Error: {response.data.get('error', 'Unknown error')}",
                        thread_ts=thread_ts,
                    )

                elif response.type == BotResponseType.UNAUTHORIZED:
                    await say(
                        text=":lock: *Account not linked*\n"
                             "Please link your Slack account first using `/link <code>`.\n"
                             "Contact your Atlas admin to get a verification code.",
                        thread_ts=thread_ts,
                    )

        except Exception as e:
            logger.error(f"Error processing Slack message: {e}", exc_info=True)
            await say(
                text=f":warning: *Error processing message*\n`{str(e)[:200]}`",
                thread_ts=thread_ts,
            )
