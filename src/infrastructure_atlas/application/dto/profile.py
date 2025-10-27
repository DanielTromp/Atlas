"""DTOs for profile and admin user responses."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from infrastructure_atlas.application.dto import DomainModel
from infrastructure_atlas.domain.entities import GlobalAPIKeyEntity, UserAPIKeyEntity, UserEntity


class ProfileDTO(DomainModel):
    id: str
    username: str
    display_name: str | None
    email: str | None
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class APIKeyDTO(DomainModel):
    id: str
    provider: str
    label: str | None
    created_at: datetime
    updated_at: datetime


class GlobalKeyDTO(DomainModel):
    id: str
    provider: str
    label: str | None
    created_at: datetime
    updated_at: datetime


def profile_to_dto(entity: UserEntity) -> ProfileDTO:
    return ProfileDTO.model_validate(entity)


def profiles_to_dto(entities: Iterable[UserEntity]) -> list[ProfileDTO]:
    return [profile_to_dto(entity) for entity in entities]


def api_key_to_dto(entity: UserAPIKeyEntity) -> APIKeyDTO:
    return APIKeyDTO.model_validate(entity)


def api_keys_to_dto(entities: Iterable[UserAPIKeyEntity]) -> list[APIKeyDTO]:
    return [api_key_to_dto(entity) for entity in entities]


def global_key_to_dto(entity: GlobalAPIKeyEntity) -> GlobalKeyDTO:
    return GlobalKeyDTO.model_validate(entity)


def global_keys_to_dto(entities: Iterable[GlobalAPIKeyEntity]) -> list[GlobalKeyDTO]:
    return [global_key_to_dto(entity) for entity in entities]
