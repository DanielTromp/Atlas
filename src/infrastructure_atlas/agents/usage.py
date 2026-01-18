"""Usage tracking service for the Agent Playground.

This module provides:
- Per-message usage logging to database
- Structured logging for operational monitoring
- Cost calculation based on model pricing
- Usage statistics and aggregation queries
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from infrastructure_atlas.db.models import PlaygroundUsage
from infrastructure_atlas.infrastructure.logging import get_logger

logger = get_logger(__name__)


# ============================================================================
# Model Pricing (USD per 1M tokens) - Update as needed
# ============================================================================
MODEL_PRICING = {
    # Anthropic Claude models
    "claude-3-5-haiku-20241022": {"input": 1.00, "output": 5.00},
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00},
    "claude-sonnet-4-5-20250929": {"input": 3.00, "output": 15.00},
    "claude-opus-4-20250514": {"input": 15.00, "output": 75.00},
    "claude-opus-4-5-20251101": {"input": 15.00, "output": 75.00},
    # Default fallback
    "default": {"input": 3.00, "output": 15.00},
}


def get_model_pricing(model: str) -> dict[str, float]:
    """Get pricing for a model (USD per 1M tokens)."""
    return MODEL_PRICING.get(model, MODEL_PRICING["default"])


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate cost in USD for a request.

    Args:
        model: Model identifier
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens

    Returns:
        Cost in USD
    """
    pricing = get_model_pricing(model)
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    return round(input_cost + output_cost, 6)


@dataclass
class UsageRecord:
    """A single usage record for logging."""

    session_id: str
    agent_id: str
    model: str
    user_message: str
    assistant_message: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: list[dict[str, Any]] | None = None
    duration_ms: int | None = None
    error: str | None = None
    user_id: str | None = None
    username: str | None = None
    client: str | None = None  # web, telegram, slack, teams

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def cost_usd(self) -> float:
        return calculate_cost(self.model, self.input_tokens, self.output_tokens)


