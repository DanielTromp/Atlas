"""Foreman configuration and inventory management service."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from infrastructure_atlas.domain.entities import ForemanConfigEntity
from infrastructure_atlas.env import project_root
from infrastructure_atlas.infrastructure.db.repositories import SqlAlchemyForemanConfigRepository
from infrastructure_atlas.infrastructure.external import (
    ForemanAuthError,
    ForemanClient,
    ForemanClientConfig,
    ForemanClientError,
)
from infrastructure_atlas.infrastructure.logging import get_logger
from infrastructure_atlas.infrastructure.security.secret_store import require_secret_store

logger = get_logger(__name__)

CACHE_DIR_ENV = "FOREMAN_CACHE_DIR"
_CACHE_LOCK = Lock()
_CACHE_LOCKS: dict[str, Lock] = {}


def _normalise_name(name: str) -> str:
    """Normalise configuration name."""
    return (name or "").strip()


def _normalise_base_url(url: str) -> str:
    """Normalise base URL."""
    cleaned = (url or "").strip().rstrip("/")
    if not cleaned:
        raise ValueError("Base URL cannot be empty")
    return cleaned


def _clean_token(token: str) -> str:
    """Clean and validate token."""
    cleaned = (token or "").strip()
    if not cleaned:
        raise ValueError("Token cannot be empty")
    return cleaned


def _now_utc() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(UTC)


def _isoformat(dt: datetime | None) -> str | None:
    """Format datetime as ISO string."""
    if dt is None:
        return None
    value = dt.astimezone(UTC).isoformat()
    return value.replace("+00:00", "Z")


def _parse_iso_datetime(value: Any) -> datetime | None:
    """Parse ISO datetime string."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        normalized = text.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).astimezone(UTC)
    except ValueError:
        return None


def _resolve_cache_dir() -> Path:
    """Resolve Foreman cache directory path."""
    raw = (os.getenv(CACHE_DIR_ENV) or "").strip()
    if raw:
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = project_root() / candidate
    else:
        candidate = project_root() / "data" / "foreman"
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


def _cache_lock_for(config_id: str) -> Lock:
    """Get or create a lock for a specific config cache."""
    with _CACHE_LOCK:
        return _CACHE_LOCKS.setdefault(config_id, Lock())


