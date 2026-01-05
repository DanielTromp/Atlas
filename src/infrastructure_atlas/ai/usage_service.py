"""AI Usage tracking service for logging API calls and managing costs."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from infrastructure_atlas.db.models import AIActivityLog, AIModelConfig, User
from infrastructure_atlas.infrastructure.logging import get_logger

from .pricing import PRICING, calculate_cost

logger = get_logger(__name__)


@dataclass
class UsageStats:
    """Aggregated usage statistics."""

    total_requests: int = 0
    total_tokens: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_reasoning_tokens: int = 0
    total_cost_usd: float = 0.0
    avg_tokens_per_request: float = 0.0
    avg_cost_per_request: float = 0.0
    avg_tokens_per_second: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_requests": self.total_requests,
            "total_tokens": self.total_tokens,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_reasoning_tokens": self.total_reasoning_tokens,
            "total_cost_usd": round(self.total_cost_usd, 4),
            "avg_tokens_per_request": round(self.avg_tokens_per_request, 1),
            "avg_cost_per_request": round(self.avg_cost_per_request, 6),
            "avg_tokens_per_second": round(self.avg_tokens_per_second, 1),
        }


@dataclass
class ModelUsageStats:
    """Usage statistics for a specific model."""

    provider: str
    model: str
    request_count: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    avg_tokens_per_second: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "request_count": self.request_count,
            "total_tokens": self.total_tokens,
            "total_cost_usd": round(self.total_cost_usd, 4),
            "avg_tokens_per_second": round(self.avg_tokens_per_second, 1),
        }


class AIUsageService:
    """Service for tracking AI API usage and managing costs."""

    def __init__(self, session: Session):
        self._session = session

    def log_activity(
        self,
        provider: str,
        model: str,
        tokens_prompt: int = 0,
        tokens_completion: int = 0,
        tokens_reasoning: int = 0,
        generation_time_ms: int | None = None,
        time_to_first_token_ms: int | None = None,
        tokens_per_second: float | None = None,
        streamed: bool = True,
        finish_reason: str | None = None,
        cancelled: bool = False,
        user_id: str | None = None,
        session_id: str | None = None,
        app_name: str | None = None,
        generation_id: str | None = None,
        model_provider: str | None = None,
    ) -> AIActivityLog:
        """Log an AI API call to the activity log.

        Args:
            provider: The provider used (e.g., 'openrouter', 'openai')
            model: The model identifier
            tokens_prompt: Number of prompt/input tokens
            tokens_completion: Number of completion/output tokens
            tokens_reasoning: Number of reasoning tokens (for o1, etc.)
            generation_time_ms: Total generation time in milliseconds
            time_to_first_token_ms: Time to first token in milliseconds
            tokens_per_second: Tokens per second throughput
            streamed: Whether the response was streamed
            finish_reason: Reason for completion (e.g., 'stop', 'length')
            cancelled: Whether the request was cancelled
            user_id: Optional user ID
            session_id: Optional session ID
            app_name: Optional app name identifier
            generation_id: Optional generation ID from provider
            model_provider: The underlying model provider (for OpenRouter)

        Returns:
            The created AIActivityLog entry
        """
        # Calculate cost
        cost_info = calculate_cost(model, tokens_prompt, tokens_completion)
        cost_usd = cost_info.cost_usd

        # Check for custom pricing override
        custom_config = self.get_model_config(provider, model)
        if custom_config:
            input_cost = (tokens_prompt / 1_000_000) * custom_config.price_input_per_million
            output_cost = (tokens_completion / 1_000_000) * custom_config.price_output_per_million
            cost_usd = input_cost + output_cost

        total_tokens = tokens_prompt + tokens_completion + tokens_reasoning

        log_entry = AIActivityLog(
            generation_id=generation_id,
            provider=provider,
            model=model,
            model_provider=model_provider,
            tokens_prompt=tokens_prompt,
            tokens_completion=tokens_completion,
            tokens_reasoning=tokens_reasoning,
            tokens_total=total_tokens,
            cost_usd=cost_usd,
            generation_time_ms=generation_time_ms,
            time_to_first_token_ms=time_to_first_token_ms,
            tokens_per_second=tokens_per_second,
            streamed=streamed,
            finish_reason=finish_reason,
            cancelled=cancelled,
            user_id=user_id,
            session_id=session_id,
            app_name=app_name,
        )

        self._session.add(log_entry)
        self._session.commit()

        logger.debug(
            f"Logged AI activity: {provider}/{model} - "
            f"{total_tokens} tokens, ${cost_usd:.6f}"
        )

        return log_entry

    def get_activity_logs(
        self,
        limit: int = 100,
        offset: int = 0,
        provider: str | None = None,
        model: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Get activity logs with optional filtering.

        Returns:
            Tuple of (list of log entries as dicts, total count)
        """
        query = select(AIActivityLog)

        if provider:
            query = query.where(AIActivityLog.provider == provider)
        if model:
            query = query.where(AIActivityLog.model == model)
        if user_id:
            query = query.where(AIActivityLog.user_id == user_id)
        if session_id:
            query = query.where(AIActivityLog.session_id == session_id)
        if start_date:
            query = query.where(AIActivityLog.created_at >= start_date)
        if end_date:
            query = query.where(AIActivityLog.created_at <= end_date)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total = self._session.execute(count_query).scalar() or 0

        # Get paginated results
        query = query.order_by(desc(AIActivityLog.created_at)).offset(offset).limit(limit)
        results = self._session.execute(query).scalars().all()

        logs = []
        for log in results:
            logs.append(self._log_to_dict(log))

        return logs, total

    def _log_to_dict(self, log: AIActivityLog) -> dict[str, Any]:
        """Convert a log entry to a dictionary."""
        return {
            "id": log.id,
            "generation_id": log.generation_id,
            "created_at": log.created_at.isoformat() if log.created_at else None,
            "provider": log.provider,
            "model": log.model,
            "model_provider": log.model_provider,
            "tokens_prompt": log.tokens_prompt,
            "tokens_completion": log.tokens_completion,
            "tokens_reasoning": log.tokens_reasoning,
            "tokens_total": log.tokens_total,
            "cost_usd": round(log.cost_usd, 6),
            "generation_time_ms": log.generation_time_ms,
            "time_to_first_token_ms": log.time_to_first_token_ms,
            "tokens_per_second": round(log.tokens_per_second, 1) if log.tokens_per_second else None,
            "streamed": log.streamed,
            "finish_reason": log.finish_reason,
            "cancelled": log.cancelled,
            "user_id": log.user_id,
            "session_id": log.session_id,
            "app_name": log.app_name,
        }

    def get_usage_stats(
        self,
        provider: str | None = None,
        model: str | None = None,
        user_id: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> UsageStats:
        """Get aggregated usage statistics."""
        query = select(
            func.count(AIActivityLog.id).label("total_requests"),
            func.sum(AIActivityLog.tokens_total).label("total_tokens"),
            func.sum(AIActivityLog.tokens_prompt).label("total_prompt"),
            func.sum(AIActivityLog.tokens_completion).label("total_completion"),
            func.sum(AIActivityLog.tokens_reasoning).label("total_reasoning"),
            func.sum(AIActivityLog.cost_usd).label("total_cost"),
            func.avg(AIActivityLog.tokens_per_second).label("avg_tps"),
        )

        if provider:
            query = query.where(AIActivityLog.provider == provider)
        if model:
            query = query.where(AIActivityLog.model == model)
        if user_id:
            query = query.where(AIActivityLog.user_id == user_id)
        if start_date:
            query = query.where(AIActivityLog.created_at >= start_date)
        if end_date:
            query = query.where(AIActivityLog.created_at <= end_date)

        result = self._session.execute(query).one()

        total_requests = result.total_requests or 0
        total_tokens = result.total_tokens or 0
        total_cost = result.total_cost or 0.0

        return UsageStats(
            total_requests=total_requests,
            total_tokens=total_tokens,
            total_prompt_tokens=result.total_prompt or 0,
            total_completion_tokens=result.total_completion or 0,
            total_reasoning_tokens=result.total_reasoning or 0,
            total_cost_usd=total_cost,
            avg_tokens_per_request=total_tokens / total_requests if total_requests > 0 else 0,
            avg_cost_per_request=total_cost / total_requests if total_requests > 0 else 0,
            avg_tokens_per_second=result.avg_tps or 0.0,
        )

    def get_usage_by_model(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 20,
    ) -> list[ModelUsageStats]:
        """Get usage statistics grouped by model."""
        query = select(
            AIActivityLog.provider,
            AIActivityLog.model,
            func.count(AIActivityLog.id).label("request_count"),
            func.sum(AIActivityLog.tokens_total).label("total_tokens"),
            func.sum(AIActivityLog.cost_usd).label("total_cost"),
            func.avg(AIActivityLog.tokens_per_second).label("avg_tps"),
        ).group_by(
            AIActivityLog.provider,
            AIActivityLog.model,
        )

        if start_date:
            query = query.where(AIActivityLog.created_at >= start_date)
        if end_date:
            query = query.where(AIActivityLog.created_at <= end_date)

        query = query.order_by(desc("total_cost")).limit(limit)

        results = self._session.execute(query).all()

        return [
            ModelUsageStats(
                provider=row.provider,
                model=row.model,
                request_count=row.request_count or 0,
                total_tokens=row.total_tokens or 0,
                total_cost_usd=row.total_cost or 0.0,
                avg_tokens_per_second=row.avg_tps or 0.0,
            )
            for row in results
        ]

    def get_usage_over_time(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        granularity: str = "day",
    ) -> list[dict[str, Any]]:
        """Get usage statistics over time.

        Args:
            start_date: Start date filter
            end_date: End date filter
            granularity: 'hour', 'day', or 'month'
        """
        # SQLite date function format
        if granularity == "hour":
            date_format = "%Y-%m-%d %H:00"
        elif granularity == "month":
            date_format = "%Y-%m"
        else:  # day
            date_format = "%Y-%m-%d"

        date_func = func.strftime(date_format, AIActivityLog.created_at)

        query = select(
            date_func.label("period"),
            func.count(AIActivityLog.id).label("request_count"),
            func.sum(AIActivityLog.tokens_total).label("total_tokens"),
            func.sum(AIActivityLog.cost_usd).label("total_cost"),
        ).group_by(date_func)

        if start_date:
            query = query.where(AIActivityLog.created_at >= start_date)
        if end_date:
            query = query.where(AIActivityLog.created_at <= end_date)

        query = query.order_by(date_func)

        results = self._session.execute(query).all()

        return [
            {
                "period": row.period,
                "request_count": row.request_count or 0,
                "total_tokens": row.total_tokens or 0,
                "total_cost_usd": round(row.total_cost or 0.0, 4),
            }
            for row in results
        ]

    def export_activity_csv(
        self,
        provider: str | None = None,
        model: str | None = None,
        user_id: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> str:
        """Export activity logs to CSV format.

        Returns:
            CSV content as a string
        """
        logs, _ = self.get_activity_logs(
            limit=10000,  # Max export limit
            offset=0,
            provider=provider,
            model=model,
            user_id=user_id,
            start_date=start_date,
            end_date=end_date,
        )

        output = io.StringIO()
        writer = csv.writer(output)

        # Header row (matching OpenRouter format)
        writer.writerow([
            "Timestamp",
            "Provider/Model",
            "Model Provider",
            "App",
            "Tokens (Prompt)",
            "Tokens (Completion)",
            "Tokens (Reasoning)",
            "Tokens (Total)",
            "Cost",
            "Latency (TTFT)",
            "Speed (T/s)",
            "Finish Reason",
            "Generation ID",
            "Session ID",
        ])

        for log in logs:
            writer.writerow([
                log["created_at"],
                f"{log['provider']}/{log['model']}",
                log["model_provider"] or "",
                log["app_name"] or "",
                log["tokens_prompt"],
                log["tokens_completion"],
                log["tokens_reasoning"],
                log["tokens_total"],
                f"${log['cost_usd']:.6f}",
                f"{log['time_to_first_token_ms']}ms" if log["time_to_first_token_ms"] else "",
                f"{log['tokens_per_second']:.1f}" if log["tokens_per_second"] else "",
                log["finish_reason"] or "",
                log["generation_id"] or "",
                log["session_id"] or "",
            ])

        return output.getvalue()

    # Model Configuration Methods

    def get_model_config(self, provider: str, model_id: str) -> AIModelConfig | None:
        """Get a custom model configuration."""
        query = select(AIModelConfig).where(
            AIModelConfig.provider == provider,
            AIModelConfig.model_id == model_id,
        )
        return self._session.execute(query).scalar_one_or_none()

    def list_model_configs(
        self,
        provider: str | None = None,
        active_only: bool = True,
    ) -> list[dict[str, Any]]:
        """List all model configurations."""
        query = select(AIModelConfig)

        if provider:
            query = query.where(AIModelConfig.provider == provider)
        if active_only:
            query = query.where(AIModelConfig.is_active == True)  # noqa: E712

        query = query.order_by(AIModelConfig.provider, AIModelConfig.model_id)
        results = self._session.execute(query).scalars().all()

        return [self._config_to_dict(config) for config in results]

    def _config_to_dict(self, config: AIModelConfig) -> dict[str, Any]:
        """Convert a model config to a dictionary."""
        return {
            "id": config.id,
            "provider": config.provider,
            "model_id": config.model_id,
            "display_name": config.display_name,
            "price_input_per_million": config.price_input_per_million,
            "price_output_per_million": config.price_output_per_million,
            "context_window": config.context_window,
            "supports_tools": config.supports_tools,
            "supports_streaming": config.supports_streaming,
            "supports_vision": config.supports_vision,
            "is_active": config.is_active,
            "is_preferred": config.is_preferred,
            "created_at": config.created_at.isoformat() if config.created_at else None,
            "updated_at": config.updated_at.isoformat() if config.updated_at else None,
        }

    def create_model_config(
        self,
        provider: str,
        model_id: str,
        display_name: str | None = None,
        price_input_per_million: float = 0.0,
        price_output_per_million: float = 0.0,
        context_window: int | None = None,
        supports_tools: bool = True,
        supports_streaming: bool = True,
        supports_vision: bool = False,
        is_active: bool = True,
        is_preferred: bool = False,
    ) -> dict[str, Any]:
        """Create a new model configuration."""
        # Check if config already exists
        existing = self.get_model_config(provider, model_id)
        if existing:
            raise ValueError(f"Model config for {provider}/{model_id} already exists")

        config = AIModelConfig(
            provider=provider,
            model_id=model_id,
            display_name=display_name,
            price_input_per_million=price_input_per_million,
            price_output_per_million=price_output_per_million,
            context_window=context_window,
            supports_tools=supports_tools,
            supports_streaming=supports_streaming,
            supports_vision=supports_vision,
            is_active=is_active,
            is_preferred=is_preferred,
        )

        self._session.add(config)
        self._session.commit()

        logger.info(f"Created model config: {provider}/{model_id}")
        return self._config_to_dict(config)

    def update_model_config(
        self,
        config_id: str,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        """Update a model configuration."""
        query = select(AIModelConfig).where(AIModelConfig.id == config_id)
        config = self._session.execute(query).scalar_one_or_none()

        if not config:
            return None

        allowed_fields = {
            "display_name",
            "price_input_per_million",
            "price_output_per_million",
            "context_window",
            "supports_tools",
            "supports_streaming",
            "supports_vision",
            "is_active",
            "is_preferred",
        }

        for key, value in kwargs.items():
            if key in allowed_fields:
                setattr(config, key, value)

        self._session.commit()

        logger.info(f"Updated model config: {config.provider}/{config.model_id}")
        return self._config_to_dict(config)

    def delete_model_config(self, config_id: str) -> bool:
        """Delete a model configuration."""
        query = select(AIModelConfig).where(AIModelConfig.id == config_id)
        config = self._session.execute(query).scalar_one_or_none()

        if not config:
            return False

        self._session.delete(config)
        self._session.commit()

        logger.info(f"Deleted model config: {config.provider}/{config.model_id}")
        return True

    def get_default_pricing(self, model: str) -> dict[str, Any]:
        """Get default pricing for a model from the built-in pricing data."""
        model_lower = model.lower()

        for key, price in PRICING.items():
            if key.lower() in model_lower or model_lower in key.lower():
                return {
                    "model": key,
                    "price_input_per_million": price[0],
                    "price_output_per_million": price[1],
                    "found": True,
                }

        return {
            "model": model,
            "price_input_per_million": 1.0,
            "price_output_per_million": 3.0,
            "found": False,
            "estimated": True,
        }

    def get_dashboard_stats(self) -> dict[str, Any]:
        """Get comprehensive dashboard statistics."""
        now = datetime.now(UTC)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=7)
        month_start = today_start - timedelta(days=30)

        # Overall stats
        overall = self.get_usage_stats()

        # Today's stats
        today_stats = self.get_usage_stats(start_date=today_start)

        # This week
        week_stats = self.get_usage_stats(start_date=week_start)

        # This month (30 days)
        month_stats = self.get_usage_stats(start_date=month_start)

        # Top models
        top_models = self.get_usage_by_model(start_date=month_start, limit=5)

        # Usage trend (last 7 days)
        daily_trend = self.get_usage_over_time(
            start_date=week_start,
            granularity="day",
        )

        return {
            "overall": overall.to_dict(),
            "today": today_stats.to_dict(),
            "this_week": week_stats.to_dict(),
            "this_month": month_stats.to_dict(),
            "top_models": [m.to_dict() for m in top_models],
            "daily_trend": daily_trend,
        }


def create_usage_service(session: Session) -> AIUsageService:
    """Factory function to create an AIUsageService."""
    return AIUsageService(session)


__all__ = [
    "AIUsageService",
    "UsageStats",
    "ModelUsageStats",
    "create_usage_service",
]
