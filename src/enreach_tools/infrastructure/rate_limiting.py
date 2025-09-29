"""Rate limiting and retry infrastructure for OpenAI API calls."""

from __future__ import annotations

import asyncio
import os
import random
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

from enreach_tools.infrastructure.logging import get_logger

logger = get_logger(__name__)

_SECURE_RANDOM = random.SystemRandom()

T = TypeVar("T")


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting behavior."""
    
    # Request rate limits
    requests_per_minute: int = 60
    requests_per_hour: int = 3000
    
    # Retry configuration
    max_retries: int = 5
    base_delay: float = 1.0
    max_delay: float = 300.0  # 5 minutes
    exponential_base: float = 2.0
    jitter_factor: float = 0.1
    
    # Stabilization period (15 minutes as recommended by OpenAI)
    stabilization_period_minutes: int = 15
    
    # Token limits
    tokens_per_minute: int = 150000
    tokens_per_hour: int = 1000000
    
    @classmethod
    def from_env(cls) -> RateLimitConfig:
        """Load configuration from environment variables."""
        return cls(
            requests_per_minute=int(os.getenv("OPENAI_REQUESTS_PER_MINUTE", "60")),
            requests_per_hour=int(os.getenv("OPENAI_REQUESTS_PER_HOUR", "3000")),
            max_retries=int(os.getenv("OPENAI_MAX_RETRIES", "5")),
            base_delay=float(os.getenv("OPENAI_BASE_DELAY", "1.0")),
            max_delay=float(os.getenv("OPENAI_MAX_DELAY", "300.0")),
            stabilization_period_minutes=int(os.getenv("OPENAI_STABILIZATION_MINUTES", "15")),
            tokens_per_minute=int(os.getenv("OPENAI_TOKENS_PER_MINUTE", "150000")),
            tokens_per_hour=int(os.getenv("OPENAI_TOKENS_PER_HOUR", "1000000")),
        )


@dataclass
class TokenUsage:
    """Token usage tracking for a single request."""
    
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class RateLimitState:
    """Current rate limiting state for tracking usage."""
    
    # Request tracking
    requests_this_minute: list[datetime] = field(default_factory=list)
    requests_this_hour: list[datetime] = field(default_factory=list)
    
    # Token tracking
    tokens_this_minute: list[tuple[datetime, int]] = field(default_factory=list)
    tokens_this_hour: list[tuple[datetime, int]] = field(default_factory=list)
    
    # Stabilization tracking
    last_rate_limit_error: datetime | None = None
    stabilization_active: bool = False
    
    # Error tracking
    consecutive_errors: int = 0
    last_error_time: datetime | None = None
    
    def cleanup_old_entries(self) -> None:
        """Remove entries older than their tracking windows."""
        now = datetime.now(UTC)
        minute_ago = now - timedelta(minutes=1)
        hour_ago = now - timedelta(hours=1)
        
        # Clean up request tracking
        self.requests_this_minute = [ts for ts in self.requests_this_minute if ts > minute_ago]
        self.requests_this_hour = [ts for ts in self.requests_this_hour if ts > hour_ago]
        
        # Clean up token tracking
        self.tokens_this_minute = [(ts, tokens) for ts, tokens in self.tokens_this_minute if ts > minute_ago]
        self.tokens_this_hour = [(ts, tokens) for ts, tokens in self.tokens_this_hour if ts > hour_ago]
    
    def add_request(self, token_count: int = 0) -> None:
        """Record a new request and its token usage."""
        now = datetime.now(UTC)
        self.requests_this_minute.append(now)
        self.requests_this_hour.append(now)
        
        if token_count > 0:
            self.tokens_this_minute.append((now, token_count))
            self.tokens_this_hour.append((now, token_count))
        
        self.cleanup_old_entries()
    
    def get_current_usage(self) -> dict[str, Any]:
        """Get current usage statistics."""
        self.cleanup_old_entries()
        
        tokens_minute = sum(tokens for _, tokens in self.tokens_this_minute)
        tokens_hour = sum(tokens for _, tokens in self.tokens_this_hour)
        
        return {
            "requests_per_minute": len(self.requests_this_minute),
            "requests_per_hour": len(self.requests_this_hour),
            "tokens_per_minute": tokens_minute,
            "tokens_per_hour": tokens_hour,
            "stabilization_active": self.stabilization_active,
            "consecutive_errors": self.consecutive_errors,
        }
    
    def check_stabilization_period(self, config: RateLimitConfig) -> bool:
        """Check if we're in a stabilization period after rate limiting."""
        if not self.last_rate_limit_error:
            self.stabilization_active = False
            return False
        
        now = datetime.now(UTC)
        stabilization_end = self.last_rate_limit_error + timedelta(minutes=config.stabilization_period_minutes)
        
        if now < stabilization_end:
            self.stabilization_active = True
            return True
        else:
            self.stabilization_active = False
            return False
    
    def record_rate_limit_error(self) -> None:
        """Record that a rate limit error occurred."""
        self.last_rate_limit_error = datetime.now(UTC)
        self.stabilization_active = True
        self.consecutive_errors += 1
        self.last_error_time = self.last_rate_limit_error
    
    def record_success(self) -> None:
        """Record a successful request."""
        self.consecutive_errors = 0
        self.last_error_time = None


