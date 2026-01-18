"""Bot platform adapters for Telegram, Slack, and Teams."""

from infrastructure_atlas.bots.adapters.base import BotAdapter
from infrastructure_atlas.bots.adapters.telegram import TelegramAdapter, TelegramWebhookHandler
from infrastructure_atlas.bots.adapters.telegram_polling import TelegramPollingBot

__all__ = [
    "BotAdapter",
    "TelegramAdapter",
    "TelegramPollingBot",
    "TelegramWebhookHandler",
]
