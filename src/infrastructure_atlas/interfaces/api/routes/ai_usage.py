"""AI Usage and Activity tracking API routes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel

from infrastructure_atlas.ai.pricing import PRICING, get_model_pricing
from infrastructure_atlas.ai.usage_service import AIUsageService, create_usage_service
from infrastructure_atlas.infrastructure.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/ai/usage", tags=["ai-usage"])


# Lazy imports to avoid circular dependencies
def get_db_session():
    from infrastructure_atlas.api.app import SessionLocal

    return SessionLocal()


def require_admin_permission(request: Request) -> None:
    """Require admin permission."""
    from infrastructure_atlas.api.app import require_permission

    require_permission(request, "admin.access")


# Pydantic models
class ModelConfigCreate(BaseModel):
    """Request to create a model configuration."""

    provider: str
    model_id: str
    display_name: str | None = None
    price_input_per_million: float = 0.0
    price_output_per_million: float = 0.0
    context_window: int | None = None
    supports_tools: bool = True
    supports_streaming: bool = True
    supports_vision: bool = False
    is_active: bool = True
    is_preferred: bool = False


class ModelConfigUpdate(BaseModel):
    """Request to update a model configuration."""

    display_name: str | None = None
    price_input_per_million: float | None = None
    price_output_per_million: float | None = None
    context_window: int | None = None
    supports_tools: bool | None = None
    supports_streaming: bool | None = None
    supports_vision: bool | None = None
    is_active: bool | None = None
    is_preferred: bool | None = None


# Dashboard & Stats Endpoints
@router.get("/dashboard")
async def get_usage_dashboard(request: Request) -> dict[str, Any]:
    """Get comprehensive usage dashboard statistics."""
    require_admin_permission(request)

    db = get_db_session()
    try:
        service = create_usage_service(db)
        return service.get_dashboard_stats()
    finally:
        db.close()


@router.get("/stats")
async def get_usage_stats(
    request: Request,
    provider: str | None = None,
    model: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Get aggregated usage statistics with optional filters."""
    require_admin_permission(request)

    # Parse dates
    start_dt = None
    end_dt = None
    if start_date:
        try:
            start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid start_date format")
    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid end_date format")

    db = get_db_session()
    try:
        service = create_usage_service(db)
        stats = service.get_usage_stats(
            provider=provider,
            model=model,
            start_date=start_dt,
            end_date=end_dt,
        )
        return stats.to_dict()
    finally:
        db.close()


@router.get("/by-model")
async def get_usage_by_model(
    request: Request,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict[str, Any]]:
    """Get usage statistics grouped by model."""
    require_admin_permission(request)

    # Parse dates
    start_dt = None
    end_dt = None
    if start_date:
        try:
            start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid start_date format")
    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid end_date format")

    db = get_db_session()
    try:
        service = create_usage_service(db)
        stats = service.get_usage_by_model(
            start_date=start_dt,
            end_date=end_dt,
            limit=limit,
        )
        return [s.to_dict() for s in stats]
    finally:
        db.close()


@router.get("/trend")
async def get_usage_trend(
    request: Request,
    granularity: str = Query(default="day", regex="^(hour|day|month)$"),
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict[str, Any]]:
    """Get usage trend over time."""
    require_admin_permission(request)

    # Default to last 30 days
    end_dt = datetime.now(UTC)
    start_dt = end_dt - timedelta(days=30)

    if start_date:
        try:
            start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid start_date format")
    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid end_date format")

    db = get_db_session()
    try:
        service = create_usage_service(db)
        return service.get_usage_over_time(
            start_date=start_dt,
            end_date=end_dt,
            granularity=granularity,
        )
    finally:
        db.close()


