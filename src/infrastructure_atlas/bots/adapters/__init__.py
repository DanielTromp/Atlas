"""Bot platform adapters for Telegram, Slack, and Teams."""

from infrastructure_atlas.bots.adapters.base import BotAdapter
from infrastructure_atlas.bots.adapters.telegram import TelegramAdapter, TelegramWebhookHandler
from infrastructure_atlas.bots.adapters.telegram_polling import TelegramPollingBot

# Slack adapters (imported lazily to avoid import errors if slack-bolt not installed)
try:
    from infrastructure_atlas.bots.adapters.slack import SlackAdapter, SlackWebhookHandler
    from infrastructure_atlas.bots.adapters.slack_socket import SlackSocketModeBot
    _SLACK_AVAILABLE = True
except ImportError:
    SlackAdapter = None  # type: ignore
    SlackWebhookHandler = None  # type: ignore
    SlackSocketModeBot = None  # type: ignore
    _SLACK_AVAILABLE = False

__all__ = [
    "BotAdapter",
    "TelegramAdapter",
    "TelegramPollingBot",
    "TelegramWebhookHandler",
    "SlackAdapter",
    "SlackWebhookHandler",
    "SlackSocketModeBot",
]