class RateLimiter:
    """Rate limiter for OpenAI API requests with exponential backoff."""
    
    def __init__(self, config: RateLimitConfig | None = None):
        self.config = config or RateLimitConfig.from_env()
        self.state = RateLimitState()
        self._lock = asyncio.Lock()
    
    async def can_make_request(self, estimated_tokens: int = 0) -> tuple[bool, str | None]:
        """Check if a request can be made without exceeding rate limits."""
        async with self._lock:
            self.state.cleanup_old_entries()
            
            # Check stabilization period
            if self.state.check_stabilization_period(self.config):
                if self.state.last_rate_limit_error:
                    remaining = (
                        self.state.last_rate_limit_error +
                        timedelta(minutes=self.config.stabilization_period_minutes) -
                        datetime.now(UTC)
                    ).total_seconds()
                    return False, f"In stabilization period for {remaining:.0f} more seconds"
                else:
                    return False, "In stabilization period"
            
            usage = self.state.get_current_usage()
            
            # Check request limits
            if usage["requests_per_minute"] >= self.config.requests_per_minute:
                return False, "Request rate limit exceeded (per minute)"
            
            if usage["requests_per_hour"] >= self.config.requests_per_hour:
                return False, "Request rate limit exceeded (per hour)"
            
            # Check token limits
            if estimated_tokens > 0:
                if usage["tokens_per_minute"] + estimated_tokens > self.config.tokens_per_minute:
                    return False, "Token rate limit would be exceeded (per minute)"
                
                if usage["tokens_per_hour"] + estimated_tokens > self.config.tokens_per_hour:
                    return False, "Token rate limit would be exceeded (per hour)"
            
            return True, None
    
    async def record_request(self, token_count: int = 0) -> None:
        """Record that a request was made."""
        async with self._lock:
            self.state.add_request(token_count)
    
    async def record_rate_limit_error(self) -> None:
        """Record that a rate limit error occurred."""
        async with self._lock:
            self.state.record_rate_limit_error()
            logger.warning(
                "Rate limit error recorded, entering stabilization period",
                extra={
                    "event": "rate_limit_error",
                    "stabilization_minutes": self.config.stabilization_period_minutes,
                    "consecutive_errors": self.state.consecutive_errors,
                }
            )
    
    async def record_success(self) -> None:
        """Record that a request succeeded."""
        async with self._lock:
            self.state.record_success()
    
    def calculate_retry_delay(self, attempt: int) -> float:
        """Calculate delay for exponential backoff with jitter."""
        if attempt <= 0:
            return 0.0
        
        # Exponential backoff: base_delay * (exponential_base ^ attempt)
        delay = self.config.base_delay * (self.config.exponential_base ** (attempt - 1))
        
        # Add jitter to prevent thundering herd
        jitter = delay * self.config.jitter_factor * _SECURE_RANDOM.random()
        delay += jitter
        
        # Cap at max delay
        delay = min(delay, self.config.max_delay)
        
        # Additional delay if we have consecutive errors
        if self.state.consecutive_errors > 3:
            delay *= 1.5
        
        return delay
    
    async def get_usage_stats(self) -> dict[str, Any]:
        """Get current usage statistics."""
        async with self._lock:
            self.state.cleanup_old_entries()
            usage = self.state.get_current_usage()
            
            # Add rate limit percentages
            usage["request_utilization_minute"] = (
                usage["requests_per_minute"] / self.config.requests_per_minute * 100
            )
            usage["request_utilization_hour"] = (
                usage["requests_per_hour"] / self.config.requests_per_hour * 100
            )
            usage["token_utilization_minute"] = (
                usage["tokens_per_minute"] / self.config.tokens_per_minute * 100
            )
            usage["token_utilization_hour"] = (
                usage["tokens_per_hour"] / self.config.tokens_per_hour * 100
            )
            
            return usage


