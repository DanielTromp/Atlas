"""Slack bot adapter using Socket Mode (no public endpoints required).

This module provides a Slack bot implementation using Socket Mode which
creates a WebSocket connection from the server to Slack, eliminating the
need for public webhook URLs.

Required Slack App permissions (OAuth Scopes):
- Bot Token Scopes:
  - app_mentions:read - Receive @mentions
  - chat:write - Send messages
  - files:write - Upload files (for Excel exports)
  - im:history - Read DMs
  - im:read - View basic DM info
  - im:write - Start DMs
  - users:read - Get user info
  - users:read.email - Get user email (for ticket assignment lookup)

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

    async def add_reaction(self, channel: str, timestamp: str, emoji: str = "hourglass_flowing_sand") -> bool:
        """Add a reaction to a message.

        Args:
            channel: Channel ID
            timestamp: Message timestamp
            emoji: Emoji name without colons (default: hourglass_flowing_sand ⏳)

        Returns:
            True if successful, False otherwise
        """
        client = self._get_client()
        try:
            client.reactions_add(channel=channel, timestamp=timestamp, name=emoji)
            return True
        except Exception as e:
            # Ignore "already_reacted" errors
            if "already_reacted" not in str(e):
                logger.debug(f"Failed to add reaction: {e}")
            return False

    async def remove_reaction(self, channel: str, timestamp: str, emoji: str = "hourglass_flowing_sand") -> bool:
        """Remove a reaction from a message.

        Args:
            channel: Channel ID
            timestamp: Message timestamp
            emoji: Emoji name without colons (default: hourglass_flowing_sand ⏳)

        Returns:
            True if successful, False otherwise
        """
        client = self._get_client()
        try:
            client.reactions_remove(channel=channel, timestamp=timestamp, name=emoji)
            return True
        except Exception as e:
            # Ignore "no_reaction" errors
            if "no_reaction" not in str(e):
                logger.debug(f"Failed to remove reaction: {e}")
            return False

    async def upload_file(
        self,
        chat_id: str,
        file_path: str,
        filename: str | None = None,
        title: str | None = None,
        initial_comment: str | None = None,
        thread_ts: str | None = None,
    ) -> dict[str, Any]:
        """Upload a file to a Slack channel/DM.

        Args:
            chat_id: Channel ID or user ID
            file_path: Path to the file to upload
            filename: Optional filename override
            title: Optional file title
            initial_comment: Optional message with the file
            thread_ts: Optional thread timestamp to reply to

        Returns:
            Dictionary with file info from Slack
        """
        client = self._get_client()

        try:
            # Use files_upload_v2 for better performance
            response = client.files_upload_v2(
                channel=chat_id,
                file=file_path,
                filename=filename,
                title=title,
                initial_comment=initial_comment,
                thread_ts=thread_ts,
            )
            logger.info(f"Uploaded file to Slack: {filename or file_path}")
            return response.data
        except Exception as e:
            logger.error(f"Failed to upload file to Slack: {e}")
            raise

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

    async def get_bot_user_id(self) -> str:
        """Get the bot's user ID (cached after first call)."""
        if not self._bot_user_id:
            await self.get_bot_info()
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
        channel_type = event.get("channel_type", "")
        text = event.get("text", "").strip()
        # thread_ts is only set for threaded replies, ts is the message's own timestamp
        actual_thread_ts = event.get("thread_ts")  # Only set if this is a reply in a thread
        reply_ts = actual_thread_ts or event.get("ts")  # For sending replies back

        # For DMs (channel_type == 'im'), ALWAYS use just channel_id for session
        # This ensures all messages in a DM share the same session, even across threads
        # For channels, use thread_ts to separate thread conversations
        is_dm = channel_type == "im"
        # Use thread_ts for session if available - each thread gets its own memory
        # For messages not in a thread, use ts to identify the message as potential thread parent
        session_thread_ts = actual_thread_ts or event.get("ts")

        if not text or not user_id:
            return

        logger.info(f"Slack message from {user_id} in {channel_id}: {text[:50]}... (is_dm={is_dm}, thread_ts={actual_thread_ts})")

        # Check for commands (use ! prefix since Slack intercepts / as native commands)
        # Also handle without prefix for common commands like "link" and "help"
        text_lower = text.lower()
        if text.startswith("!"):
            await self._handle_command(text, user_id, channel_id, say, reply_ts)
            return
        elif text_lower.startswith("link ") or text_lower == "link":
            # Handle "link <code>" without the ! prefix
            await self._handle_command("!" + text, user_id, channel_id, say, reply_ts)
            return
        elif text_lower in ("help", "status", "agents"):
            await self._handle_command("!" + text, user_id, channel_id, say, reply_ts)
            return

        # Process regular message through orchestrator
        # session_thread_ts is None for DMs (all messages share one session)
        message_ts = event.get("ts")  # Original message timestamp for reactions
        await self._process_message(text, user_id, channel_id, say, reply_ts, message_ts, session_thread_ts)

    async def handle_app_mention(self, event: dict[str, Any], say: Any) -> None:
        """Handle an @mention of the bot.

        Args:
            event: Slack app_mention event
            say: Function to send messages back
        """
        user_id = event.get("user", "")
        channel_id = event.get("channel", "")
        text = event.get("text", "").strip()
        # thread_ts is only set for threaded replies
        actual_thread_ts = event.get("thread_ts")  # Only set if this is a reply in a thread
        reply_ts = actual_thread_ts or event.get("ts")  # For sending replies back

        # Remove the bot mention from the text
        bot_user_id = await self.adapter.get_bot_user_id()
        if bot_user_id:
            text = text.replace(f"<@{bot_user_id}>", "").strip()

        if not text or not user_id:
            return

        logger.info(f"Slack mention from {user_id} in {channel_id}: {text[:50]}... (thread_ts={actual_thread_ts})")

        # Check for commands in mentions too
        text_lower = text.lower()
        if text.startswith("!"):
            await self._handle_command(text, user_id, channel_id, say, reply_ts)
            return
        elif text_lower.startswith("link ") or text_lower == "link":
            await self._handle_command("!" + text, user_id, channel_id, say, reply_ts)
            return
        elif text_lower in ("help", "status", "agents"):
            await self._handle_command("!" + text, user_id, channel_id, say, reply_ts)
            return

        # Use thread_ts for session if available - each thread/message gets its own memory
        session_thread_ts = actual_thread_ts or event.get("ts")
        message_ts = event.get("ts")  # Original message timestamp for reactions
        await self._process_message(text, user_id, channel_id, say, reply_ts, message_ts, session_thread_ts)

    async def _handle_command(
        self,
        text: str,
        user_id: str,
        channel_id: str,
        say: Any,
        thread_ts: str | None,
    ) -> None:
        """Handle bot commands (starting with !).

        Note: Slack intercepts / as native slash commands, so we use ! prefix.
        """
        parts = text.split(maxsplit=1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if command == "!help":
            help_text = (
                "*Atlas Bot Commands*\n\n"
                "• `!help` - Show this help message\n"
                "• `!link <code>` - Link your Slack account to Atlas\n"
                "• `!status` - Check your account linking status\n"
                "• `!agents` - List available AI agents\n\n"
                "*Talking to Agents*\n"
                "• Just send a message to chat with the default agent\n"
                "• Use `@agent_name message` to talk to a specific agent\n"
                "• Example: `@triage analyze ticket ESD-123`"
            )
            await say(text=help_text, thread_ts=thread_ts)

        elif command == "!link":
            if not args:
                await say(
                    text="Please provide a verification code: `!link <code>`\n"
                         "Get a code from your Atlas admin or the web UI.",
                    thread_ts=thread_ts,
                )
                return

            # Get user info for platform username
            try:
                user_info = await self.adapter.get_user_info(user_id)
                platform_username = user_info.get("real_name") or user_info.get("name")
            except Exception:
                platform_username = None

            # Try to verify the code - signature: (platform, platform_user_id, code, platform_username)
            account = self.linking.verify_code("slack", user_id, args.strip(), platform_username)
            if account:
                # Get username from account's user relationship or look it up
                username = "user"
                if hasattr(account, "user") and account.user:
                    username = getattr(account.user, "username", None) or "user"
                elif hasattr(account, "user_id") and account.user_id:
                    # Look up the user to get username (for MongoDB where user isn't eager-loaded)
                    atlas_user = self.linking.get_user_by_platform("slack", user_id)
                    if atlas_user:
                        username = getattr(atlas_user, "username", None) or "user"
                await say(
                    text=f":white_check_mark: *Account linked successfully!*\n"
                         f"Your Slack account is now linked to Atlas user `{username}`.\n"
                         f"You can now use all Atlas bot features.",
                    thread_ts=thread_ts,
                )
            else:
                await say(
                    text=":x: *Linking failed:* Invalid or expired code\n"
                         "Please check your code and try again.",
                    thread_ts=thread_ts,
                )

        elif command == "!status":
            account = self.linking.get_linked_account("slack", user_id)
            if account and account.verified:
                username = "Unknown"
                if hasattr(account, "user") and account.user:
                    username = getattr(account.user, "username", None) or "Unknown"
                elif hasattr(account, "user_id") and account.user_id:
                    # MongoDB doesn't eager-load user - look it up
                    atlas_user = self.linking.get_user_by_platform("slack", user_id)
                    if atlas_user:
                        username = getattr(atlas_user, "username", None) or "Unknown"
                await say(
                    text=f":white_check_mark: *Account linked*\n"
                         f"Slack → Atlas user: `{username}`",
                    thread_ts=thread_ts,
                )
            else:
                await say(
                    text=":x: *Account not linked*\n"
                         "Use `!link <code>` to link your account.",
                    thread_ts=thread_ts,
                )

        elif command == "!agents":
            from infrastructure_atlas.agents.playground import AVAILABLE_AGENTS

            agent_lines = []
            for agent in AVAILABLE_AGENTS.values():
                agent_lines.append(f"• *{agent.id}* - {agent.description}")

            await say(
                text="*Available Agents*\n\n" + "\n".join(agent_lines) + "\n\n"
                     "_Use `@agent_name message` to talk to a specific agent_",
                thread_ts=thread_ts,
            )

        elif command == "!test":
            # Test command to verify mrkdwn formatting in blocks
            test_blocks = [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*This should be bold*\n_This should be italic_\n`This should be code`"
                    }
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*1. ESD-40403 - Test ticket*\n• Status: Pending\n• Priority: Medium"
                    }
                }
            ]
            await say(
                blocks=test_blocks,
                text="Test message",
                thread_ts=thread_ts,
            )

        else:
            await say(
                text=f"Unknown command: `{command}`\nUse `!help` for available commands.",
                thread_ts=thread_ts,
            )

    async def _process_message(
        self,
        text: str,
        user_id: str,
        channel_id: str,
        say: Any,
        reply_ts: str | None,
        message_ts: str | None = None,
        session_thread_ts: str | None = None,
    ) -> None:
        """Process a message through the AI orchestrator.

        Args:
            text: Message text
            user_id: Slack user ID
            channel_id: Channel ID
            say: Function to send responses
            reply_ts: Thread timestamp for sending replies back
            message_ts: Original message timestamp (for reactions)
            session_thread_ts: Thread timestamp for session ID (None for DMs = shared session)
        """
        from infrastructure_atlas.bots.orchestrator import BotResponse, BotResponseType

        # Add "thinking" reaction to show we're processing
        if message_ts:
            await self.adapter.add_reaction(channel_id, message_ts, "hourglass_flowing_sand")

        try:
            # Use thread_ts in conversation ID only for actual threaded conversations
            # For DMs (no thread_ts), all messages share the same session via channel_id
            # For channel threads, each thread is a separate session
            if session_thread_ts:
                conversation_id = f"{channel_id}:{session_thread_ts}"
            else:
                conversation_id = channel_id

            logger.info(f"Processing message with conversation_id={conversation_id}")

            # Get Slack user info (email, display name) for agent context
            platform_user_info = await self.adapter.get_user_info(user_id)
            logger.info(f"Slack user info: {platform_user_info.get('display_name')} <{platform_user_info.get('email')}>")

            async for response in self.orchestrator.process_message(
                platform="slack",
                platform_user_id=user_id,
                platform_conversation_id=conversation_id,
                message=text,
                platform_user_info=platform_user_info,
            ):
                logger.debug(f"[SLACK] Received response type: {response.type}")
                if response.type == BotResponseType.TYPING:
                    # Slack doesn't support typing indicators for bots
                    pass

                elif response.type == BotResponseType.TEXT:
                    # Always use Slack formatter for proper mrkdwn formatting
                    raw_content = response.content or ""
                    logger.debug(f"[SLACK] Received TEXT response, content length: {len(raw_content)}, channel={channel_id}, thread={reply_ts}")

                    formatted = self.formatter.format_agent_response(
                        agent_id=response.agent_id or "assistant",
                        response=raw_content,
                        tool_calls=None,
                    )
                    # Get content as string for fallback text
                    content_text = raw_content if isinstance(raw_content, str) else str(raw_content)
                    blocks = formatted.content.get("blocks", []) if isinstance(formatted.content, dict) else []
                    logger.info(f"Sending Slack message with {len(blocks)} blocks")
                    try:
                        await say(
                            blocks=blocks,
                            text=content_text[:150],  # Fallback text
                            thread_ts=reply_ts,
                        )
                        logger.info("Slack message sent successfully")
                    except Exception as e:
                        logger.error(f"Failed to send Slack message: {e}", exc_info=True)

                elif response.type == BotResponseType.ERROR:
                    error_msg = response.content if isinstance(response.content, str) else str(response.content or "An error occurred")
                    formatted = self.formatter.format_error(error_msg)
                    await say(
                        blocks=formatted.content.get("blocks", []) if isinstance(formatted.content, dict) else [],
                        text=f"Error: {error_msg[:200]}",
                        thread_ts=reply_ts,
                    )

                elif response.type == BotResponseType.UNAUTHORIZED:
                    await say(
                        text=":lock: *Account not linked*\n"
                             "Please link your Slack account first using `!link <code>`.\n"
                             "Contact your Atlas admin to get a verification code.",
                        thread_ts=reply_ts,
                    )

                elif response.type == BotResponseType.FILE:
                    # File export - upload to Slack
                    file_data = response.content if isinstance(response.content, dict) else {}
                    file_path = file_data.get("file_path")
                    filename = file_data.get("filename")
                    file_type = file_data.get("file_type", "file")
                    row_count = file_data.get("row_count")
                    message = file_data.get("message")

                    if file_path:
                        try:
                            # Build initial comment
                            comment_parts = []
                            if message:
                                comment_parts.append(message)
                            if row_count:
                                comment_parts.append(f"📊 {row_count} rows exported")
                            initial_comment = "\n".join(comment_parts) if comment_parts else None

                            # Upload file to Slack
                            await self.adapter.upload_file(
                                chat_id=channel_id,
                                file_path=file_path,
                                filename=filename,
                                title=filename or f"Export.{file_type}",
                                initial_comment=initial_comment,
                                thread_ts=reply_ts,
                            )
                            logger.info(f"Uploaded file to Slack: {filename}")
                        except Exception as e:
                            logger.error(f"Failed to upload file to Slack: {e}")
                            await say(
                                text=f":warning: *Failed to upload file*\n`{str(e)[:200]}`",
                                thread_ts=reply_ts,
                            )

            logger.debug("[SLACK] Finished processing all responses from orchestrator")

        except Exception as e:
            logger.error(f"Error processing Slack message: {e}", exc_info=True)
            await say(
                text=f":warning: *Error processing message*\n`{str(e)[:200]}`",
                thread_ts=reply_ts,
            )

        finally:
            # Remove "thinking" reaction when done (success or error)
            if message_ts:
                await self.adapter.remove_reaction(channel_id, message_ts, "hourglass_flowing_sand")
