"""User-facing service implementations backed by repositories."""
from __future__ import annotations

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
    session: Session,
    user_repo_factory = None,
    user_key_repo_factory = None,
    global_key_repo_factory = None,
    role_permission_repo_factory = None,
) -> DefaultUserService:
    """Helper to create a user service from a SQLAlchemy session.

    The optional factory arguments allow tests to supply instrumented repository
    implementations while production usage defaults to the SQLAlchemy-backed
    repositories defined in the infrastructure layer.
    """
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


__all__ = ["DefaultUserService", "create_user_service"]
