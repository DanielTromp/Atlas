"""DTOs for user-facing operations."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from infrastructure_atlas.domain.entities import GlobalAPIKeyEntity, UserAPIKeyEntity, UserEntity

from .base import DomainModel


class UserDTO(DomainModel):
    id: str
    username: str
    display_name: str | None = None
    email: str | None = None
    role: str
    permissions: tuple[str, ...] = ()
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserAPIKeyDTO(DomainModel):
    id: str
    provider: str
    label: str | None = None
    created_at: datetime
    updated_at: datetime


class GlobalAPIKeyDTO(DomainModel):
    id: str
    provider: str
    label: str | None = None
    created_at: datetime
    updated_at: datetime


def user_to_dto(entity: UserEntity) -> UserDTO:
    return UserDTO(
        id=entity.id,
        username=entity.username,
        display_name=entity.display_name,
        email=entity.email,
        role=entity.role,
        permissions=tuple(sorted(entity.permissions)),
        is_active=entity.is_active,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def users_to_dto(entities: Iterable[UserEntity]) -> list[UserDTO]:
    return [user_to_dto(entity) for entity in entities]


def user_key_to_dto(entity: UserAPIKeyEntity) -> UserAPIKeyDTO:
    return UserAPIKeyDTO.model_validate(entity)


def user_keys_to_dto(entities: Iterable[UserAPIKeyEntity]) -> list[UserAPIKeyDTO]:
    return [user_key_to_dto(entity) for entity in entities]


def global_key_to_dto(entity: GlobalAPIKeyEntity) -> GlobalAPIKeyDTO:
    return GlobalAPIKeyDTO.model_validate(entity)
