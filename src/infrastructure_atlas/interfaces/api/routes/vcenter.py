"""API endpoints for vCenter configuration and inventory."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request

from infrastructure_atlas.application.dto.vcenter import (
    vcenter_config_to_dto,
    vcenter_configs_to_dto,
    vcenter_vms_to_dto,
)
from infrastructure_atlas.application.services import VCenterService
from infrastructure_atlas.infrastructure.external import VCenterAPIError, VCenterAuthError, VCenterClientError
from infrastructure_atlas.infrastructure.security.secret_store import SecretStoreUnavailable
from infrastructure_atlas.interfaces.api.dependencies import AdminUserDep, CurrentUserDep, get_vcenter_service
from infrastructure_atlas.interfaces.api.schemas import VCenterConfigCreate, VCenterConfigUpdate

router = APIRouter(prefix="/vcenter", tags=["vcenter"])

VCenterServiceDep = Annotated[VCenterService, Depends(get_vcenter_service)]
CreateBody = Annotated[VCenterConfigCreate, Body(...)]
UpdateBody = Annotated[VCenterConfigUpdate, Body(...)]


def _meta_to_payload(meta: dict[str, object]) -> dict[str, object]:
    generated_at = meta.get("generated_at")
    if isinstance(generated_at, datetime):
        generated_at_str = generated_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    else:
        generated_at_str = None
    return {
        "generated_at": generated_at_str,
        "vm_count": meta.get("vm_count"),
        "source": meta.get("source"),
    }


@router.get("/configs")
def list_configs(admin: AdminUserDep, service: VCenterServiceDep):
    configs = service.list_configs_with_status()
    return [dto.dict_clean() for dto in vcenter_configs_to_dto(configs)]


@router.post("/configs")
def create_config(admin: AdminUserDep, payload: CreateBody, service: VCenterServiceDep):
    try:
        entity = service.create_config(
            name=payload.name,
            base_url=payload.base_url,
            username=payload.username,
            password=payload.password,
            verify_ssl=payload.verify_ssl,
        )
    except SecretStoreUnavailable as exc:  # pragma: no cover - depends on deployment config
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return vcenter_config_to_dto(entity).dict_clean()


@router.put("/configs/{config_id}")
def update_config(admin: AdminUserDep, config_id: str, payload: UpdateBody, service: VCenterServiceDep):
    try:
        entity = service.update_config(
            config_id,
            name=payload.name,
            base_url=payload.base_url,
            username=payload.username,
            password=payload.password,
            verify_ssl=payload.verify_ssl,
        )
    except SecretStoreUnavailable as exc:  # pragma: no cover - depends on deployment config
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        message = str(exc)
        if message.lower().endswith("not found"):
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc
    return vcenter_config_to_dto(entity).dict_clean()


@router.delete("/configs/{config_id}")
def delete_config(admin: AdminUserDep, config_id: str, service: VCenterServiceDep):
    try:
        removed = service.delete_config(config_id)
    except SecretStoreUnavailable as exc:  # pragma: no cover - depends on deployment config
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail="vCenter configuration not found")
    return {"status": "deleted"}


@router.get("/instances")
def list_instances(user: CurrentUserDep, service: VCenterServiceDep):
    entries = service.list_configs_with_status()
    response: list[dict[str, object]] = []
    for config, meta in entries:
        meta_payload = _meta_to_payload(meta or {}) if meta else {"generated_at": None, "vm_count": None, "source": None}
        response.append(
            {
                "id": config.id,
                "name": config.name,
                "base_url": config.base_url,
                "verify_ssl": config.verify_ssl,
                "has_credentials": bool(config.password_secret),
                "last_refresh": meta_payload.get("generated_at"),
                "vm_count": meta_payload.get("vm_count"),
            }
        )
    return response


@router.get("/{config_id}/vms")
def list_vms(
    config_id: str,
    request: Request,
    user: CurrentUserDep,
    service: VCenterServiceDep,
    refresh: bool = Query(False, description="Force refresh from vCenter"),
):
    permissions = getattr(request.state, "permissions", frozenset())
    if "vcenter.view" not in permissions and user.role != "admin":
        raise HTTPException(status_code=403, detail="vCenter access requires additional permissions")

    try:
        config, vms, meta = service.get_inventory(config_id, refresh=refresh)
    except SecretStoreUnavailable as exc:  # pragma: no cover - depends on deployment config
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        message = str(exc)
        if message.lower().endswith("not found"):
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc
    except VCenterAuthError as exc:
        raise HTTPException(status_code=401, detail=f"Failed to authenticate with vCenter: {exc}") from exc
    except (VCenterAPIError, VCenterClientError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    config_dto = vcenter_config_to_dto(config, metadata=meta)
    vm_dtos = vcenter_vms_to_dto(vms)
    return {
        "config": config_dto.dict_clean(),
        "meta": _meta_to_payload(meta or {}),
        "vms": [dto.dict_clean() for dto in vm_dtos],
    }


@router.post("/{config_id}/refresh")
def refresh_vms(config_id: str, request: Request, user: CurrentUserDep, service: VCenterServiceDep):
    permissions = getattr(request.state, "permissions", frozenset())
    if "vcenter.view" not in permissions and user.role != "admin":
        raise HTTPException(status_code=403, detail="vCenter access requires additional permissions")

    try:
        config, vms, meta = service.refresh_inventory(config_id)
    except SecretStoreUnavailable as exc:  # pragma: no cover - depends on deployment config
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        message = str(exc)
        if message.lower().endswith("not found"):
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc
    except VCenterAuthError as exc:
        raise HTTPException(status_code=401, detail=f"Failed to authenticate with vCenter: {exc}") from exc
    except (VCenterAPIError, VCenterClientError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    config_dto = vcenter_config_to_dto(config, metadata=meta)
    vm_dtos = vcenter_vms_to_dto(vms)
    return {
        "config": config_dto.dict_clean(),
        "meta": _meta_to_payload(meta or {}),
        "vms": [dto.dict_clean() for dto in vm_dtos],
    }


__all__ = ["router"]