async def with_rate_limiting(
    func: Callable[..., T],
    rate_limiter: RateLimiter,
    estimated_tokens: int = 0,
    *args: Any,
    **kwargs: Any,
) -> T:
    """Execute a function with rate limiting and exponential backoff retry."""
    
    for attempt in range(1, rate_limiter.config.max_retries + 1):
        # Check if we can make the request
        can_proceed, reason = await rate_limiter.can_make_request(estimated_tokens)
        if not can_proceed:
            if attempt == 1:
                # Log the rate limit prevention
                logger.info(
                    "Request blocked by rate limiter",
                    extra={
                        "event": "rate_limit_blocked",
                        "reason": reason,
                        "estimated_tokens": estimated_tokens,
                    }
                )
            
            # Wait before retrying
            delay = rate_limiter.calculate_retry_delay(attempt)
            if delay > 0:
                logger.info(
                    f"Rate limit delay: waiting {delay:.1f}s before retry {attempt}",
                    extra={
                        "event": "rate_limit_delay",
                        "delay_seconds": delay,
                        "attempt": attempt,
                        "reason": reason,
                    }
                )
                await asyncio.sleep(delay)
            continue
        
        try:
            # Record the request attempt
            await rate_limiter.record_request(estimated_tokens)
            
            # Execute the function
            result = func(*args, **kwargs)
            
            # Handle async functions
            if asyncio.iscoroutine(result):
                result = await result
            
            # Record success
            await rate_limiter.record_success()
            
            logger.debug(
                "Rate limited request succeeded",
                extra={
                    "event": "rate_limit_success",
                    "attempt": attempt,
                    "estimated_tokens": estimated_tokens,
                }
            )
            
            return result  # type: ignore[return-value]
            
        except Exception as exc:
            # Check if this is a rate limit error
            is_rate_limit = _is_rate_limit_error(exc)
            is_server_error = _is_server_error(exc)
            
            if is_rate_limit:
                await rate_limiter.record_rate_limit_error()
                logger.warning(
                    "Rate limit error encountered",
                    extra={
                        "event": "rate_limit_error_caught",
                        "attempt": attempt,
                        "error": str(exc),
                        "entering_stabilization": True,
                    }
                )
            elif is_server_error:
                logger.warning(
                    "Server error encountered, will retry",
                    extra={
                        "event": "server_error_retry",
                        "attempt": attempt,
                        "error": str(exc),
                    }
                )
            else:
                # Non-retryable error
                logger.error(
                    "Non-retryable error in rate limited request",
                    extra={
                        "event": "rate_limit_non_retryable_error",
                        "attempt": attempt,
                        "error": str(exc),
                    }
                )
                raise
            
            # Don't retry on last attempt
            if attempt >= rate_limiter.config.max_retries:
                logger.error(
                    "Rate limited request failed after all retries",
                    extra={
                        "event": "rate_limit_max_retries_exceeded",
                        "max_retries": rate_limiter.config.max_retries,
                        "final_error": str(exc),
                    }
                )
                raise
            
            # Calculate delay for next attempt
            delay = rate_limiter.calculate_retry_delay(attempt)
            
            logger.info(
                f"Retrying after {delay:.1f}s (attempt {attempt + 1}/{rate_limiter.config.max_retries})",
                extra={
                    "event": "rate_limit_retry_delay",
                    "delay_seconds": delay,
                    "next_attempt": attempt + 1,
                    "max_retries": rate_limiter.config.max_retries,
                    "error_type": "rate_limit" if is_rate_limit else "server_error",
                }
            )
            
            await asyncio.sleep(delay)
    
    # This should never be reached due to the raise in the loop
    raise RuntimeError("Rate limited request failed unexpectedly")


def _is_rate_limit_error(exc: Exception) -> bool:
    """Check if an exception indicates a rate limit error."""
    # Check status code attributes
    for attr in ("status_code", "status", "http_status"):
        status = getattr(exc, attr, None)
        if status == 429:
            return True
    
    # Check error message content
    msg = str(exc).lower()
    rate_limit_indicators = [
        "rate limit",
        "too many requests",
        "quota exceeded",
        "rate_limit_exceeded",
        "requests per minute",
        "requests per hour",
    ]
    
    return any(indicator in msg for indicator in rate_limit_indicators)


def _is_server_error(exc: Exception) -> bool:
    """Check if an exception indicates a server error that should be retried."""
    # Check status code attributes
    for attr in ("status_code", "status", "http_status"):
        status = getattr(exc, attr, None)
        if status in (500, 502, 503, 504):
            return True
    
    # Check error message content
    msg = str(exc).lower()
    server_error_indicators = [
        "internal server error",
        "bad gateway",
        "service unavailable",
        "gateway timeout",
        "server error",
        "upstream error",
    ]
    
    return any(indicator in msg for indicator in server_error_indicators)


