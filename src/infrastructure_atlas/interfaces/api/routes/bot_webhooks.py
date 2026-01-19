"""Bot webhook endpoints for Telegram, Slack, and Teams."""

from __future__ import annotations

import os
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from infrastructure_atlas.bots.adapters.telegram import TelegramAdapter, TelegramWebhookHandler
from infrastructure_atlas.bots.service_factory import (
    create_bot_orchestrator,
    create_user_linking_service,
    get_bot_session,
)
from infrastructure_atlas.db.models import BotWebhookConfig
from infrastructure_atlas.infrastructure.logging import get_logger
from infrastructure_atlas.infrastructure.modules.registry import get_module_registry
from infrastructure_atlas.interfaces.api.dependencies import DbSessionDep

logger = get_logger(__name__)

router = APIRouter(prefix="/webhooks/bots", tags=["bot-webhooks"])


def require_bots_enabled() -> None:
    """Dependency to check if bots module is enabled."""
    registry = get_module_registry()
    if not registry.is_enabled("bots"):
        raise HTTPException(status_code=404, detail="Bots module is not enabled")


BotsEnabledDep = Annotated[None, Depends(require_bots_enabled)]


def get_skills_registry_for_bots():
    """Get the skills registry for agent operations."""
    # Import here to avoid circular imports
    from infrastructure_atlas.skills import get_skills_registry

    return get_skills_registry()


def get_telegram_config(db: Session) -> BotWebhookConfig | None:
    """Get Telegram webhook configuration from database or env."""
    config = db.query(BotWebhookConfig).filter_by(platform="telegram").first()
    if config and config.enabled:
        return config

    # Fall back to environment variable
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if token:
        # Create a transient config object
        return BotWebhookConfig(
            platform="telegram",
            enabled=True,
            bot_token_secret="TELEGRAM_BOT_TOKEN",  # Env var name
            webhook_secret=os.getenv("TELEGRAM_WEBHOOK_SECRET"),
        )

    return None


@router.post("/telegram/{webhook_secret}")
async def telegram_webhook(
    webhook_secret: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: DbSessionDep,
    _: BotsEnabledDep,
) -> dict[str, str]:
    """Handle incoming Telegram webhook updates.

    This endpoint receives webhook updates from Telegram and processes them
    in the background for fast response times.

    Args:
        webhook_secret: Secret token in URL path for basic validation
        request: FastAPI request object
        background_tasks: FastAPI background tasks
        db: Database session

    Returns:
        Acknowledgement response
    """
    # Get Telegram config
    config = get_telegram_config(db)
    if not config:
        raise HTTPException(status_code=404, detail="Telegram bot not configured")

    # Verify webhook secret from URL matches configured secret
    configured_secret = config.webhook_secret or os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    if configured_secret and webhook_secret != configured_secret:
        logger.warning("Telegram webhook secret mismatch")
        raise HTTPException(status_code=403, detail="Invalid webhook secret")

    # Verify X-Telegram-Bot-Api-Secret-Token header if present
    header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if configured_secret and header_secret and header_secret != configured_secret:
        logger.warning("Telegram header secret mismatch")
        raise HTTPException(status_code=403, detail="Invalid secret token")

    # Parse update
    try:
        update = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse Telegram update: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Process in background
    background_tasks.add_task(
        _process_telegram_update,
        update=update,
        db_session_factory=db.get_bind,
    )

    return {"status": "ok"}


async def _process_telegram_update(
    update: dict[str, Any],
    db_session_factory: Any,
) -> None:
    """Process a Telegram update in the background.

    Args:
        update: Telegram Update object
        db_session_factory: Factory for creating database sessions (unused, kept for compatibility)
    """
    try:
        # Get bot token from environment
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not token:
            # Try to get from database config
            from infrastructure_atlas.db import get_sessionmaker
            SessionLocal = get_sessionmaker()
            with SessionLocal() as db:
                config = db.query(BotWebhookConfig).filter_by(platform="telegram").first()
                if config:
                    # TODO: Decrypt token from SecretStore
                    token = config.bot_token_secret

        if not token:
            logger.error("No Telegram bot token configured")
            return

        # Create adapter and handler using service factory
        # This uses MongoDB or SQLite based on ATLAS_STORAGE_BACKEND
        with get_bot_session() as session:
            adapter = TelegramAdapter(bot_token=token)
            skills = get_skills_registry_for_bots()
            orchestrator = create_bot_orchestrator(session, skills)
            linking = create_user_linking_service(session)
            handler = TelegramWebhookHandler(adapter, orchestrator, linking)

            # Process update
            await handler.handle_update(update)

    except Exception as e:
        logger.error(f"Failed to process Telegram update: {e}", exc_info=True)


@router.post("/telegram")
async def telegram_webhook_no_secret(
    request: Request,
    background_tasks: BackgroundTasks,
    db: DbSessionDep,
    _: BotsEnabledDep,
    x_telegram_bot_api_secret_token: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    """Handle Telegram webhook without URL path secret (uses header instead).

    This is an alternative endpoint that uses the X-Telegram-Bot-Api-Secret-Token
    header for authentication instead of the URL path.
    """
    # Get configured secret
    configured_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    config = get_telegram_config(db)
    if config and config.webhook_secret:
        configured_secret = config.webhook_secret

    # Verify header secret
    if configured_secret:
        if not x_telegram_bot_api_secret_token:
            raise HTTPException(status_code=403, detail="Missing secret token")
        if x_telegram_bot_api_secret_token != configured_secret:
            logger.warning("Telegram webhook secret mismatch")
            raise HTTPException(status_code=403, detail="Invalid secret token")

    # Parse update
    try:
        update = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse Telegram update: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Process in background
    background_tasks.add_task(
        _process_telegram_update,
        update=update,
        db_session_factory=db.get_bind,
    )

    return {"status": "ok"}
