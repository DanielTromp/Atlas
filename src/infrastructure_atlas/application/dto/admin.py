"""DTO helpers for admin responses."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from infrastructure_atlas.application.dto.base import DomainModel
from infrastructure_atlas.domain.entities import (
    GlobalAPIKeyEntity,
    RolePermissionEntity,
    UserEntity,
)


class AdminUserDTO(DomainModel):
    id: str
    username: str
    display_name: str | None
    email: str | None
    role: str
    permissions: tuple[str, ...]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AdminGlobalKeyDTO(DomainModel):
    id: str
    provider: str
    label: str | None
    created_at: datetime
    updated_at: datetime


class AdminRoleDTO(DomainModel):
    role: str
    label: str
    description: str | None
    permissions: tuple[str, ...]
    created_at: datetime
    updated_at: datetime


def admin_user_to_dto(entity: UserEntity) -> AdminUserDTO:
    return AdminUserDTO(
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


def admin_users_to_dto(entities: Iterable[UserEntity]) -> list[AdminUserDTO]:
    return [admin_user_to_dto(entity) for entity in entities]


def admin_global_key_to_dto(entity: GlobalAPIKeyEntity) -> AdminGlobalKeyDTO:
    return AdminGlobalKeyDTO.model_validate(entity)


def admin_global_keys_to_dto(entities: Iterable[GlobalAPIKeyEntity]) -> list[AdminGlobalKeyDTO]:
    return [admin_global_key_to_dto(entity) for entity in entities]


def admin_role_to_dto(entity: RolePermissionEntity) -> AdminRoleDTO:
    return AdminRoleDTO(
        role=entity.role,
        label=entity.label,
        description=entity.description,
        permissions=tuple(sorted(entity.permissions)),
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def admin_roles_to_dto(entities: Iterable[RolePermissionEntity]) -> list[AdminRoleDTO]:
    return [admin_role_to_dto(entity) for entity in entities]


__all__ = [
    "AdminGlobalKeyDTO",
    "AdminRoleDTO",
    "AdminUserDTO",
    "admin_global_key_to_dto",
    "admin_global_keys_to_dto",
    "admin_role_to_dto",
    "admin_roles_to_dto",
    "admin_user_to_dto",
    "admin_users_to_dto",
]