class UsageService:
    """Service for recording and querying playground usage."""

    def __init__(self, db: Session):
        self.db = db

    def record(self, record: UsageRecord) -> PlaygroundUsage:
        """Record a usage entry to database and emit structured log.

        Args:
            record: UsageRecord with all the details

        Returns:
            The created PlaygroundUsage database record
        """
        # Create database record
        usage = PlaygroundUsage(
            user_id=record.user_id,
            username=record.username,
            client=record.client or "web",
            session_id=record.session_id,
            agent_id=record.agent_id,
            model=record.model,
            user_message=record.user_message,
            assistant_message=record.assistant_message,
            input_tokens=record.input_tokens,
            output_tokens=record.output_tokens,
            total_tokens=record.total_tokens,
            cost_usd=record.cost_usd,
            tool_calls=record.tool_calls,
            duration_ms=record.duration_ms,
            error=record.error,
        )

        try:
            self.db.add(usage)
            self.db.commit()
            self.db.refresh(usage)
        except Exception as e:
            logger.error(f"Failed to record usage to DB: {e!s}")
            self.db.rollback()
            raise

        # Emit structured log for operational monitoring
        logger.info(
            "Playground usage recorded",
            extra={
                "event": "playground_usage",
                "usage_id": usage.id,
                "user_id": record.user_id,
                "username": record.username,
                "client": record.client or "web",
                "session_id": record.session_id,
                "agent_id": record.agent_id,
                "model": record.model,
                "input_tokens": record.input_tokens,
                "output_tokens": record.output_tokens,
                "total_tokens": record.total_tokens,
                "cost_usd": record.cost_usd,
                "tool_call_count": len(record.tool_calls) if record.tool_calls else 0,
                "duration_ms": record.duration_ms,
                "has_error": record.error is not None,
            },
        )

        return usage

    def get_user_stats(
        self,
        user_id: str | None = None,
        days: int = 30,
    ) -> dict[str, Any]:
        """Get usage statistics for a user.

        Args:
            user_id: User ID to filter by (None for current session only)
            days: Number of days to look back

        Returns:
            Dict with usage statistics
        """
        since = datetime.now(UTC) - timedelta(days=days)

        query = select(
            func.count(PlaygroundUsage.id).label("total_requests"),
            func.sum(PlaygroundUsage.input_tokens).label("total_input_tokens"),
            func.sum(PlaygroundUsage.output_tokens).label("total_output_tokens"),
            func.sum(PlaygroundUsage.total_tokens).label("total_tokens"),
            func.sum(PlaygroundUsage.cost_usd).label("total_cost_usd"),
            func.avg(PlaygroundUsage.duration_ms).label("avg_duration_ms"),
        ).where(PlaygroundUsage.created_at >= since)

        if user_id:
            query = query.where(PlaygroundUsage.user_id == user_id)

        result = self.db.execute(query).first()

        return {
            "total_requests": result.total_requests or 0,
            "total_input_tokens": result.total_input_tokens or 0,
            "total_output_tokens": result.total_output_tokens or 0,
            "total_tokens": result.total_tokens or 0,
            "total_cost_usd": round(result.total_cost_usd or 0, 4),
            "avg_duration_ms": round(result.avg_duration_ms or 0, 0),
            "period_days": days,
        }

    def get_user_stats_by_agent(
        self,
        user_id: str | None = None,
        days: int = 30,
    ) -> list[dict[str, Any]]:
        """Get usage statistics grouped by agent.

        Args:
            user_id: User ID to filter by
            days: Number of days to look back

        Returns:
            List of dicts with per-agent statistics
        """
        since = datetime.now(UTC) - timedelta(days=days)

        query = (
            select(
                PlaygroundUsage.agent_id,
                func.count(PlaygroundUsage.id).label("requests"),
                func.sum(PlaygroundUsage.total_tokens).label("tokens"),
                func.sum(PlaygroundUsage.cost_usd).label("cost_usd"),
            )
            .where(PlaygroundUsage.created_at >= since)
            .group_by(PlaygroundUsage.agent_id)
            .order_by(func.sum(PlaygroundUsage.total_tokens).desc())
        )

        if user_id:
            query = query.where(PlaygroundUsage.user_id == user_id)

        results = self.db.execute(query).all()

        return [
            {
                "agent_id": row.agent_id,
                "requests": row.requests,
                "tokens": row.tokens or 0,
                "cost_usd": round(row.cost_usd or 0, 4),
            }
            for row in results
        ]

    def get_all_users_stats(self, days: int = 30) -> list[dict[str, Any]]:
        """Get usage statistics for all users (admin view).

        Args:
            days: Number of days to look back

        Returns:
            List of dicts with per-user statistics
        """
        since = datetime.now(UTC) - timedelta(days=days)

        query = (
            select(
                PlaygroundUsage.user_id,
                PlaygroundUsage.username,
                func.count(PlaygroundUsage.id).label("requests"),
                func.sum(PlaygroundUsage.total_tokens).label("tokens"),
                func.sum(PlaygroundUsage.cost_usd).label("cost_usd"),
                func.max(PlaygroundUsage.created_at).label("last_used"),
            )
            .where(PlaygroundUsage.created_at >= since)
            .group_by(PlaygroundUsage.user_id, PlaygroundUsage.username)
            .order_by(func.sum(PlaygroundUsage.cost_usd).desc())
        )

        results = self.db.execute(query).all()

        return [
            {
                "user_id": row.user_id,
                "username": row.username or "anonymous",
                "requests": row.requests,
                "tokens": row.tokens or 0,
                "cost_usd": round(row.cost_usd or 0, 4),
                "last_used": row.last_used.isoformat() if row.last_used else None,
            }
            for row in results
        ]

    def get_overall_stats(self, days: int = 30) -> dict[str, Any]:
        """Get overall platform usage statistics (admin view).

        Args:
            days: Number of days to look back

        Returns:
            Dict with overall statistics
        """
        since = datetime.now(UTC) - timedelta(days=days)

        # Get main stats
        main_query = select(
            func.count(PlaygroundUsage.id).label("total_requests"),
            func.sum(PlaygroundUsage.total_tokens).label("total_tokens"),
            func.sum(PlaygroundUsage.cost_usd).label("total_cost_usd"),
            func.count(func.distinct(PlaygroundUsage.user_id)).label("unique_users"),
            func.count(func.distinct(PlaygroundUsage.session_id)).label("unique_sessions"),
        ).where(PlaygroundUsage.created_at >= since)

        main_result = self.db.execute(main_query).first()

        # Get per-model breakdown
        model_query = (
            select(
                PlaygroundUsage.model,
                func.count(PlaygroundUsage.id).label("requests"),
                func.sum(PlaygroundUsage.total_tokens).label("tokens"),
                func.sum(PlaygroundUsage.cost_usd).label("cost_usd"),
            )
            .where(PlaygroundUsage.created_at >= since)
            .group_by(PlaygroundUsage.model)
            .order_by(func.sum(PlaygroundUsage.cost_usd).desc())
        )

        model_results = self.db.execute(model_query).all()

        return {
            "total_requests": main_result.total_requests or 0,
            "total_tokens": main_result.total_tokens or 0,
            "total_cost_usd": round(main_result.total_cost_usd or 0, 4),
            "unique_users": main_result.unique_users or 0,
            "unique_sessions": main_result.unique_sessions or 0,
            "period_days": days,
            "by_model": [
                {
                    "model": row.model,
                    "requests": row.requests,
                    "tokens": row.tokens or 0,
                    "cost_usd": round(row.cost_usd or 0, 4),
                }
                for row in model_results
            ],
        }

    def get_recent_usage(
        self,
        user_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get recent usage records.

        Args:
            user_id: Filter by user ID (None for all)
            limit: Maximum records to return

        Returns:
            List of recent usage records
        """
        query = (
            select(PlaygroundUsage)
            .order_by(PlaygroundUsage.created_at.desc())
            .limit(limit)
        )

        if user_id:
            query = query.where(PlaygroundUsage.user_id == user_id)

        results = self.db.execute(query).scalars().all()

        return [
            {
                "id": r.id,
                "user_id": r.user_id,
                "username": r.username,
                "client": r.client or "web",
                "session_id": r.session_id,
                "agent_id": r.agent_id,
                "model": r.model,
                "user_message": r.user_message[:100] + "..." if len(r.user_message) > 100 else r.user_message,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "total_tokens": r.total_tokens,
                "cost_usd": r.cost_usd,
                "tool_calls": len(r.tool_calls) if r.tool_calls else 0,
                "duration_ms": r.duration_ms,
                "error": r.error[:100] if r.error else None,
                "created_at": r.created_at.isoformat(),
            }
            for r in results
        ]
