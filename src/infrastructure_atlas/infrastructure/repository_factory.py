"""Repository factory for switching between storage backends.

Provides factory functions that return the appropriate repository implementation
based on environment configuration. Supports gradual rollout and easy rollback.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from infrastructure_atlas.domain.repositories import (
        ChatSessionRepository,
        ForemanConfigRepository,
        GlobalAPIKeyRepository,
        RolePermissionRepository,
        UserAPIKeyRepository,
        UserRepository,
        VCenterConfigRepository,
    )
    from infrastructure_atlas.infrastructure.mongodb.cache_repositories import (
        MongoDBCommvaultCacheRepository,
        MongoDBVCenterCacheRepository,
    )

from infrastructure_atlas.infrastructure.logging import get_logger

logger = get_logger(__name__)

StorageBackend = Literal["mongodb", "sqlite"]
CacheBackend = Literal["mongodb", "json"]


def get_storage_backend() -> StorageBackend:
    """Get the configured storage backend.

    Reads from ATLAS_STORAGE_BACKEND environment variable.
    Defaults to 'mongodb'.
    """
    backend = os.getenv("ATLAS_STORAGE_BACKEND", "mongodb").lower().strip()
    if backend in ("mongodb", "mongo"):
        return "mongodb"
    if backend in ("sqlite", "sql"):
        return "sqlite"
    logger.warning("Unknown storage backend '%s', defaulting to mongodb", backend)
    return "mongodb"


def get_cache_backend() -> CacheBackend:
    """Get the configured cache backend.

    Reads from ATLAS_CACHE_BACKEND environment variable.
    Defaults to 'mongodb'.
    """
    backend = os.getenv("ATLAS_CACHE_BACKEND", "mongodb").lower().strip()
    if backend in ("mongodb", "mongo"):
        return "mongodb"
    if backend in ("json", "file"):
        return "json"
    logger.warning("Unknown cache backend '%s', defaulting to mongodb", backend)
    return "mongodb"


# =============================================================================
# MongoDB Factory Functions
# =============================================================================


@lru_cache(maxsize=1)
def _get_mongodb_databases():
    """Get MongoDB databases (cached)."""
    from infrastructure_atlas.infrastructure.mongodb import get_mongodb_client

    client = get_mongodb_client()
    return client.atlas, client.atlas_cache


def get_mongodb_user_repository() -> UserRepository:
    """Get the MongoDB user repository."""
    from infrastructure_atlas.infrastructure.mongodb.repositories import MongoDBUserRepository

    app_db, _ = _get_mongodb_databases()
    return MongoDBUserRepository(app_db)


def get_mongodb_user_api_key_repository() -> UserAPIKeyRepository:
    """Get the MongoDB user API key repository."""
    from infrastructure_atlas.infrastructure.mongodb.repositories import MongoDBUserAPIKeyRepository

    app_db, _ = _get_mongodb_databases()
    return MongoDBUserAPIKeyRepository(app_db)


def get_mongodb_global_api_key_repository() -> GlobalAPIKeyRepository:
    """Get the MongoDB global API key repository."""
    from infrastructure_atlas.infrastructure.mongodb.repositories import MongoDBGlobalAPIKeyRepository

    app_db, _ = _get_mongodb_databases()
    return MongoDBGlobalAPIKeyRepository(app_db)


def get_mongodb_chat_session_repository() -> ChatSessionRepository:
    """Get the MongoDB chat session repository."""
    from infrastructure_atlas.infrastructure.mongodb.repositories import MongoDBChatSessionRepository

    app_db, _ = _get_mongodb_databases()
    return MongoDBChatSessionRepository(app_db)


def get_mongodb_role_permission_repository() -> RolePermissionRepository:
    """Get the MongoDB role permission repository."""
    from infrastructure_atlas.infrastructure.mongodb.repositories import MongoDBRolePermissionRepository

    app_db, _ = _get_mongodb_databases()
    return MongoDBRolePermissionRepository(app_db)


def get_mongodb_vcenter_config_repository() -> VCenterConfigRepository:
    """Get the MongoDB vCenter config repository."""
    from infrastructure_atlas.infrastructure.mongodb.repositories import MongoDBVCenterConfigRepository

    app_db, _ = _get_mongodb_databases()
    return MongoDBVCenterConfigRepository(app_db)


def get_mongodb_foreman_config_repository() -> ForemanConfigRepository:
    """Get the MongoDB Foreman config repository."""
    from infrastructure_atlas.infrastructure.mongodb.repositories import MongoDBForemanConfigRepository

    app_db, _ = _get_mongodb_databases()
    return MongoDBForemanConfigRepository(app_db)


# =============================================================================
# Cache Repository Factory Functions
# =============================================================================


def get_vcenter_cache_repository() -> MongoDBVCenterCacheRepository:
    """Get the vCenter cache repository.

    Currently only supports MongoDB. JSON backend would require implementing
    file-based operations with proper locking.
    """
    from infrastructure_atlas.infrastructure.mongodb.cache_repositories import MongoDBVCenterCacheRepository

    _, cache_db = _get_mongodb_databases()
    return MongoDBVCenterCacheRepository(cache_db)


def get_commvault_cache_repository() -> MongoDBCommvaultCacheRepository:
    """Get the Commvault cache repository.

    Currently only supports MongoDB. JSON backend would require implementing
    file-based operations with proper locking.
    """
    from infrastructure_atlas.infrastructure.mongodb.cache_repositories import MongoDBCommvaultCacheRepository

    _, cache_db = _get_mongodb_databases()
    return MongoDBCommvaultCacheRepository(cache_db)


# =============================================================================
# Backend-Aware Factory Functions
# =============================================================================


def get_user_repository(backend: StorageBackend | None = None) -> UserRepository:
    """Get the user repository for the configured or specified backend.

    Args:
        backend: Override the configured backend. If None, uses environment config.

    Returns:
        The appropriate user repository implementation.
    """
    effective_backend = backend or get_storage_backend()

    if effective_backend == "mongodb":
        return get_mongodb_user_repository()

    # SQLite backend
    from infrastructure_atlas.infrastructure.db.repositories import SqlAlchemyUserRepository
    from infrastructure_atlas.infrastructure.persistence.database import get_session

    return SqlAlchemyUserRepository(get_session())


def get_user_api_key_repository(backend: StorageBackend | None = None) -> UserAPIKeyRepository:
    """Get the user API key repository for the configured or specified backend."""
    effective_backend = backend or get_storage_backend()

    if effective_backend == "mongodb":
        return get_mongodb_user_api_key_repository()

    from infrastructure_atlas.infrastructure.db.repositories import SqlAlchemyUserAPIKeyRepository
    from infrastructure_atlas.infrastructure.persistence.database import get_session

    return SqlAlchemyUserAPIKeyRepository(get_session())


def get_global_api_key_repository(backend: StorageBackend | None = None) -> GlobalAPIKeyRepository:
    """Get the global API key repository for the configured or specified backend."""
    effective_backend = backend or get_storage_backend()

    if effective_backend == "mongodb":
        return get_mongodb_global_api_key_repository()

    from infrastructure_atlas.infrastructure.db.repositories import SqlAlchemyGlobalAPIKeyRepository
    from infrastructure_atlas.infrastructure.persistence.database import get_session

    return SqlAlchemyGlobalAPIKeyRepository(get_session())


def get_chat_session_repository(backend: StorageBackend | None = None) -> ChatSessionRepository:
    """Get the chat session repository for the configured or specified backend."""
    effective_backend = backend or get_storage_backend()

    if effective_backend == "mongodb":
        return get_mongodb_chat_session_repository()

    from infrastructure_atlas.infrastructure.db.repositories import SqlAlchemyChatSessionRepository
    from infrastructure_atlas.infrastructure.persistence.database import get_session

    return SqlAlchemyChatSessionRepository(get_session())


def get_role_permission_repository(backend: StorageBackend | None = None) -> RolePermissionRepository:
    """Get the role permission repository for the configured or specified backend."""
    effective_backend = backend or get_storage_backend()

    if effective_backend == "mongodb":
        return get_mongodb_role_permission_repository()

    from infrastructure_atlas.infrastructure.db.repositories import SqlAlchemyRolePermissionRepository
    from infrastructure_atlas.infrastructure.persistence.database import get_session

    return SqlAlchemyRolePermissionRepository(get_session())


def get_vcenter_config_repository(backend: StorageBackend | None = None) -> VCenterConfigRepository:
    """Get the vCenter config repository for the configured or specified backend."""
    effective_backend = backend or get_storage_backend()

    if effective_backend == "mongodb":
        return get_mongodb_vcenter_config_repository()

    from infrastructure_atlas.infrastructure.db.repositories import SqlAlchemyVCenterConfigRepository
    from infrastructure_atlas.infrastructure.persistence.database import get_session

    return SqlAlchemyVCenterConfigRepository(get_session())


def get_foreman_config_repository(backend: StorageBackend | None = None) -> ForemanConfigRepository:
    """Get the Foreman config repository for the configured or specified backend."""
    effective_backend = backend or get_storage_backend()

    if effective_backend == "mongodb":
        return get_mongodb_foreman_config_repository()

    from infrastructure_atlas.infrastructure.db.repositories import SqlAlchemyForemanConfigRepository
    from infrastructure_atlas.infrastructure.persistence.database import get_session

    return SqlAlchemyForemanConfigRepository(get_session())


__all__ = [
    # Backend detection
    "get_storage_backend",
    "get_cache_backend",
    # Backend-aware factories
    "get_user_repository",
    "get_user_api_key_repository",
    "get_global_api_key_repository",
    "get_chat_session_repository",
    "get_role_permission_repository",
    "get_vcenter_config_repository",
    "get_foreman_config_repository",
    # Cache repositories (MongoDB only)
    "get_vcenter_cache_repository",
    "get_commvault_cache_repository",
]