class TokenUsageTracker:
    """Tracks token usage across requests for analytics and cost monitoring."""
    
    def __init__(self):
        self._usage_history: list[TokenUsage] = []
        self._session_usage: dict[str, list[TokenUsage]] = defaultdict(list)
        self._lock = asyncio.Lock()
    
    async def record_usage(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int | None = None,
        cost_usd: float = 0.0,
        session_id: str | None = None,
    ) -> TokenUsage:
        """Record token usage for a request."""
        if total_tokens is None:
            total_tokens = prompt_tokens + completion_tokens
        
        usage = TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=cost_usd,
        )
        
        async with self._lock:
            self._usage_history.append(usage)
            
            if session_id:
                self._session_usage[session_id].append(usage)
            
            # Keep only last 1000 entries to prevent memory growth
            if len(self._usage_history) > 1000:
                self._usage_history = self._usage_history[-1000:]
        
        logger.info(
            "Token usage recorded",
            extra={
                "event": "token_usage_recorded",
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "cost_usd": cost_usd,
                "session_id": session_id,
            }
        )
        
        return usage
    
    async def get_session_usage(self, session_id: str) -> dict[str, Any]:
        """Get token usage statistics for a specific session."""
        async with self._lock:
            session_usage = self._session_usage.get(session_id, [])
            
            if not session_usage:
                return {
                    "total_prompt_tokens": 0,
                    "total_completion_tokens": 0,
                    "total_tokens": 0,
                    "total_cost_usd": 0.0,
                    "request_count": 0,
                }
            
            return {
                "total_prompt_tokens": sum(u.prompt_tokens for u in session_usage),
                "total_completion_tokens": sum(u.completion_tokens for u in session_usage),
                "total_tokens": sum(u.total_tokens for u in session_usage),
                "total_cost_usd": sum(u.cost_usd for u in session_usage),
                "request_count": len(session_usage),
                "first_request": session_usage[0].timestamp.isoformat(),
                "last_request": session_usage[-1].timestamp.isoformat(),
            }
    
    async def get_recent_usage(self, hours: int = 24) -> dict[str, Any]:
        """Get token usage statistics for recent time period."""
        cutoff = datetime.now(UTC) - timedelta(hours=hours)
        
        async with self._lock:
            recent_usage = [u for u in self._usage_history if u.timestamp > cutoff]
            
            if not recent_usage:
                return {
                    "total_prompt_tokens": 0,
                    "total_completion_tokens": 0,
                    "total_tokens": 0,
                    "total_cost_usd": 0.0,
                    "request_count": 0,
                    "time_period_hours": hours,
                }
            
            return {
                "total_prompt_tokens": sum(u.prompt_tokens for u in recent_usage),
                "total_completion_tokens": sum(u.completion_tokens for u in recent_usage),
                "total_tokens": sum(u.total_tokens for u in recent_usage),
                "total_cost_usd": sum(u.cost_usd for u in recent_usage),
                "request_count": len(recent_usage),
                "time_period_hours": hours,
                "average_tokens_per_request": sum(u.total_tokens for u in recent_usage) / len(recent_usage),
                "first_request": recent_usage[0].timestamp.isoformat(),
                "last_request": recent_usage[-1].timestamp.isoformat(),
            }


# Global instances
_GLOBAL_RATE_LIMITER: dict[str, RateLimiter | None] = {"instance": None}
_GLOBAL_TOKEN_TRACKER: dict[str, TokenUsageTracker | None] = {"instance": None}


def get_rate_limiter() -> RateLimiter:
    """Get the global rate limiter instance."""
    limiter = _GLOBAL_RATE_LIMITER.get("instance")
    if limiter is None:
        limiter = RateLimiter()
        _GLOBAL_RATE_LIMITER["instance"] = limiter
    return limiter


def get_token_tracker() -> TokenUsageTracker:
    """Get the global token usage tracker instance."""
    tracker = _GLOBAL_TOKEN_TRACKER.get("instance")
    if tracker is None:
        tracker = TokenUsageTracker()
        _GLOBAL_TOKEN_TRACKER["instance"] = tracker
    return tracker


__all__ = [
    "RateLimitConfig",
    "RateLimitState",
    "RateLimiter",
    "TokenUsage",
    "TokenUsageTracker",
    "get_rate_limiter",
    "get_token_tracker",
    "with_rate_limiting",
]
