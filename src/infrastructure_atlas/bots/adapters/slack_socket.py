"""Slack bot using Socket Mode (no public endpoints required).

Socket Mode creates a WebSocket connection from your server to Slack,
eliminating the need for public webhook URLs. This is ideal for:
- Internal deployments behind firewalls
- Development and testing
- Environments without public HTTPS endpoints

Requirements:
1. Create a Slack App at https://api.slack.com/apps
2. Enable Socket Mode in the app settings
3. Generate an App-Level Token with `connections:write` scope
4. Add Bot Token Scopes (see slack.py for required scopes)
5. Subscribe to events: message.im, app_mention
"""

from __future__ import annotations

import asyncio
import os
import signal
from typing import TYPE_CHECKING, Any

from infrastructure_atlas.bots.adapters.slack import SlackAdapter, SlackWebhookHandler
from infrastructure_atlas.bots.service_factory import (
    create_bot_orchestrator,
    create_user_linking_service,
    get_bot_session,
)
from infrastructure_atlas.infrastructure.logging import get_logger
from infrastructure_atlas.skills import get_skills_registry

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class SlackSocketModeBot:
    """Slack bot using Socket Mode connection.

    This creates a persistent WebSocket connection to Slack,
    allowing the bot to receive events without exposing a public endpoint.

    Usage:
        bot = SlackSocketModeBot()
        await bot.start()  # Runs until interrupted
    """

    def __init__(
        self,
        bot_token: str | None = None,
        app_token: str | None = None,
    ):
        """Initialize the Socket Mode bot.

        Args:
            bot_token: Bot User OAuth Token (xoxb-...). Uses SLACK_BOT_TOKEN env var if not provided.
            app_token: App-Level Token for Socket Mode (xapp-...). Uses SLACK_APP_TOKEN env var if not provided.
        """
        self.bot_token = bot_token or os.getenv("SLACK_BOT_TOKEN", "")
        self.app_token = app_token or os.getenv("SLACK_APP_TOKEN", "")
        self._running = False
        self._handler: Any = None  # Socket Mode handler reference for shutdown
        self._shutdown_event: asyncio.Event | None = None

        if not self.bot_token:
            raise ValueError("SLACK_BOT_TOKEN not set")
        if not self.app_token:
            raise ValueError("SLACK_APP_TOKEN not set (required for Socket Mode)")

    async def start(self) -> None:
        """Start the Socket Mode connection. Runs until stop() is called or interrupted."""
        from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
        from slack_bolt.async_app import AsyncApp

        self._running = True
        self._shutdown_event = asyncio.Event()

        # Create the Bolt app
        app = AsyncApp(token=self.bot_token)

        # Get bot info
        adapter = SlackAdapter(bot_token=self.bot_token, app_token=self.app_token)
        bot_info = await adapter.get_bot_info()
        logger.info(f"Starting Slack Socket Mode bot: @{bot_info.get('username')} (team: {bot_info.get('team')})")

        # Register event handlers
        @app.event("message")
        async def handle_message(event: dict[str, Any], say: Any) -> None:
            """Handle direct messages to the bot."""
            # Only handle DMs (channel_type == 'im')
            if event.get("channel_type") != "im":
                return

            await self._process_event(event, say, "message")

        @app.event("app_mention")
        async def handle_mention(event: dict[str, Any], say: Any) -> None:
            """Handle @mentions of the bot in channels."""
            await self._process_event(event, say, "mention")

        # Set up signal handlers for graceful shutdown
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._signal_handler)

        # Start Socket Mode handler
        self._handler = AsyncSocketModeHandler(app, self.app_token)

        try:
            logger.info("Connecting to Slack via Socket Mode...")
            # Start handler in background and wait for shutdown signal
            await self._handler.connect_async()
            # Wait for shutdown event instead of blocking forever
            await self._shutdown_event.wait()
        except asyncio.CancelledError:
            logger.info("Socket Mode cancelled")
        finally:
            if self._handler:
                await self._handler.close_async()
            logger.info("Slack Socket Mode bot stopped")

    def stop(self) -> None:
        """Stop the Socket Mode connection."""
        self._running = False
        if self._shutdown_event:
            self._shutdown_event.set()

    def _signal_handler(self) -> None:
        """Handle shutdown signals."""
        logger.info("Received shutdown signal, stopping bot...")
        self.stop()

    async def _process_event(
        self,
        event: dict[str, Any],
        say: Any,
        event_type: str,
    ) -> None:
        """Process a Slack event.

        Args:
            event: Slack event data
            say: Function to send messages back
            event_type: Type of event ("message" or "mention")
        """
        try:
            # Create fresh database session for each event
            with get_bot_session() as db:
                adapter = SlackAdapter(bot_token=self.bot_token, app_token=self.app_token)
                skills = get_skills_registry()
                orchestrator = create_bot_orchestrator(db, skills)
                linking = create_user_linking_service(db)
                handler = SlackWebhookHandler(adapter, orchestrator, linking)

                if event_type == "mention":
                    await handler.handle_app_mention(event, say)
                else:
                    await handler.handle_message(event, say)

        except Exception as e:
            logger.error(f"Error processing Slack event: {e}", exc_info=True)


async def run_socket_mode_bot(
    bot_token: str | None = None,
    app_token: str | None = None,
) -> None:
    """Run the Slack Socket Mode bot.

    This is the main entry point for running the bot.

    Args:
        bot_token: Optional bot token, uses SLACK_BOT_TOKEN env var if not provided.
        app_token: Optional app token, uses SLACK_APP_TOKEN env var if not provided.
    """
    bot = SlackSocketModeBot(bot_token=bot_token, app_token=app_token)
    await bot.start()


def main() -> None:
    """CLI entry point for running the Socket Mode bot."""
    asyncio.run(run_socket_mode_bot())


if __name__ == "__main__":
    main()
