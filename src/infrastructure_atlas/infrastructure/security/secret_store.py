"""Encrypted secret storage backed by the database.

This module centralises the logic for persisting sensitive configuration
values (API tokens, passwords) in the database while keeping them encrypted at
rest. Secrets are decrypted only when they need to be injected back into the
process environment.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from infrastructure_atlas.db.models import SecureSetting

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
)


class SecretStoreUnavailable(RuntimeError):
    """Raised when the encrypted secret store is unavailable."""


class _SecureSettingStore:
    """Helper implementing CRUD operations for encrypted settings."""

    def __init__(self, session: Session, cipher: Fernet):
        self._session = session
        self._cipher = cipher

    def get(self, name: str) -> str | None:
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
        record = self._session.get(SecureSetting, name)
        if record is None:
            return False
        self._session.delete(record)
        return True


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


def _has_secure_table() -> bool:
    try:
        from infrastructure_atlas.db.config import get_engine

        engine = get_engine()
        inspector = inspect(engine)
        return inspector.has_table(SecureSetting.__tablename__)
    except SQLAlchemyError as exc:
        logger.debug("Unable to inspect database for secure settings table", exc_info=exc)
        return False


def _build_store(session: Session) -> _SecureSettingStore | None:
    cipher = _build_cipher()
    if cipher is None:
        return None
    if not _has_secure_table():
        return None
    return _SecureSettingStore(session, cipher)


def get_secret_store(session: Session) -> _SecureSettingStore | None:
    """Return a secret store instance when encryption is configured."""

    return _build_store(session)


def require_secret_store(session: Session) -> _SecureSettingStore:
    """Return a secret store or raise when encryption is not configured."""

    store = _build_store(session)
    if store is None:
        raise SecretStoreUnavailable(
            "Encrypted settings are not available. Configure ATLAS_SECRET_KEY and run migrations.",
        )
    return store


def sync_secure_settings(keys: Iterable[str] | None = None) -> None:
    """Synchronise selected environment variables with the encrypted store.

    - When an environment variable is set (non-empty), its trimmed value is
      encrypted and persisted to the database.
    - When the environment variable is missing or empty, the function attempts
      to load it from the encrypted store and injects it into ``os.environ``.

    The operation is silent when the encryption key is missing, the table does
    not exist yet, or the database is unreachable.
    """

    cipher = _build_cipher()
    if cipher is None:
        return
    if not _has_secure_table():
        return

    names = tuple(keys or SECURE_ENV_KEYS)
    if not names:
        return

    from infrastructure_atlas.db.config import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        store = _SecureSettingStore(session, cipher)
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
    "SecretStoreUnavailable",
    "get_secret_store",
    "require_secret_store",
    "sync_secure_settings",
]
