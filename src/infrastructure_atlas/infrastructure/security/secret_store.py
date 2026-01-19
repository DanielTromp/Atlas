"""Encrypted secret storage backed by the database.

This module centralises the logic for persisting sensitive configuration
values (API tokens, passwords) in the database while keeping them encrypted at
rest. Secrets are decrypted only when they need to be injected back into the
process environment.

Supports both SQLite (SQLAlchemy) and MongoDB backends based on the
ATLAS_STORAGE_BACKEND environment variable.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from typing import TYPE_CHECKING, Protocol

from cryptography.fernet import Fernet, InvalidToken

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

SECRET_KEY_ENV = "ATLAS_SECRET_KEY"  # noqa: S105 - env var name, not a secret value
SECURE_ENV_KEYS: tuple[str, ...] = (
    "ATLAS_API_TOKEN",
    "ATLAS_UI_SECRET",
    "NETBOX_TOKEN",
    "ATLASSIAN_EMAIL",
    "ATLASSIAN_API_TOKEN",
    "COMMVAULT_EMAIL",
    "COMMVAULT_API_TOKEN",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "ANTHROPIC_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "BACKUP_PASSWORD",
    "CONTEXT7_API_KEY",
    "ATLAS_SSL_KEY_PASSWORD",
    # AI provider default models (persisted to survive restarts)
    "OPENAI_DEFAULT_MODEL",
    "OPENROUTER_DEFAULT_MODEL",
    "ANTHROPIC_DEFAULT_MODEL",
    "AZURE_OPENAI_DEFAULT_MODEL",
    "GEMINI_DEFAULT_MODEL",
)


class SecretStoreUnavailable(RuntimeError):
    """Raised when the encrypted secret store is unavailable."""


class SecretStore(Protocol):
    """Protocol for secret store implementations."""

    def get(self, name: str) -> str | None:
        """Get a decrypted secret by name."""
        ...

    def set(self, name: str, value: str) -> bool:
        """Set an encrypted secret. Returns True if changed."""
        ...

    def delete(self, name: str) -> bool:
        """Delete a secret. Returns True if deleted."""
        ...


# =============================================================================
# SQLite/SQLAlchemy Implementation
# =============================================================================


class _SqlAlchemySecretStore:
    """SQLAlchemy-backed secret store implementation."""

    def __init__(self, session: Session, cipher: Fernet):
        self._session = session
        self._cipher = cipher

    def get(self, name: str) -> str | None:
        from infrastructure_atlas.db.models import SecureSetting

        record = self._session.get(SecureSetting, name)
        if record is None:
            return None
        try:
            decrypted = self._cipher.decrypt(record.encrypted_value.encode("utf-8"))
        except InvalidToken:
            logger.warning("Discarding secure setting '%s': failed to decrypt", name)
            return None
        return decrypted.decode("utf-8")

    def set(self, name: str, value: str) -> bool:
        from infrastructure_atlas.db.models import SecureSetting

        cleaned = (value or "").strip()
        if not cleaned:
            return self.delete(name)
        token = self._cipher.encrypt(cleaned.encode("utf-8")).decode("utf-8")
        record = self._session.get(SecureSetting, name)
        if record is None:
            self._session.add(SecureSetting(name=name, encrypted_value=token))
            return True
        if record.encrypted_value == token:
            return False
        record.encrypted_value = token
        return True

    def delete(self, name: str) -> bool:
        from infrastructure_atlas.db.models import SecureSetting

        record = self._session.get(SecureSetting, name)
        if record is None:
            return False
        self._session.delete(record)
        return True


# =============================================================================
# MongoDB Implementation
# =============================================================================


class _MongoDBSecretStore:
    """MongoDB-backed secret store implementation."""

    def __init__(self, cipher: Fernet):
        self._cipher = cipher
        self._collection = None

    def _get_collection(self):
        """Lazy-load the MongoDB collection."""
        if self._collection is None:
            from infrastructure_atlas.infrastructure.mongodb import get_mongodb_client

            client = get_mongodb_client()
            self._collection = client.atlas["secure_settings"]
        return self._collection

    def get(self, name: str) -> str | None:
        collection = self._get_collection()
        doc = collection.find_one({"_id": name})
        if doc is None:
            return None
        encrypted_value = doc.get("encrypted_value")
        if not encrypted_value:
            return None
        try:
            decrypted = self._cipher.decrypt(encrypted_value.encode("utf-8"))
        except InvalidToken:
            logger.warning("Discarding secure setting '%s': failed to decrypt", name)
            return None
        return decrypted.decode("utf-8")

    def set(self, name: str, value: str) -> bool:
        cleaned = (value or "").strip()
        if not cleaned:
            return self.delete(name)
        token = self._cipher.encrypt(cleaned.encode("utf-8")).decode("utf-8")
        collection = self._get_collection()

        # Check if value is the same (to return False if no change)
        existing = collection.find_one({"_id": name})
        if existing and existing.get("encrypted_value") == token:
            return False

        # Upsert the document
        collection.replace_one(
            {"_id": name},
            {"_id": name, "name": name, "encrypted_value": token},
            upsert=True,
        )
        return True

    def delete(self, name: str) -> bool:
        collection = self._get_collection()
        result = collection.delete_one({"_id": name})
        return result.deleted_count > 0


# =============================================================================
# Factory Functions
# =============================================================================


def _build_cipher() -> Fernet | None:
    key = os.getenv(SECRET_KEY_ENV, "").strip()
    if not key:
        logger.debug("Encrypted secret store disabled: %s not configured", SECRET_KEY_ENV)
        return None
    try:
        return Fernet(key)
    except (ValueError, TypeError) as exc:
        logger.error("Invalid %s provided; expected base64-encoded 32 byte key", SECRET_KEY_ENV, exc_info=exc)
        return None


def _get_storage_backend() -> str:
    """Get the configured storage backend."""
    from infrastructure_atlas.infrastructure.repository_factory import get_storage_backend

    return get_storage_backend()


def _has_secure_table() -> bool:
    """Check if SQLite secure_settings table exists."""
    try:
        from sqlalchemy import inspect
        from sqlalchemy.exc import SQLAlchemyError

        from infrastructure_atlas.db.config import get_engine
        from infrastructure_atlas.db.models import SecureSetting

        engine = get_engine()
        inspector = inspect(engine)
        return inspector.has_table(SecureSetting.__tablename__)
    except SQLAlchemyError as exc:
        logger.debug("Unable to inspect database for secure settings table", exc_info=exc)
        return False
    except Exception:
        return False


def _mongodb_available() -> bool:
    """Check if MongoDB is available."""
    try:
        from infrastructure_atlas.infrastructure.mongodb import get_mongodb_client

        client = get_mongodb_client()
        result = client.health_check()
        return result.get("healthy", False)
    except Exception as exc:
        logger.debug("MongoDB not available for secret store: %s", exc)
        return False


def _build_store_mongodb() -> _MongoDBSecretStore | None:
    """Build a MongoDB secret store."""
    cipher = _build_cipher()
    if cipher is None:
        return None
    if not _mongodb_available():
        return None
    return _MongoDBSecretStore(cipher)


def _build_store_sqlite(session: Session) -> _SqlAlchemySecretStore | None:
    """Build a SQLite secret store."""
    cipher = _build_cipher()
    if cipher is None:
        return None
    if not _has_secure_table():
        return None
    return _SqlAlchemySecretStore(session, cipher)


def get_secret_store(session: Session | None = None) -> SecretStore | None:
    """Return a secret store instance when encryption is configured.

    Uses the configured storage backend (MongoDB or SQLite).

    Args:
        session: SQLAlchemy session (only required for SQLite backend).

    Returns:
        A secret store instance or None if not available.
    """
    backend = _get_storage_backend()

    if backend == "mongodb":
        return _build_store_mongodb()

    # SQLite backend
    if session is None:
        from infrastructure_atlas.db import get_sessionmaker

        Sessionmaker = get_sessionmaker()
        session = Sessionmaker()

    return _build_store_sqlite(session)


def require_secret_store(session: Session | None = None) -> SecretStore:
    """Return a secret store or raise when encryption is not configured.

    Uses the configured storage backend (MongoDB or SQLite).

    Args:
        session: SQLAlchemy session (only required for SQLite backend).

    Returns:
        A secret store instance.

    Raises:
        SecretStoreUnavailable: If the secret store cannot be initialized.
    """
    store = get_secret_store(session)
    if store is None:
        raise SecretStoreUnavailable(
            "Encrypted settings are not available. Configure ATLAS_SECRET_KEY and ensure database is ready.",
        )
    return store


def sync_secure_settings(keys: Iterable[str] | None = None) -> None:
    """Synchronise selected environment variables with the encrypted store.

    - When an environment variable is set (non-empty), its trimmed value is
      encrypted and persisted to the database.
    - When the environment variable is missing or empty, the function attempts
      to load it from the encrypted store and injects it into ``os.environ``.

    The operation is silent when the encryption key is missing, the database
    is not available, or the table does not exist yet.
    """
    cipher = _build_cipher()
    if cipher is None:
        return

    names = tuple(keys or SECURE_ENV_KEYS)
    if not names:
        return

    backend = _get_storage_backend()

    if backend == "mongodb":
        _sync_secure_settings_mongodb(cipher, names)
    else:
        _sync_secure_settings_sqlite(cipher, names)


def _sync_secure_settings_mongodb(cipher: Fernet, names: tuple[str, ...]) -> None:
    """Sync secure settings using MongoDB."""
    if not _mongodb_available():
        return

    store = _MongoDBSecretStore(cipher)
    for name in names:
        env_value = os.getenv(name)
        if env_value is not None and env_value.strip():
            store.set(name, env_value)
        else:
            secret = store.get(name)
            if secret:
                os.environ[name] = secret


def _sync_secure_settings_sqlite(cipher: Fernet, names: tuple[str, ...]) -> None:
    """Sync secure settings using SQLite."""
    from sqlalchemy.exc import SQLAlchemyError

    if not _has_secure_table():
        return

    from infrastructure_atlas.db.config import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        store = _SqlAlchemySecretStore(session, cipher)
        changed = False
        try:
            for name in names:
                env_value = os.getenv(name)
                if env_value is not None and env_value.strip():
                    if store.set(name, env_value):
                        changed = True
                else:
                    secret = store.get(name)
                    if secret:
                        os.environ[name] = secret
            if changed:
                session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            logger.error("Failed to synchronise encrypted settings", exc_info=exc)


__all__ = [
    "SECRET_KEY_ENV",
    "SECURE_ENV_KEYS",
    "SecretStore",
    "SecretStoreUnavailable",
    "get_secret_store",
    "require_secret_store",
    "sync_secure_settings",
]