@dataclass(slots=True)
class ForemanService:
    """Application service exposing Foreman configuration operations."""

    session: Session
    _repo: SqlAlchemyForemanConfigRepository | None = field(init=False, repr=False, default=None)
    _cache_dir: Path | None = field(init=False, repr=False, default=None)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_repo", SqlAlchemyForemanConfigRepository(self.session))
        object.__setattr__(self, "_cache_dir", _resolve_cache_dir())

    def _repo_instance(self) -> SqlAlchemyForemanConfigRepository:
        repo = self._repo
        if repo is None:
            repo = SqlAlchemyForemanConfigRepository(self.session)
            object.__setattr__(self, "_repo", repo)
        return repo

    def _cache_dir_path(self) -> Path:
        """Get cache directory path."""
        cache_dir = self._cache_dir
        if cache_dir is None:
            cache_dir = _resolve_cache_dir()
            object.__setattr__(self, "_cache_dir", cache_dir)
        return cache_dir

    # ------------------------------------------------------------------
    # Configuration management
    # ------------------------------------------------------------------
    def list_configs(self) -> list[ForemanConfigEntity]:
        """List all Foreman configurations."""
        return self._repo_instance().list_all()

    def get_config(self, config_id: str) -> ForemanConfigEntity | None:
        """Get a specific Foreman configuration by ID."""
        identifier = (config_id or "").strip()
        if not identifier:
            return None
        return self._repo_instance().get(identifier)

    def create_config(
        self,
        *,
        name: str,
        base_url: str,
        username: str,
        token: str,
        verify_ssl: bool,
    ) -> ForemanConfigEntity:
        """Create a new Foreman configuration.

        Args:
            name: Configuration name (must be unique).
            base_url: Foreman base URL.
            username: Foreman username for API authentication.
            token: Personal Access Token.
            verify_ssl: Whether to verify SSL certificates.

        Returns:
            Created configuration entity.

        Raises:
            ValueError: If validation fails or name already exists.
        """
        normalised_name = _normalise_name(name)
        normalised_url = _normalise_base_url(base_url)
        normalised_username = (username or "").strip()
        if not normalised_username:
            raise ValueError("Username cannot be empty")
        cleaned_token = _clean_token(token)
        store = require_secret_store(self.session)

        config_id = str(uuid.uuid4())
        secret_name = f"foreman:{config_id}:token"

        try:
            entity = self._repo_instance().create(
                config_id=config_id,
                name=normalised_name,
                base_url=normalised_url,
                username=normalised_username,
                token_secret=secret_name,
                verify_ssl=bool(verify_ssl),
            )
        except IntegrityError as exc:
            self.session.rollback()
            raise ValueError("A Foreman configuration with that name already exists") from exc

        try:
            store.set(secret_name, cleaned_token)
            self.session.commit()
        except Exception:
            logger.exception("Failed to persist encrypted token for Foreman '%s'", normalised_name)
            self.session.rollback()
            try:
                self._repo_instance().delete(entity.id)
                self.session.commit()
            except Exception:  # pragma: no cover - defensive cleanup
                self.session.rollback()
            raise

        return entity

    def update_config(  # noqa: PLR0913
        self,
        config_id: str,
        *,
        name: str | None = None,
        base_url: str | None = None,
        username: str | None = None,
        token: str | None = None,
        verify_ssl: bool | None = None,
    ) -> ForemanConfigEntity:
        """Update an existing Foreman configuration.

        Args:
            config_id: Configuration ID.
            name: New name (optional).
            base_url: New base URL (optional).
            username: New username (optional).
            token: New token (optional).
            verify_ssl: New SSL verification setting (optional).

        Returns:
            Updated configuration entity.

        Raises:
            ValueError: If configuration not found or validation fails.
        """
        repo = self._repo_instance()
        config = repo.get(config_id)
        if config is None:
            raise ValueError("Foreman configuration not found")

        update_data: dict[str, Any] = {}
        if name is not None:
            update_data["name"] = _normalise_name(name)
        if base_url is not None:
            update_data["base_url"] = _normalise_base_url(base_url)
        if username is not None:
            normalised_username = (username or "").strip()
            if not normalised_username:
                raise ValueError("Username cannot be empty")
            update_data["username"] = normalised_username
        if verify_ssl is not None:
            update_data["verify_ssl"] = bool(verify_ssl)

        try:
            entity = repo.update(config_id, **update_data)
        except IntegrityError as exc:
            self.session.rollback()
            raise ValueError("A Foreman configuration with that name already exists") from exc

        if entity is None:
            raise ValueError("Foreman configuration not found")

        if token is not None:
            cleaned = _clean_token(token)
            store = require_secret_store(self.session)
            store.set(entity.token_secret, cleaned)

        self.session.commit()
        return entity

    def delete_config(self, config_id: str) -> bool:
        """Delete a Foreman configuration.

        Args:
            config_id: Configuration ID.

        Returns:
            True if deleted, False if not found.
        """
        repo = self._repo_instance()
        config = repo.get(config_id)
        if config is None:
            return False
        store = require_secret_store(self.session)
        removed = repo.delete(config_id)
        if removed:
            store.delete(config.token_secret)
            self.session.commit()
        return removed

    def test_connection(self, config_id: str) -> dict[str, Any]:
        """Test connectivity to a Foreman instance.

        Args:
            config_id: Configuration ID.

        Returns:
            Dictionary with connection status and details.

        Raises:
            ValueError: If configuration not found.
        """
        config = self.get_config(config_id)
        if config is None:
            raise ValueError("Foreman configuration not found")

        store = require_secret_store(self.session)
        token = store.get(config.token_secret)
        if not token:
            raise ValueError("Token not found in secret store")

        client_config = ForemanClientConfig(
            base_url=config.base_url,
            username=config.username,
            token=token,
            verify_ssl=config.verify_ssl,
        )

        try:
            client = ForemanClient(client_config)
            with client:
                client.test_connection()
            return {
                "status": "success",
                "message": "Successfully connected to Foreman",
                "base_url": config.base_url,
            }
        except ForemanAuthError as exc:
            return {
                "status": "error",
                "message": f"Authentication failed: {exc}",
                "base_url": config.base_url,
            }
        except ForemanClientError as exc:
            return {
                "status": "error",
                "message": f"Connection failed: {exc}",
                "base_url": config.base_url,
            }
        except Exception as exc:  # pragma: no cover - unexpected errors
            logger.exception("Unexpected error testing Foreman connection")
            return {
                "status": "error",
                "message": f"Unexpected error: {exc}",
                "base_url": config.base_url,
            }

    def get_client(self, config_id: str) -> ForemanClient:
        """Get a ForemanClient instance for a configuration.

        Args:
            config_id: Configuration ID.

        Returns:
            Configured ForemanClient instance.

        Raises:
            ValueError: If configuration not found or token unavailable.
        """
        config = self.get_config(config_id)
        if config is None:
            raise ValueError("Foreman configuration not found")

        store = require_secret_store(self.session)
        token = store.get(config.token_secret)
        if not token:
            raise ValueError("Token not found in secret store")

        return ForemanClient(
            ForemanClientConfig(
                base_url=config.base_url,
                username=config.username,
                token=token,
                verify_ssl=config.verify_ssl,
            )
        )

    # ------------------------------------------------------------------
    # Inventory management with caching
    # ------------------------------------------------------------------
    def list_configs_with_status(self) -> list[tuple[ForemanConfigEntity, dict[str, Any]]]:
        """List all configurations with cache status metadata."""
        results: list[tuple[ForemanConfigEntity, dict[str, Any]]] = []
        repo = self._repo_instance()
        for config in repo.list_all():
            cache = self._load_cache_entry(config.id)
            meta = cache["meta"] if cache else {}
            results.append((config, meta))
        return results

    def refresh_inventory(
        self,
        config_id: str,
    ) -> tuple[ForemanConfigEntity, list[dict[str, Any]], dict[str, Any]]:
        """Refresh Foreman hosts inventory and update cache.

        Args:
            config_id: Configuration ID.

        Returns:
            Tuple of (config, hosts list, metadata).

        Raises:
            ValueError: If configuration not found.
        """
        repo = self._repo_instance()
        config = repo.get(config_id)
        if config is None:
            raise ValueError("Foreman configuration not found")

        store = require_secret_store(self.session)
        token = store.get(config.token_secret)
        if not token:
            raise ValueError("Token not found in secret store")

        client_config = ForemanClientConfig(
            base_url=config.base_url,
            username=config.username,
            token=token,
            verify_ssl=config.verify_ssl,
        )

        try:
            client = ForemanClient(client_config)
            with client:
                hosts = client.list_hosts(force_refresh=True)

            generated_at = _now_utc()
            meta = {
                "generated_at": generated_at,
                "host_count": len(hosts),
                "source": "live",
            }

            self._write_cache(config, hosts, meta)
            return config, hosts, meta
        except ForemanAuthError as exc:
            logger.error("Foreman authentication failed for %s: %s", config_id, exc)
            raise
        except ForemanClientError as exc:
            logger.error("Foreman API error for %s: %s", config_id, exc)
            raise

    def get_inventory(
        self,
        config_id: str,
        *,
        refresh: bool = False,
    ) -> tuple[ForemanConfigEntity, list[dict[str, Any]], dict[str, Any]]:
        """Get Foreman hosts inventory, using cache if available.

        Args:
            config_id: Configuration ID.
            refresh: If True, force refresh from API.

        Returns:
            Tuple of (config, hosts list, metadata).

        Raises:
            ValueError: If configuration not found.
        """
        if refresh:
            return self.refresh_inventory(config_id)

        repo = self._repo_instance()
        config = repo.get(config_id)
        if config is None:
            raise ValueError("Foreman configuration not found")

        cache = self._load_cache_entry(config_id)
        if cache:
            meta = dict(cache["meta"])
            meta["source"] = "cache"
            return config, cache["hosts"], meta
        return self.refresh_inventory(config_id)

    # ------------------------------------------------------------------
    # Internal cache helpers
    # ------------------------------------------------------------------
    def _cache_path(self, config_id: str) -> Path:
        """Get cache file path for a configuration."""
        return self._cache_dir_path() / f"{config_id}.json"

    def _load_cache_entry(self, config_id: str) -> dict[str, Any] | None:
        """Load cache entry from disk."""
        path = self._cache_path(config_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Failed to read Foreman cache for %s", config_id, exc_info=True)
            return None

        generated_at = _parse_iso_datetime(payload.get("generated_at"))
        hosts_payload = payload.get("hosts")
        if not isinstance(hosts_payload, list):
            return None

        hosts: list[dict[str, Any]] = []
        for item in hosts_payload:
            if isinstance(item, dict):
                hosts.append(item)

        host_count = len(hosts)
        if "host_count" in payload:
            try:
                host_count = int(payload["host_count"])
            except (ValueError, TypeError):
                pass

        meta = {
            "generated_at": generated_at,
            "host_count": host_count,
        }
        return {"meta": meta, "hosts": hosts}

    def _write_cache(
        self,
        config: ForemanConfigEntity,
        hosts: Iterable[dict[str, Any]],
        meta: Mapping[str, Any],
    ) -> None:
        """Write cache entry to disk."""
        path = self._cache_path(config.id)
        lock = _cache_lock_for(config.id)
        host_list = list(hosts)

        payload: dict[str, Any] = {
            "config_id": config.id,
            "config_name": config.name,
            "generated_at": _isoformat(meta.get("generated_at")),
            "host_count": len(host_list),
            "hosts": host_list,
        }

        with lock:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
                logger.debug("Wrote Foreman cache for %s (%d hosts)", config.id, len(host_list))
            except Exception:
                logger.exception("Failed to write Foreman cache for %s", config.id)
                raise


class MongoDBForemanService:
    """MongoDB-based Foreman configuration and inventory management service."""

    def __init__(self, repo: Any) -> None:
        self._repo = repo
        self._cache_dir = _resolve_cache_dir()

    def _cache_dir_path(self) -> Path:
        """Get cache directory path."""
        if self._cache_dir is None:
            self._cache_dir = _resolve_cache_dir()
        return self._cache_dir

    # ------------------------------------------------------------------
    # Configuration management
    # ------------------------------------------------------------------
    def list_configs(self) -> list[ForemanConfigEntity]:
        """List all Foreman configurations."""
        return self._repo.list_all()

    def get_config(self, config_id: str) -> ForemanConfigEntity | None:
        """Get a specific Foreman configuration by ID."""
        identifier = (config_id or "").strip()
        if not identifier:
            return None
        return self._repo.get(identifier)

    def create_config(
        self,
        *,
        name: str,
        base_url: str,
        username: str,
        token: str,
        verify_ssl: bool,
    ) -> ForemanConfigEntity:
        """Create a new Foreman configuration."""
        import uuid as uuid_module

        normalised_name = _normalise_name(name)
        normalised_url = _normalise_base_url(base_url)
        normalised_username = (username or "").strip()
        if not normalised_username:
            raise ValueError("Username cannot be empty")
        cleaned_token = _clean_token(token)
        store = require_secret_store()

        config_id = str(uuid_module.uuid4())
        secret_name = f"foreman:{config_id}:token"

        try:
            entity = self._repo.create(
                config_id=config_id,
                name=normalised_name,
                base_url=normalised_url,
                username=normalised_username,
                token_secret=secret_name,
                verify_ssl=bool(verify_ssl),
            )
        except ValueError:
            raise

        try:
            store.set(secret_name, cleaned_token)
        except Exception:
            logger.exception("Failed to persist encrypted token for Foreman '%s'", normalised_name)
            try:
                self._repo.delete(entity.id)
            except Exception:  # pragma: no cover - defensive cleanup
                pass
            raise

        return entity

    def update_config(  # noqa: PLR0913
        self,
        config_id: str,
        *,
        name: str | None = None,
        base_url: str | None = None,
        username: str | None = None,
        token: str | None = None,
        verify_ssl: bool | None = None,
    ) -> ForemanConfigEntity:
        """Update an existing Foreman configuration."""
        config = self._repo.get(config_id)
        if config is None:
            raise ValueError("Foreman configuration not found")

        update_data: dict[str, Any] = {}
        if name is not None:
            update_data["name"] = _normalise_name(name)
        if base_url is not None:
            update_data["base_url"] = _normalise_base_url(base_url)
        if username is not None:
            normalised_username = (username or "").strip()
            if not normalised_username:
                raise ValueError("Username cannot be empty")
            update_data["username"] = normalised_username
        if verify_ssl is not None:
            update_data["verify_ssl"] = bool(verify_ssl)

        entity = self._repo.update(config_id, **update_data)
        if entity is None:
            raise ValueError("Foreman configuration not found")

        if token is not None:
            cleaned = _clean_token(token)
            store = require_secret_store()
            store.set(entity.token_secret, cleaned)

        return entity

    def delete_config(self, config_id: str) -> bool:
        """Delete a Foreman configuration."""
        config = self._repo.get(config_id)
        if config is None:
            return False
        store = require_secret_store()
        removed = self._repo.delete(config_id)
        if removed:
            store.delete(config.token_secret)
        return removed

    def test_connection(self, config_id: str) -> dict[str, Any]:
        """Test connectivity to a Foreman instance."""
        config = self.get_config(config_id)
        if config is None:
            raise ValueError("Foreman configuration not found")

        store = require_secret_store()
        token = store.get(config.token_secret)
        if not token:
            raise ValueError("Token not found in secret store")

        client_config = ForemanClientConfig(
            base_url=config.base_url,
            username=config.username,
            token=token,
            verify_ssl=config.verify_ssl,
        )

        try:
            client = ForemanClient(client_config)
            with client:
                client.test_connection()
            return {
                "status": "success",
                "message": "Successfully connected to Foreman",
                "base_url": config.base_url,
            }
        except ForemanAuthError as exc:
            return {
                "status": "error",
                "message": f"Authentication failed: {exc}",
                "base_url": config.base_url,
            }
        except ForemanClientError as exc:
            return {
                "status": "error",
                "message": f"Connection failed: {exc}",
                "base_url": config.base_url,
            }
        except Exception as exc:  # pragma: no cover - unexpected errors
            logger.exception("Unexpected error testing Foreman connection")
            return {
                "status": "error",
                "message": f"Unexpected error: {exc}",
                "base_url": config.base_url,
            }

    def get_client(self, config_id: str) -> ForemanClient:
        """Get a ForemanClient instance for a configuration."""
        config = self.get_config(config_id)
        if config is None:
            raise ValueError("Foreman configuration not found")

        store = require_secret_store()
        token = store.get(config.token_secret)
        if not token:
            raise ValueError("Token not found in secret store")

        return ForemanClient(
            ForemanClientConfig(
                base_url=config.base_url,
                username=config.username,
                token=token,
                verify_ssl=config.verify_ssl,
            )
        )

    # ------------------------------------------------------------------
    # Inventory management with caching
    # ------------------------------------------------------------------
    def list_configs_with_status(self) -> list[tuple[ForemanConfigEntity, dict[str, Any]]]:
        """List all configurations with cache status metadata."""
        results: list[tuple[ForemanConfigEntity, dict[str, Any]]] = []
        for config in self._repo.list_all():
            cache = self._load_cache_entry(config.id)
            meta = cache["meta"] if cache else {}
            results.append((config, meta))
        return results

    def refresh_inventory(
        self,
        config_id: str,
    ) -> tuple[ForemanConfigEntity, list[dict[str, Any]], dict[str, Any]]:
        """Refresh Foreman hosts inventory and update cache."""
        config = self._repo.get(config_id)
        if config is None:
            raise ValueError("Foreman configuration not found")

        store = require_secret_store()
        token = store.get(config.token_secret)
        if not token:
            raise ValueError("Token not found in secret store")

        client_config = ForemanClientConfig(
            base_url=config.base_url,
            username=config.username,
            token=token,
            verify_ssl=config.verify_ssl,
        )

        try:
            client = ForemanClient(client_config)
            with client:
                hosts = client.list_hosts(force_refresh=True)

            generated_at = _now_utc()
            meta = {
                "generated_at": generated_at,
                "host_count": len(hosts),
                "source": "live",
            }

            self._write_cache(config, hosts, meta)
            return config, hosts, meta
        except ForemanAuthError as exc:
            logger.error("Foreman authentication failed for %s: %s", config_id, exc)
            raise
        except ForemanClientError as exc:
            logger.error("Foreman API error for %s: %s", config_id, exc)
            raise

    def get_inventory(
        self,
        config_id: str,
        *,
        refresh: bool = False,
    ) -> tuple[ForemanConfigEntity, list[dict[str, Any]], dict[str, Any]]:
        """Get Foreman hosts inventory, using cache if available."""
        if refresh:
            return self.refresh_inventory(config_id)

        config = self._repo.get(config_id)
        if config is None:
            raise ValueError("Foreman configuration not found")

        cache = self._load_cache_entry(config_id)
        if cache:
            meta = dict(cache["meta"])
            meta["source"] = "cache"
            return config, cache["hosts"], meta
        return self.refresh_inventory(config_id)

    # ------------------------------------------------------------------
    # Internal cache helpers
    # ------------------------------------------------------------------
    def _cache_path(self, config_id: str) -> Path:
        """Get cache file path for a configuration."""
        return self._cache_dir_path() / f"{config_id}.json"

    def _load_cache_entry(self, config_id: str) -> dict[str, Any] | None:
        """Load cache entry from disk."""
        path = self._cache_path(config_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Failed to read Foreman cache for %s", config_id, exc_info=True)
            return None

        generated_at = _parse_iso_datetime(payload.get("generated_at"))
        hosts_payload = payload.get("hosts")
        if not isinstance(hosts_payload, list):
            return None

        hosts: list[dict[str, Any]] = []
        for item in hosts_payload:
            if isinstance(item, dict):
                hosts.append(item)

        host_count = len(hosts)
        if "host_count" in payload:
            try:
                host_count = int(payload["host_count"])
            except (ValueError, TypeError):
                pass

        meta = {
            "generated_at": generated_at,
            "host_count": host_count,
        }
        return {"meta": meta, "hosts": hosts}

    def _write_cache(
        self,
        config: ForemanConfigEntity,
        hosts: Iterable[dict[str, Any]],
        meta: Mapping[str, Any],
    ) -> None:
        """Write cache entry to disk."""
        path = self._cache_path(config.id)
        lock = _cache_lock_for(config.id)
        host_list = list(hosts)

        payload: dict[str, Any] = {
            "config_id": config.id,
            "config_name": config.name,
            "generated_at": _isoformat(meta.get("generated_at")),
            "host_count": len(host_list),
            "hosts": host_list,
        }

        with lock:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
                logger.debug("Wrote Foreman cache for %s (%d hosts)", config.id, len(host_list))
            except Exception:
                logger.exception("Failed to write Foreman cache for %s", config.id)
                raise


# Type alias for service protocol
ForemanServiceProtocol = ForemanService | MongoDBForemanService


def create_foreman_service(session: Any = None) -> ForemanServiceProtocol:
    """Factory function to create a ForemanService instance.

    Uses the configured storage backend to return the appropriate implementation.
    """
    from infrastructure_atlas.infrastructure.repository_factory import get_storage_backend

    backend = get_storage_backend()

    if backend == "mongodb":
        from infrastructure_atlas.infrastructure.mongodb import get_mongodb_client
        from infrastructure_atlas.infrastructure.mongodb.repositories import MongoDBForemanConfigRepository

        client = get_mongodb_client()
        repo = MongoDBForemanConfigRepository(client.atlas)
        return MongoDBForemanService(repo)
    else:
        if session is None:
            from infrastructure_atlas.db import get_sessionmaker

            SessionLocal = get_sessionmaker()
            session = SessionLocal()
        return ForemanService(session=session)
