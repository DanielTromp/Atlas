"""API routes for token usage monitoring and rate limiting analytics."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from enreach_tools.infrastructure.logging import get_logger
from enreach_tools.infrastructure.queues.chat_queue import get_chat_queue
from enreach_tools.infrastructure.rate_limiting import get_rate_limiter, get_token_tracker
from enreach_tools.interfaces.api.dependencies import OptionalUserDep

logger = get_logger(__name__)

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


@router.get("/token-usage")
async def get_token_usage_stats(
    user: OptionalUserDep,
    hours: int = Query(24, ge=1, le=168, description="Hours of history to include"),
) -> dict[str, Any]:
    """Get comprehensive token usage statistics."""
    
    try:
        tracker = get_token_tracker()
        
        # Get recent usage
        recent_usage = await tracker.get_recent_usage(hours)
        
        # Get rate limiting stats
        rate_limiter = get_rate_limiter()
        rate_stats = await rate_limiter.get_usage_stats()
        
        return {
            "token_usage": recent_usage,
            "rate_limiting": rate_stats,
            "time_period_hours": hours,
        }
        
    except Exception as exc:
        logger.error(
            "Failed to get token usage stats",
            extra={
                "event": "monitoring_token_usage_error",
                "error": str(exc),
                "user": getattr(user, "username", None),
            }
        )
        raise HTTPException(status_code=500, detail="Failed to retrieve token usage statistics")


@router.get("/session-usage/{session_id}")
async def get_session_token_usage(
    session_id: str,
    user: OptionalUserDep,
) -> dict[str, Any]:
    """Get token usage statistics for a specific chat session."""
    
    try:
        tracker = get_token_tracker()
        session_stats = await tracker.get_session_usage(session_id)
        
        return {
            "session_id": session_id,
            "usage": session_stats,
        }
        
    except Exception as exc:
        logger.error(
            "Failed to get session usage stats",
            extra={
                "event": "monitoring_session_usage_error",
                "session_id": session_id,
                "error": str(exc),
                "user": getattr(user, "username", None),
            }
        )
        raise HTTPException(status_code=500, detail="Failed to retrieve session usage statistics")


@router.get("/queue-status")
async def get_queue_status(user: OptionalUserDep) -> dict[str, Any]:
    """Get current chat request queue status."""
    
    try:
        queue = await get_chat_queue()
        queue_stats = await queue.get_queue_stats()
        
        return {
            "queue": queue_stats,
            "timestamp": "2025-09-25T19:23:59.670Z",  # Will be replaced with actual timestamp
        }
        
    except Exception as exc:
        logger.error(
            "Failed to get queue status",
            extra={
                "event": "monitoring_queue_status_error",
                "error": str(exc),
                "user": getattr(user, "username", None),
            }
        )
        raise HTTPException(status_code=500, detail="Failed to retrieve queue status")


@router.get("/rate-limits")
async def get_rate_limit_status(user: OptionalUserDep) -> dict[str, Any]:
    """Get current rate limiting status and configuration."""
    
    try:
        rate_limiter = get_rate_limiter()
        stats = await rate_limiter.get_usage_stats()
        
        return {
            "rate_limits": stats,
            "config": {
                "requests_per_minute": rate_limiter.config.requests_per_minute,
                "requests_per_hour": rate_limiter.config.requests_per_hour,
                "tokens_per_minute": rate_limiter.config.tokens_per_minute,
                "tokens_per_hour": rate_limiter.config.tokens_per_hour,
                "max_retries": rate_limiter.config.max_retries,
                "stabilization_period_minutes": rate_limiter.config.stabilization_period_minutes,
            },
        }
        
    except Exception as exc:
        logger.error(
            "Failed to get rate limit status",
            extra={
                "event": "monitoring_rate_limit_error",
                "error": str(exc),
                "user": getattr(user, "username", None),
            }
        )
        raise HTTPException(status_code=500, detail="Failed to retrieve rate limit status")


@router.get("/performance")
async def get_performance_metrics(
    user: OptionalUserDep,
    hours: int = Query(24, ge=1, le=168, description="Hours of history to include"),
) -> dict[str, Any]:
    """Get comprehensive performance metrics."""
    
    try:
        # Get all monitoring data
        tracker = get_token_tracker()
        rate_limiter = get_rate_limiter()
        queue = await get_chat_queue()
        
        # Gather metrics
        token_usage = await tracker.get_recent_usage(hours)
        rate_stats = await rate_limiter.get_usage_stats()
        queue_stats = await queue.get_queue_stats()
        
        # Calculate performance indicators
        performance_score = 100.0
        issues = []
        
        # Rate limiting health
        if rate_stats.get("stabilization_active", False):
            performance_score -= 30
            issues.append("Rate limiting active")
        
        if rate_stats.get("request_utilization_minute", 0) > 80:
            performance_score -= 20
            issues.append("High request rate utilization")
        
        if rate_stats.get("token_utilization_minute", 0) > 80:
            performance_score -= 20
            issues.append("High token rate utilization")
        
        # Queue health
        if queue_stats.get("queue_size", 0) > 10:
            performance_score -= 15
            issues.append("High queue backlog")
        
        if queue_stats.get("avg_wait_time_ms", 0) > 5000:
            performance_score -= 10
            issues.append("High queue wait times")
        
        # Cost efficiency
        avg_cost_per_request = 0.0
        if token_usage.get("request_count", 0) > 0:
            avg_cost_per_request = token_usage.get("total_cost_usd", 0.0) / token_usage["request_count"]
        
        return {
            "performance_score": max(0, performance_score),
            "issues": issues,
            "metrics": {
                "token_usage": token_usage,
                "rate_limiting": rate_stats,
                "queue": queue_stats,
            },
            "cost_analysis": {
                "total_cost_usd": token_usage.get("total_cost_usd", 0.0),
                "average_cost_per_request": avg_cost_per_request,
                "cost_trend": "stable",  # Could be enhanced with trend analysis
            },
            "time_period_hours": hours,
        }
        
    except Exception as exc:
        logger.error(
            "Failed to get performance metrics",
            extra={
                "event": "monitoring_performance_error",
                "error": str(exc),
                "user": getattr(user, "username", None),
            }
        )
        raise HTTPException(status_code=500, detail="Failed to retrieve performance metrics")


@router.post("/reset-rate-limits")
async def reset_rate_limits(user: OptionalUserDep) -> dict[str, Any]:
    """Reset rate limiting state (admin function)."""
    
    # Check if user has admin privileges
    if not user or getattr(user, "role", "") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        rate_limiter = get_rate_limiter()
        
        # Reset the rate limiter state
        async with rate_limiter._lock:
            rate_limiter.state = type(rate_limiter.state)()
        
        logger.info(
            "Rate limiting state reset by admin",
            extra={
                "event": "rate_limit_reset",
                "admin_user": user.username,
            }
        )
        
        return {
            "status": "reset",
            "message": "Rate limiting state has been reset",
            "reset_by": user.username,
        }
        
    except Exception as exc:
        logger.error(
            "Failed to reset rate limits",
            extra={
                "event": "monitoring_reset_error",
                "error": str(exc),
                "user": user.username if user else None,
            }
        )
        raise HTTPException(status_code=500, detail="Failed to reset rate limiting state")


@router.get("/cost-breakdown")
async def get_cost_breakdown(
    user: OptionalUserDep,
    hours: int = Query(24, ge=1, le=168, description="Hours of history to include"),
) -> dict[str, Any]:
    """Get detailed cost breakdown by model, session, and time period."""
    
    try:
        tracker = get_token_tracker()
        
        # Get recent usage
        recent_usage = await tracker.get_recent_usage(hours)
        
        # For now, return basic cost info
        # This could be enhanced to break down by model, session, etc.
        return {
            "total_cost_usd": recent_usage.get("total_cost_usd", 0.0),
            "total_tokens": recent_usage.get("total_tokens", 0),
            "total_requests": recent_usage.get("request_count", 0),
            "time_period_hours": hours,
            "cost_per_token": (
                recent_usage.get("total_cost_usd", 0.0) / recent_usage.get("total_tokens", 1)
                if recent_usage.get("total_tokens", 0) > 0 else 0.0
            ),
            "cost_per_request": (
                recent_usage.get("total_cost_usd", 0.0) / recent_usage.get("request_count", 1)
                if recent_usage.get("request_count", 0) > 0 else 0.0
            ),
        }
        
    except Exception as exc:
        logger.error(
            "Failed to get cost breakdown",
            extra={
                "event": "monitoring_cost_breakdown_error",
                "error": str(exc),
                "user": getattr(user, "username", None),
            }
        )
        raise HTTPException(status_code=500, detail="Failed to retrieve cost breakdown")


__all__ = ["router"]