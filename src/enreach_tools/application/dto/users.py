"""DTOs for user-facing operations."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from enreach_tools.domain.entities import GlobalAPIKeyEntity, UserAPIKeyEntity, UserEntity

from .base import DomainModel


class UserDTO(DomainModel):
    id: str
    username: str
    display_name: str | None = None
    email: str | None = None
    role: str
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
    return UserDTO.model_validate(entity)


def users_to_dto(entities: Iterable[UserEntity]) -> list[UserDTO]:
    return [user_to_dto(entity) for entity in entities]


def user_key_to_dto(entity: UserAPIKeyEntity) -> UserAPIKeyDTO:
    return UserAPIKeyDTO.model_validate(entity)


def user_keys_to_dto(entities: Iterable[UserAPIKeyEntity]) -> list[UserAPIKeyDTO]:
    return [user_key_to_dto(entity) for entity in entities]


def global_key_to_dto(entity: GlobalAPIKeyEntity) -> GlobalAPIKeyDTO:
    return GlobalAPIKeyDTO.model_validate(entity)
