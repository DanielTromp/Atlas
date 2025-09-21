"""Authentication and user profile endpoints wired via application services."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from enreach_tools.application.dto import user_to_dto
from enreach_tools.application.services import DefaultUserService
from enreach_tools.infrastructure.db import mappers
from enreach_tools.interfaces.api.dependencies import CurrentUserDep, get_user_service

router = APIRouter()


@router.get("/auth/me")
def auth_me(
    current_user: CurrentUserDep,
    user_service: DefaultUserService = Depends(get_user_service),
):
    """Return the authenticated user's profile."""
    entity = user_service.get_current_user(current_user.id)
    if entity is None:
        entity = mappers.user_to_entity(current_user)
    dto = user_to_dto(entity)
    return dto.dict_clean()


__all__ = ["router"]
