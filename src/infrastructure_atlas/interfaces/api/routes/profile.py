"""Profile management endpoints."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from infrastructure_atlas.application.dto.profile import (
    api_key_to_dto,
    api_keys_to_dto,
    profile_to_dto,
)
from infrastructure_atlas.application.security import hash_password, verify_password
from infrastructure_atlas.application.services.profile import ProfileService
from infrastructure_atlas.interfaces.api.dependencies import CurrentUserDep, get_profile_service
from infrastructure_atlas.interfaces.api.schemas import APIKeyPayload, PasswordChange, ProfileUpdate

router = APIRouter(prefix="/profile")

ProfileServiceDep = Annotated[ProfileService, Depends(get_profile_service)]


@router.patch("")
def update_profile(
    payload: ProfileUpdate,
    current_user: CurrentUserDep,
    service: ProfileServiceDep,
):
    if payload.email and "@" not in payload.email:
        raise HTTPException(status_code=400, detail="Invalid email address")

    entity = service.update_profile(
        current_user,
        payload.display_name or None,
        payload.email or None,
    )
    return profile_to_dto(entity).dict_clean()


@router.post("/password")
def change_password(
    payload: PasswordChange,
    current_user: CurrentUserDep,
    service: ProfileServiceDep,
):
    new_password = (payload.new_password or "").strip()
    current_password = (payload.current_password or "").strip() if payload.current_password else ""

    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    if current_user.password_hash:
        if not current_password or not verify_password(current_password, current_user.password_hash):
            raise HTTPException(status_code=400, detail="Current password is incorrect")

    service.change_password(current_user, hash_password(new_password))
    return {"status": "ok"}


@router.get("/api-keys")
def list_api_keys(
    current_user: CurrentUserDep,
    service: ProfileServiceDep,
):
    entities = service.list_api_keys(current_user.id)
    return [dto.dict_clean() for dto in api_keys_to_dto(entities)]


@router.put("/api-keys/{provider}")
def upsert_api_key(
    provider: str,
    payload: APIKeyPayload,
    current_user: CurrentUserDep,
    service: ProfileServiceDep,
):
    provider_norm = (provider or "").strip().lower()
    if not provider_norm:
        raise HTTPException(status_code=400, detail="Provider is required")

    secret = payload.secret.strip()
    if not secret:
        raise HTTPException(status_code=400, detail="Secret is required")

    entity = service.save_api_key(current_user, provider_norm, secret, payload.label or None)
    return api_key_to_dto(entity).dict_clean()


@router.delete("/api-keys/{provider}")
def delete_api_key(
    provider: str,
    current_user: CurrentUserDep,
    service: ProfileServiceDep,
):
    provider_norm = (provider or "").strip().lower()
    try:
        service.delete_api_key(current_user, provider_norm)
    except LookupError:
        raise HTTPException(status_code=404, detail="API key not found") from None
    return {"status": "deleted"}


__all__ = ["router"]
