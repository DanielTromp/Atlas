"""Authentication and user profile endpoints wired via application services."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from infrastructure_atlas.application.dto import user_to_dto
from infrastructure_atlas.application.services import DefaultUserService
from infrastructure_atlas.infrastructure.db import mappers
from infrastructure_atlas.interfaces.api.dependencies import CurrentUserDep, get_user_service

router = APIRouter()

UserServiceDep = Annotated[DefaultUserService, Depends(get_user_service)]


@router.get("/auth/me")
def auth_me(
    current_user: CurrentUserDep,
    user_service: UserServiceDep,
):
    """Return the authenticated user's profile."""
    entity = user_service.get_current_user(current_user.id)
    if entity is None:
        entity = mappers.user_to_entity(current_user)
    dto = user_to_dto(entity)
    return dto.dict_clean()


__all__ = ["router"]
