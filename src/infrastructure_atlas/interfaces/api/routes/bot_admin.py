"""Bot administration API routes."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from infrastructure_atlas.bots.adapters.telegram import TelegramAdapter
from infrastructure_atlas.bots.linking import UserLinkingService
from infrastructure_atlas.db.models import (
    BotConversation,
    BotMessage,
    BotPlatformAccount,
    BotWebhookConfig,
)
from infrastructure_atlas.infrastructure.logging import get_logger
from infrastructure_atlas.infrastructure.modules.registry import get_module_registry
from infrastructure_atlas.interfaces.api.dependencies import AdminUserDep, CurrentUserDep, DbSessionDep

logger = get_logger(__name__)

router = APIRouter(prefix="/admin/bots", tags=["bot-admin"])


def require_bots_enabled() -> None:
    """Dependency to check if bots module is enabled."""
    registry = get_module_registry()
    if not registry.is_enabled("bots"):
        raise HTTPException(status_code=404, detail="Bots module is not enabled")


BotsEnabledDep = Annotated[None, Depends(require_bots_enabled)]


# =============================================================================
# Pydantic Models
# =============================================================================


class PlatformStatus(BaseModel):
    """Status of a bot platform."""

    platform: str
    configured: bool
    enabled: bool
    healthy: bool | None
    bot_name: str | None = None
    webhook_url: str | None = None
    message_count_24h: int = 0
    linked_accounts: int = 0
    error: str | None = None


class PlatformConfigRequest(BaseModel):
    """Request to configure a bot platform."""

    bot_token: str
    webhook_secret: str | None = None
    webhook_url: str | None = None
    extra_config: dict[str, Any] | None = None


class LinkedAccountResponse(BaseModel):
    """Response for a linked account."""

    id: int
    user_id: str
    username: str | None
    platform: str
    platform_user_id: str
    platform_username: str | None
    verified: bool
    created_at: datetime
    last_message_at: datetime | None = None


class ConversationResponse(BaseModel):
    """Response for a bot conversation."""

    id: int
    platform: str
    platform_conversation_id: str
    user_id: str
    username: str | None
    agent_id: str | None
    session_id: str | None
    message_count: int
    created_at: datetime
    last_message_at: datetime


class MessageResponse(BaseModel):
    """Response for a bot message."""

    id: int
    direction: str
    content: str
    agent_id: str | None
    tool_calls: list[dict[str, Any]] | None
    input_tokens: int
    output_tokens: int
    cost_usd: float
    duration_ms: int | None
    error: str | None
    created_at: datetime


class UsageStats(BaseModel):
    """Bot usage statistics."""

    period_days: int
    total_messages: int
    total_conversations: int
    total_linked_accounts: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
    messages_by_platform: dict[str, int]
    messages_by_agent: dict[str, int]


class VerificationCodeResponse(BaseModel):
    """Response containing a verification code."""

    code: str
    expires_at: datetime
    platform: str


# =============================================================================
# Platform Management Endpoints
# =============================================================================


@router.get("/platforms")
def list_platforms(
    db: DbSessionDep,
    _admin: AdminUserDep,
    _: BotsEnabledDep,
) -> list[PlatformStatus]:
    """List all bot platforms with their status.

    Returns configuration status, health, and statistics for each platform.
    """
    platforms = []

    for platform in ["telegram", "slack", "teams"]:
        status = _get_platform_status(db, platform)
        platforms.append(status)

    return platforms


def _get_platform_status(db: Session, platform: str) -> PlatformStatus:
    """Get status for a specific platform."""
    # Check database config
    config = db.query(BotWebhookConfig).filter_by(platform=platform).first()

    # Check environment variables
    env_configured = False
    if platform == "telegram":
        env_configured = bool(os.getenv("TELEGRAM_BOT_TOKEN"))
    elif platform == "slack":
        env_configured = bool(os.getenv("SLACK_BOT_TOKEN"))
    elif platform == "teams":
        env_configured = bool(os.getenv("TEAMS_APP_ID"))

    configured = (config is not None and config.enabled) or env_configured
    enabled = (config.enabled if config else False) or env_configured

    # Get statistics
    now = datetime.now(UTC)
    day_ago = now - timedelta(days=1)

    message_count = db.execute(
        select(func.count(BotMessage.id)).join(BotConversation).where(
            BotConversation.platform == platform,
            BotMessage.created_at >= day_ago,
        )
    ).scalar() or 0

    linked_accounts = db.execute(
        select(func.count(BotPlatformAccount.id)).where(
            BotPlatformAccount.platform == platform,
            BotPlatformAccount.verified == True,  # noqa: E712
        )
    ).scalar() or 0

    # Get health status
    healthy = None
    bot_name = None
    error = None

    if configured and platform == "telegram":
        try:
            import asyncio

            token = os.getenv("TELEGRAM_BOT_TOKEN")
            if token:
                adapter = TelegramAdapter(bot_token=token)
                bot_info = asyncio.run(adapter.get_bot_info())
                healthy = True
                bot_name = f"@{bot_info.get('username', 'unknown')}"
        except Exception as e:
            healthy = False
            error = str(e)

    return PlatformStatus(
        platform=platform,
        configured=configured,
        enabled=enabled,
        healthy=healthy,
        bot_name=bot_name,
        message_count_24h=message_count,
        linked_accounts=linked_accounts,
        error=error,
    )


@router.get("/platforms/{platform}")
def get_platform(
    platform: str,
    db: DbSessionDep,
    _admin: AdminUserDep,
    _: BotsEnabledDep,
) -> PlatformStatus:
    """Get detailed status for a specific platform."""
    if platform not in ["telegram", "slack", "teams"]:
        raise HTTPException(status_code=400, detail="Invalid platform")

    return _get_platform_status(db, platform)


@router.post("/platforms/{platform}/configure")
async def configure_platform(
    platform: str,
    config: PlatformConfigRequest,
    db: DbSessionDep,
    _admin: AdminUserDep,
    _: BotsEnabledDep,
) -> dict[str, Any]:
    """Configure a bot platform.

    This stores the bot token securely and optionally sets up the webhook.
    """
    if platform not in ["telegram", "slack", "teams"]:
        raise HTTPException(status_code=400, detail="Invalid platform")

    # TODO: Store token in SecretStore
    secret_key = f"bot_{platform}_token"

    # Create or update config
    existing = db.query(BotWebhookConfig).filter_by(platform=platform).first()

    if existing:
        existing.bot_token_secret = secret_key
        existing.webhook_secret = config.webhook_secret
        existing.extra_config = config.extra_config
        existing.enabled = True
    else:
        webhook_config = BotWebhookConfig(
            platform=platform,
            enabled=True,
            bot_token_secret=secret_key,
            webhook_secret=config.webhook_secret,
            extra_config=config.extra_config,
        )
        db.add(webhook_config)

    db.commit()

    # Set up webhook if URL provided and platform is Telegram
    webhook_result = None
    if config.webhook_url and platform == "telegram":
        try:
            adapter = TelegramAdapter(bot_token=config.bot_token)
            success = await adapter.set_webhook(
                webhook_url=config.webhook_url,
                secret_token=config.webhook_secret,
            )
            webhook_result = {"success": success, "url": config.webhook_url}
        except Exception as e:
            webhook_result = {"success": False, "error": str(e)}

    return {
        "status": "configured",
        "platform": platform,
        "webhook": webhook_result,
    }


@router.post("/platforms/{platform}/enable")
def enable_platform(
    platform: str,
    db: DbSessionDep,
    _admin: AdminUserDep,
    _: BotsEnabledDep,
) -> dict[str, str]:
    """Enable a bot platform."""
    config = db.query(BotWebhookConfig).filter_by(platform=platform).first()
    if not config:
        raise HTTPException(status_code=404, detail="Platform not configured")

    config.enabled = True
    db.commit()

    return {"status": "enabled", "platform": platform}


@router.post("/platforms/{platform}/disable")
def disable_platform(
    platform: str,
    db: DbSessionDep,
    _admin: AdminUserDep,
    _: BotsEnabledDep,
) -> dict[str, str]:
    """Disable a bot platform."""
    config = db.query(BotWebhookConfig).filter_by(platform=platform).first()
    if not config:
        raise HTTPException(status_code=404, detail="Platform not configured")

    config.enabled = False
    db.commit()

    return {"status": "disabled", "platform": platform}


# =============================================================================
# Linked Accounts Endpoints
# =============================================================================


@router.get("/accounts")
def list_linked_accounts(
    db: DbSessionDep,
    _admin: AdminUserDep,
    _: BotsEnabledDep,
    platform: str | None = Query(None, description="Filter by platform"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[LinkedAccountResponse]:
    """List all linked user accounts."""
    query = select(BotPlatformAccount).order_by(BotPlatformAccount.created_at.desc())

    if platform:
        query = query.where(BotPlatformAccount.platform == platform)

    query = query.limit(limit).offset(offset)
    accounts = list(db.execute(query).scalars().all())

    result = []
    for account in accounts:
        # Get last message time
        last_msg = db.execute(
            select(BotMessage.created_at)
            .join(BotConversation)
            .where(BotConversation.platform_account_id == account.id)
            .order_by(BotMessage.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        result.append(
            LinkedAccountResponse(
                id=account.id,
                user_id=account.user_id,
                username=account.user.username if account.user else None,
                platform=account.platform,
                platform_user_id=account.platform_user_id,
                platform_username=account.platform_username,
                verified=account.verified,
                created_at=account.created_at,
                last_message_at=last_msg,
            )
        )

    return result


@router.delete("/accounts/{account_id}")
def unlink_account(
    account_id: int,
    db: DbSessionDep,
    _admin: AdminUserDep,
    _: BotsEnabledDep,
) -> dict[str, str]:
    """Unlink a platform account."""
    linking = UserLinkingService(db)
    if linking.unlink_account(account_id):
        return {"status": "unlinked"}
    raise HTTPException(status_code=404, detail="Account not found")


# =============================================================================
# Conversations Endpoints
# =============================================================================


@router.get("/conversations")
def list_conversations(
    db: DbSessionDep,
    _admin: AdminUserDep,
    _: BotsEnabledDep,
    platform: str | None = Query(None),
    user_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[ConversationResponse]:
    """List bot conversations."""
    query = select(BotConversation).order_by(BotConversation.last_message_at.desc())

    if platform:
        query = query.where(BotConversation.platform == platform)

    if user_id:
        # Join with platform accounts to filter by user
        query = query.join(BotPlatformAccount).where(BotPlatformAccount.user_id == user_id)

    query = query.limit(limit).offset(offset)
    conversations = list(db.execute(query).scalars().all())

    result = []
    for conv in conversations:
        message_count = db.execute(
            select(func.count(BotMessage.id)).where(BotMessage.conversation_id == conv.id)
        ).scalar() or 0

        account = conv.platform_account
        result.append(
            ConversationResponse(
                id=conv.id,
                platform=conv.platform,
                platform_conversation_id=conv.platform_conversation_id,
                user_id=account.user_id,
                username=account.user.username if account.user else None,
                agent_id=conv.agent_id,
                session_id=conv.session_id,
                message_count=message_count,
                created_at=conv.created_at,
                last_message_at=conv.last_message_at,
            )
        )

    return result


@router.get("/conversations/{conversation_id}/messages")
def get_conversation_messages(
    conversation_id: int,
    db: DbSessionDep,
    _admin: AdminUserDep,
    _: BotsEnabledDep,
    limit: int = Query(100, ge=1, le=500),
) -> list[MessageResponse]:
    """Get messages for a conversation."""
    conversation = db.get(BotConversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = list(
        db.execute(
            select(BotMessage)
            .where(BotMessage.conversation_id == conversation_id)
            .order_by(BotMessage.created_at.asc())
            .limit(limit)
        )
        .scalars()
        .all()
    )

    return [
        MessageResponse(
            id=msg.id,
            direction=msg.direction,
            content=msg.content,
            agent_id=msg.agent_id,
            tool_calls=msg.tool_calls,
            input_tokens=msg.input_tokens,
            output_tokens=msg.output_tokens,
            cost_usd=msg.cost_usd,
            duration_ms=msg.duration_ms,
            error=msg.error,
            created_at=msg.created_at,
        )
        for msg in messages
    ]


# =============================================================================
# Usage Statistics Endpoints
# =============================================================================


@router.get("/usage")
def get_usage_stats(
    db: DbSessionDep,
    _admin: AdminUserDep,
    _: BotsEnabledDep,
    days: int = Query(30, ge=1, le=365),
    platform: str | None = Query(None),
) -> UsageStats:
    """Get bot usage statistics."""
    now = datetime.now(UTC)
    start_date = now - timedelta(days=days)

    # Base query filters
    message_filter = [BotMessage.created_at >= start_date]
    if platform:
        message_filter.append(BotConversation.platform == platform)

    # Total messages
    total_messages = db.execute(
        select(func.count(BotMessage.id))
        .join(BotConversation)
        .where(*message_filter)
    ).scalar() or 0

    # Total conversations (with activity in period)
    total_conversations = db.execute(
        select(func.count(func.distinct(BotConversation.id)))
        .join(BotMessage)
        .where(*message_filter)
    ).scalar() or 0

    # Total linked accounts
    account_filter = [BotPlatformAccount.verified == True]  # noqa: E712
    if platform:
        account_filter.append(BotPlatformAccount.platform == platform)

    total_linked_accounts = db.execute(
        select(func.count(BotPlatformAccount.id)).where(*account_filter)
    ).scalar() or 0

    # Token usage
    total_input_tokens = db.execute(
        select(func.sum(BotMessage.input_tokens))
        .join(BotConversation)
        .where(*message_filter)
    ).scalar() or 0

    total_output_tokens = db.execute(
        select(func.sum(BotMessage.output_tokens))
        .join(BotConversation)
        .where(*message_filter)
    ).scalar() or 0

    total_cost = db.execute(
        select(func.sum(BotMessage.cost_usd))
        .join(BotConversation)
        .where(*message_filter)
    ).scalar() or 0.0

    # Messages by platform
    platform_counts = db.execute(
        select(BotConversation.platform, func.count(BotMessage.id))
        .join(BotConversation)
        .where(BotMessage.created_at >= start_date)
        .group_by(BotConversation.platform)
    ).all()
    messages_by_platform = {p: c for p, c in platform_counts}

    # Messages by agent
    agent_counts = db.execute(
        select(BotMessage.agent_id, func.count(BotMessage.id))
        .join(BotConversation)
        .where(BotMessage.created_at >= start_date, BotMessage.agent_id.isnot(None))
        .group_by(BotMessage.agent_id)
    ).all()
    messages_by_agent = {a or "unknown": c for a, c in agent_counts}

    return UsageStats(
        period_days=days,
        total_messages=total_messages,
        total_conversations=total_conversations,
        total_linked_accounts=total_linked_accounts,
        total_input_tokens=total_input_tokens,
        total_output_tokens=total_output_tokens,
        total_cost_usd=float(total_cost),
        messages_by_platform=messages_by_platform,
        messages_by_agent=messages_by_agent,
    )


# =============================================================================
# User Account Linking (for regular users)
# =============================================================================


@router.post("/link/{platform}/generate-code")
def generate_verification_code(
    platform: str,
    db: DbSessionDep,
    user: CurrentUserDep,
    _: BotsEnabledDep,
) -> VerificationCodeResponse:
    """Generate a verification code for linking a platform account.

    This endpoint is available to regular users (not just admins) so they
    can link their own accounts.
    """
    if platform not in ["telegram", "slack", "teams"]:
        raise HTTPException(status_code=400, detail="Invalid platform")

    linking = UserLinkingService(db)
    code = linking.generate_verification_code(user.id, platform)

    # Code expires in 10 minutes
    expires_at = datetime.now(UTC) + timedelta(minutes=10)

    return VerificationCodeResponse(
        code=code,
        expires_at=expires_at,
        platform=platform,
    )


@router.get("/link/my-accounts")
def get_my_linked_accounts(
    db: DbSessionDep,
    user: CurrentUserDep,
    _: BotsEnabledDep,
) -> list[LinkedAccountResponse]:
    """Get the current user's linked platform accounts."""
    linking = UserLinkingService(db)
    accounts = linking.get_user_accounts(user.id)

    return [
        LinkedAccountResponse(
            id=account.id,
            user_id=account.user_id,
            username=user.username,
            platform=account.platform,
            platform_user_id=account.platform_user_id,
            platform_username=account.platform_username,
            verified=account.verified,
            created_at=account.created_at,
        )
        for account in accounts
    ]


@router.delete("/link/my-accounts/{platform}")
def unlink_my_account(
    platform: str,
    db: DbSessionDep,
    user: CurrentUserDep,
    _: BotsEnabledDep,
) -> dict[str, str]:
    """Unlink the current user's account from a platform."""
    if platform not in ["telegram", "slack", "teams"]:
        raise HTTPException(status_code=400, detail="Invalid platform")

    linking = UserLinkingService(db)
    if linking.unlink_user_platform(user.id, platform):
        return {"status": "unlinked", "platform": platform}
    raise HTTPException(status_code=404, detail="No linked account found for this platform")
