"""Administrative user management services."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from infrastructure_atlas.application.security import hash_password
from infrastructure_atlas.domain.repositories import (
    GlobalAPIKeyRepository,
    RolePermissionRepository,
    UserRepository,
)


class AdminService:
    """Backend-agnostic admin service for user and permission management."""

    def __init__(
        self,
        user_repo: UserRepository,
        role_repo: RolePermissionRepository,
        global_key_repo: GlobalAPIKeyRepository,
    ) -> None:
        self._user_repo = user_repo
        self._role_repo = role_repo
        self._global_key_repo = global_key_repo

    def _normalize_role(self, role: str) -> str:
        return (role or "").strip().lower()

    def ensure_role_defined(self, role: str) -> str:
        normalized = self._normalize_role(role)
        if not normalized:
            raise ValueError("Role is required")
        record = self._role_repo.get(normalized)
        if record is None:
            raise ValueError(f"Role '{normalized}' is not defined")
        return normalized

    def _role_permissions(self, role: str) -> frozenset[str]:
        record = self._role_repo.get(role)
        return record.permissions if record else frozenset()

    def _attach_user_permissions(self, entity):
        if entity is None:
            return None
        entity.permissions = self._role_permissions(entity.role)
        return entity

    def list_users(self, include_inactive: bool = False):
        users = self._user_repo.list_all()
        if not include_inactive:
            users = [u for u in users if u.is_active]
        cache: dict[str, frozenset[str]] = {}
        for entity in users:
            perms = cache.get(entity.role)
            if perms is None:
                perms = self._role_permissions(entity.role)
                cache[entity.role] = perms
            entity.permissions = perms
        return users

    def create_user(self, username: str, password: str, display_name: str | None, email: str | None, role: str):
        role_norm = self.ensure_role_defined(role)
        entity = self._user_repo.create(
            username=username,
            display_name=display_name,
            email=email,
            role=role_norm,
            password_hash=hash_password(password),
            is_active=True,
        )
        return self._attach_user_permissions(entity)

    def get_user(self, user_id: str):
        return self._user_repo.get_by_id(user_id)

    def get_user_by_username(self, username: str):
        return self._user_repo.get_by_username(username)

    def ensure_username_available(self, username: str) -> None:
        if self._user_repo.get_by_username(username):
            raise ValueError("Username already exists")

    def save_user(self, user):
        if user.role:
            user.role = self.ensure_role_defined(user.role)
        # For MongoDB, we update using the repository
        entity = self._user_repo.update(
            user.id,
            username=user.username,
            display_name=user.display_name,
            email=user.email,
            role=user.role,
            is_active=user.is_active,
        )
        return self._attach_user_permissions(entity)

    def set_password(self, user, password: str):
        entity = self._user_repo.update(
            user.id,
            password_hash=hash_password(password),
        )
        return entity

    def delete_user(self, user):
        self._user_repo.delete(user.id)

    def list_global_api_keys(self):
        return self._global_key_repo.list_all()

    def list_role_permissions(self):
        return self._role_repo.list_all()

    def get_role_permission(self, role: str):
        normalized = self._normalize_role(role)
        return self._role_repo.get(normalized)

    def update_role_permission(self, role: str, label: str | None, description: str | None, permissions: list[str]):
        normalized = self._normalize_role(role)
        existing = self._role_repo.get(normalized)
        if existing is None:
            raise ValueError("Role not found")
        label_value = (label or existing.label or normalized).strip() or normalized
        description_value = (
            description.strip()
            if isinstance(description, str) and description.strip()
            else None
        )
        cleaned_perms = [p.strip() for p in permissions if p and str(p).strip()]
        return self._role_repo.upsert(normalized, label_value, description_value, cleaned_perms)

    def upsert_global_api_key(self, provider: str, secret: str, label: str | None):
        return self._global_key_repo.upsert(provider=provider, secret=secret, label=label)

    def delete_global_api_key(self, provider: str) -> bool:
        return self._global_key_repo.delete(provider)


def create_admin_service(session: Session | None = None) -> AdminService:
    """Create an admin service using the configured storage backend.

    Args:
        session: SQLAlchemy session (only used for SQLite backend).

    Returns:
        Configured admin service instance.
    """
    from infrastructure_atlas.infrastructure.repository_factory import (
        get_global_api_key_repository,
        get_role_permission_repository,
        get_storage_backend,
        get_user_repository,
    )

    backend = get_storage_backend()

    if backend == "mongodb":
        return AdminService(
            user_repo=get_user_repository(),
            role_repo=get_role_permission_repository(),
            global_key_repo=get_global_api_key_repository(),
        )

    # SQLite backend
    if session is None:
        from infrastructure_atlas.db import get_sessionmaker

        Sessionmaker = get_sessionmaker()
        session = Sessionmaker()

    from infrastructure_atlas.infrastructure.db.repositories import (
        SqlAlchemyGlobalAPIKeyRepository,
        SqlAlchemyRolePermissionRepository,
        SqlAlchemyUserRepository,
    )

    return AdminService(
        user_repo=SqlAlchemyUserRepository(session),
        role_repo=SqlAlchemyRolePermissionRepository(session),
        global_key_repo=SqlAlchemyGlobalAPIKeyRepository(session),
    )


__all__ = ["AdminService", "create_admin_service"]
