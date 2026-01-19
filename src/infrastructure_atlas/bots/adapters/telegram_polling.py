"""Telegram bot polling mode for environments without public webhook URLs.

This module provides a long-polling based Telegram bot that doesn't require
a public webhook URL. It connects to Telegram and pulls updates continuously.
"""

from __future__ import annotations

import asyncio
import os
import signal
from typing import TYPE_CHECKING, Any

from infrastructure_atlas.bots.adapters.telegram import TelegramAdapter, TelegramWebhookHandler
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


class TelegramPollingBot:
    """Telegram bot using long-polling mode.

    This is suitable for internal deployments where you don't have
    a public HTTPS endpoint for webhooks.

    Usage:
        bot = TelegramPollingBot(bot_token="...")
        await bot.start()  # Runs until interrupted
    """

    def __init__(
        self,
        bot_token: str | None = None,
        poll_interval: float = 1.0,
        timeout: int = 30,
    ):
        """Initialize the polling bot.

        Args:
            bot_token: Telegram bot token. Uses TELEGRAM_BOT_TOKEN env var if not provided.
            poll_interval: Seconds between polling requests when no updates.
            timeout: Long-polling timeout in seconds.
        """
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.poll_interval = poll_interval
        self.timeout = timeout
        self._running = False
        self._offset: int | None = None

        if not self.bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN not set")

    async def start(self) -> None:
        """Start the polling loop. Runs until stop() is called or interrupted."""
        self._running = True

        # Delete any existing webhook first
        adapter = TelegramAdapter(bot_token=self.bot_token)
        await adapter.delete_webhook(drop_pending_updates=True)

        # Get bot info
        bot_info = await adapter.get_bot_info()
        logger.info(f"Starting Telegram polling bot: @{bot_info.get('username')}")

        # Set up signal handlers for graceful shutdown
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._signal_handler)

        try:
            while self._running:
                await self._poll_updates()
        except asyncio.CancelledError:
            logger.info("Polling cancelled")
        finally:
            logger.info("Telegram polling bot stopped")

    def stop(self) -> None:
        """Stop the polling loop."""
        self._running = False

    def _signal_handler(self) -> None:
        """Handle shutdown signals."""
        logger.info("Received shutdown signal")
        self.stop()

    async def _poll_updates(self) -> None:
        """Poll for updates from Telegram."""
        import httpx

        url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
        params: dict[str, Any] = {
            "timeout": self.timeout,
            "allowed_updates": ["message", "callback_query"],
        }

        if self._offset is not None:
            params["offset"] = self._offset

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    url,
                    params=params,
                    timeout=self.timeout + 10,  # Extra buffer for network
                )
                data = response.json()

                if not data.get("ok"):
                    logger.error(f"Telegram API error: {data.get('description')}")
                    await asyncio.sleep(self.poll_interval)
                    return

                updates = data.get("result", [])

                for update in updates:
                    # Update offset to acknowledge this update
                    self._offset = update["update_id"] + 1

                    # Process update
                    await self._process_update(update)

                if not updates:
                    # No updates, brief sleep before next poll
                    await asyncio.sleep(self.poll_interval)

        except httpx.TimeoutException:
            # Normal for long-polling, just continue
            pass
        except Exception as e:
            logger.error(f"Polling error: {e}", exc_info=True)
            await asyncio.sleep(self.poll_interval)

    async def _process_update(self, update: dict[str, Any]) -> None:
        """Process a single update.

        Args:
            update: Telegram Update object
        """
        try:
            # Create fresh database session for each update
            # Uses MongoDB or SQLite based on ATLAS_STORAGE_BACKEND
            with get_bot_session() as db:
                adapter = TelegramAdapter(bot_token=self.bot_token)
                skills = get_skills_registry()
                orchestrator = create_bot_orchestrator(db, skills)
                linking = create_user_linking_service(db)
                handler = TelegramWebhookHandler(adapter, orchestrator, linking)

                await handler.handle_update(update)

        except Exception as e:
            logger.error(f"Error processing update {update.get('update_id')}: {e}", exc_info=True)


async def run_polling_bot(bot_token: str | None = None) -> None:
    """Run the Telegram polling bot.

    This is the main entry point for running the bot in polling mode.

    Args:
        bot_token: Optional bot token, uses TELEGRAM_BOT_TOKEN env var if not provided.
    """
    bot = TelegramPollingBot(bot_token=bot_token)
    await bot.start()


def main() -> None:
    """CLI entry point for running the polling bot."""
    asyncio.run(run_polling_bot())


if __name__ == "__main__":
    main()