# Activity Log Endpoints
@router.get("/activity")
async def get_activity_logs(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    provider: str | None = None,
    model: str | None = None,
    session_id: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Get activity logs with optional filtering and pagination."""
    require_admin_permission(request)

    # Parse dates
    start_dt = None
    end_dt = None
    if start_date:
        try:
            start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid start_date format")
    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid end_date format")

    db = get_db_session()
    try:
        service = create_usage_service(db)
        logs, total = service.get_activity_logs(
            limit=limit,
            offset=offset,
            provider=provider,
            model=model,
            session_id=session_id,
            start_date=start_dt,
            end_date=end_dt,
        )
        return {
            "items": logs,
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    finally:
        db.close()


@router.get("/activity/export")
async def export_activity_csv(
    request: Request,
    provider: str | None = None,
    model: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> Response:
    """Export activity logs to CSV."""
    require_admin_permission(request)

    # Parse dates
    start_dt = None
    end_dt = None
    if start_date:
        try:
            start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid start_date format")
    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid end_date format")

    db = get_db_session()
    try:
        service = create_usage_service(db)
        csv_content = service.export_activity_csv(
            provider=provider,
            model=model,
            start_date=start_dt,
            end_date=end_dt,
        )

        filename = f"ai_activity_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.csv"

        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    finally:
        db.close()


# Pricing Endpoints
@router.get("/pricing")
async def get_all_pricing(request: Request) -> dict[str, Any]:
    """Get all built-in model pricing."""
    require_admin_permission(request)

    pricing_list = []
    for model, (input_price, output_price) in PRICING.items():
        pricing_list.append({
            "model": model,
            "price_input_per_million": input_price,
            "price_output_per_million": output_price,
        })

    return {
        "pricing": pricing_list,
        "count": len(pricing_list),
    }


@router.get("/pricing/{model:path}")
async def get_model_pricing_info(
    request: Request,
    model: str,
) -> dict[str, Any]:
    """Get pricing for a specific model."""
    require_admin_permission(request)

    return get_model_pricing(model)


# Model Configuration Endpoints
@router.get("/models")
async def list_model_configs(
    request: Request,
    provider: str | None = None,
    active_only: bool = True,
) -> list[dict[str, Any]]:
    """List all custom model configurations."""
    require_admin_permission(request)

    db = get_db_session()
    try:
        service = create_usage_service(db)
        return service.list_model_configs(provider=provider, active_only=active_only)
    finally:
        db.close()


@router.post("/models")
async def create_model_config(
    request: Request,
    config: ModelConfigCreate,
) -> dict[str, Any]:
    """Create a new custom model configuration."""
    require_admin_permission(request)

    db = get_db_session()
    try:
        service = create_usage_service(db)

        # Auto-fill pricing if not provided
        if config.price_input_per_million == 0.0 and config.price_output_per_million == 0.0:
            pricing = get_model_pricing(config.model_id)
            config.price_input_per_million = pricing.get("price_input_per_million", 0.0)
            config.price_output_per_million = pricing.get("price_output_per_million", 0.0)

        return service.create_model_config(
            provider=config.provider,
            model_id=config.model_id,
            display_name=config.display_name,
            price_input_per_million=config.price_input_per_million,
            price_output_per_million=config.price_output_per_million,
            context_window=config.context_window,
            supports_tools=config.supports_tools,
            supports_streaming=config.supports_streaming,
            supports_vision=config.supports_vision,
            is_active=config.is_active,
            is_preferred=config.is_preferred,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        db.close()


@router.get("/models/{config_id}")
async def get_model_config(
    request: Request,
    config_id: str,
) -> dict[str, Any]:
    """Get a specific model configuration."""
    require_admin_permission(request)

    db = get_db_session()
    try:
        service = create_usage_service(db)
        configs = service.list_model_configs(active_only=False)
        for config in configs:
            if config["id"] == config_id:
                return config
        raise HTTPException(status_code=404, detail="Model config not found")
    finally:
        db.close()


@router.patch("/models/{config_id}")
async def update_model_config(
    request: Request,
    config_id: str,
    config: ModelConfigUpdate,
) -> dict[str, Any]:
    """Update a model configuration."""
    require_admin_permission(request)

    db = get_db_session()
    try:
        service = create_usage_service(db)

        # Only include non-None values
        update_data = {k: v for k, v in config.model_dump().items() if v is not None}

        result = service.update_model_config(config_id, **update_data)
        if not result:
            raise HTTPException(status_code=404, detail="Model config not found")
        return result
    finally:
        db.close()


@router.delete("/models/{config_id}")
async def delete_model_config(
    request: Request,
    config_id: str,
) -> dict[str, str]:
    """Delete a model configuration."""
    require_admin_permission(request)

    db = get_db_session()
    try:
        service = create_usage_service(db)
        if not service.delete_model_config(config_id):
            raise HTTPException(status_code=404, detail="Model config not found")
        return {"status": "deleted", "id": config_id}
    finally:
        db.close()


@router.post("/models/lookup")
async def lookup_model_pricing(
    request: Request,
    model_id: str = Query(..., description="Model ID to look up pricing for"),
) -> dict[str, Any]:
    """Look up default pricing for a model (for auto-fill when adding)."""
    require_admin_permission(request)

    return get_model_pricing(model_id)
