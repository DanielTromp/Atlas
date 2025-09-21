"""DTO helpers for admin responses."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from enreach_tools.application.dto.base import DomainModel
from enreach_tools.domain.entities import GlobalAPIKeyEntity, UserEntity


class AdminUserDTO(DomainModel):
    id: str
    username: str
    display_name: str | None
    email: str | None
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AdminGlobalKeyDTO(DomainModel):
    id: str
    provider: str
    label: str | None
    created_at: datetime
    updated_at: datetime


def admin_user_to_dto(entity: UserEntity) -> AdminUserDTO:
    return AdminUserDTO.model_validate(entity)


def admin_users_to_dto(entities: Iterable[UserEntity]) -> list[AdminUserDTO]:
    return [admin_user_to_dto(entity) for entity in entities]


def admin_global_key_to_dto(entity: GlobalAPIKeyEntity) -> AdminGlobalKeyDTO:
    return AdminGlobalKeyDTO.model_validate(entity)


def admin_global_keys_to_dto(entities: Iterable[GlobalAPIKeyEntity]) -> list[AdminGlobalKeyDTO]:
    return [admin_global_key_to_dto(entity) for entity in entities]


__all__ = [
    "AdminGlobalKeyDTO",
    "AdminUserDTO",
    "admin_global_key_to_dto",
    "admin_global_keys_to_dto",
    "admin_user_to_dto",
    "admin_users_to_dto",
]
