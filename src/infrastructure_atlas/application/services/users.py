"""User-facing service implementations backed by repositories."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from infrastructure_atlas.domain.repositories import (
    GlobalAPIKeyRepository,
    RolePermissionRepository,
    UserAPIKeyRepository,
    UserRepository,
)


class DefaultUserService:
    """Default user service relying on repository abstractions."""

    def __init__(
        self,
        user_repo: UserRepository,
        user_key_repo: UserAPIKeyRepository,
        global_key_repo: GlobalAPIKeyRepository,
        role_permission_repo: RolePermissionRepository,
    ) -> None:
        self._user_repo = user_repo
        self._user_key_repo = user_key_repo
        self._global_key_repo = global_key_repo
        self._role_repo = role_permission_repo

    def _enrich_user(self, entity):
        if entity is None:
            return None
        role = entity.role
        permissions = self._role_repo.get(role)
        entity.permissions = permissions.permissions if permissions else frozenset()
        return entity

    def get_current_user(self, user_id: str):
        return self._enrich_user(self._user_repo.get_by_id(user_id))

    def get_user_by_username(self, username: str):
        return self._enrich_user(self._user_repo.get_by_username(username))

    def list_users(self):
        entities = self._user_repo.list_all()
        cache: dict[str, frozenset[str]] = {}
        for entity in entities:
            role = entity.role
            perms = cache.get(role)
            if perms is None:
                record = self._role_repo.get(role)
                perms = record.permissions if record else frozenset()
                cache[role] = perms
            entity.permissions = perms
        return entities

    def list_api_keys(self, user_id: str):
        return self._user_key_repo.list_for_user(user_id)

    def get_global_api_key(self, provider: str):
        return self._global_key_repo.get(provider)


def create_user_service(
    session: Session | None = None,
    user_repo_factory=None,
    user_key_repo_factory=None,
    global_key_repo_factory=None,
    role_permission_repo_factory=None,
) -> DefaultUserService:
    """Helper to create a user service.

    Uses the configured storage backend (MongoDB or SQLite) unless explicit
    repository factories are provided. When using MongoDB, the session parameter
    is ignored.

    Args:
        session: SQLAlchemy session (only used for SQLite backend).
        user_repo_factory: Optional factory for user repository.
        user_key_repo_factory: Optional factory for user API key repository.
        global_key_repo_factory: Optional factory for global API key repository.
        role_permission_repo_factory: Optional factory for role permission repository.

    Returns:
        Configured user service instance.
    """
    from infrastructure_atlas.infrastructure.repository_factory import (
        get_global_api_key_repository,
        get_role_permission_repository,
        get_storage_backend,
        get_user_api_key_repository,
        get_user_repository,
    )

    backend = get_storage_backend()

    # If custom factories provided, use them (for testing)
    if any([user_repo_factory, user_key_repo_factory, global_key_repo_factory, role_permission_repo_factory]):
        if user_repo_factory is None:
            from infrastructure_atlas.infrastructure.db.repositories import SqlAlchemyUserRepository

            user_repo_factory = SqlAlchemyUserRepository
        if user_key_repo_factory is None:
            from infrastructure_atlas.infrastructure.db.repositories import SqlAlchemyUserAPIKeyRepository

            user_key_repo_factory = SqlAlchemyUserAPIKeyRepository
        if global_key_repo_factory is None:
            from infrastructure_atlas.infrastructure.db.repositories import SqlAlchemyGlobalAPIKeyRepository

            global_key_repo_factory = SqlAlchemyGlobalAPIKeyRepository
        if role_permission_repo_factory is None:
            from infrastructure_atlas.infrastructure.db.repositories import SqlAlchemyRolePermissionRepository

            role_permission_repo_factory = SqlAlchemyRolePermissionRepository

        return DefaultUserService(
            user_repo=user_repo_factory(session),
            user_key_repo=user_key_repo_factory(session),
            global_key_repo=global_key_repo_factory(session),
            role_permission_repo=role_permission_repo_factory(session),
        )

    # Use backend-aware repository factory
    if backend == "mongodb":
        return DefaultUserService(
            user_repo=get_user_repository(),
            user_key_repo=get_user_api_key_repository(),
            global_key_repo=get_global_api_key_repository(),
            role_permission_repo=get_role_permission_repository(),
        )

    # SQLite backend - requires session
    if session is None:
        from infrastructure_atlas.db import get_sessionmaker

        Sessionmaker = get_sessionmaker()
        session = Sessionmaker()

    from infrastructure_atlas.infrastructure.db.repositories import (
        SqlAlchemyGlobalAPIKeyRepository,
        SqlAlchemyRolePermissionRepository,
        SqlAlchemyUserAPIKeyRepository,
        SqlAlchemyUserRepository,
    )

    return DefaultUserService(
        user_repo=SqlAlchemyUserRepository(session),
        user_key_repo=SqlAlchemyUserAPIKeyRepository(session),
        global_key_repo=SqlAlchemyGlobalAPIKeyRepository(session),
        role_permission_repo=SqlAlchemyRolePermissionRepository(session),
    )


__all__ = ["DefaultUserService", "create_user_service"]
