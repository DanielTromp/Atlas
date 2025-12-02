"""Puppet configuration and inventory management service."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from infrastructure_atlas.domain.entities import PuppetConfigEntity
from infrastructure_atlas.env import project_root
from infrastructure_atlas.infrastructure.external import (
    GitClient,
    GitClientConfig,
    PuppetGroup,
    PuppetInventory,
    PuppetParser,
    PuppetUser,
    PuppetUserAccess,
)
from infrastructure_atlas.infrastructure.logging import get_logger

logger = get_logger(__name__)

CACHE_DIR_ENV = "PUPPET_CACHE_DIR"
_CACHE_LOCK = Lock()
_CACHE_LOCKS: dict[str, Lock] = {}


def _normalise_name(name: str) -> str:
    """Normalise configuration name."""
    return (name or "").strip()


def _normalise_remote_url(url: str) -> str:
    """Normalise remote URL."""
    cleaned = (url or "").strip()
    if not cleaned:
        raise ValueError("Remote URL cannot be empty")
    return cleaned


def _normalise_branch(branch: str | None) -> str:
    """Normalise branch name."""
    cleaned = (branch or "").strip()
    return cleaned if cleaned else "production"


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
    """Resolve Puppet cache directory path."""
    raw = (os.getenv(CACHE_DIR_ENV) or "").strip()
    if raw:
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = project_root() / candidate
    else:
        candidate = project_root() / "data" / "puppet"
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


def _cache_lock_for(config_id: str) -> Lock:
    """Get or create a lock for a specific config cache."""
    with _CACHE_LOCK:
        return _CACHE_LOCKS.setdefault(config_id, Lock())


def _model_to_entity(model: Any) -> PuppetConfigEntity:
    """Convert SQLAlchemy model to domain entity."""
    return PuppetConfigEntity(
        id=model.id,
        name=model.name,
        remote_url=model.remote_url,
        branch=model.branch,
        ssh_key_secret=model.ssh_key_secret,
        local_path=model.local_path,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


@dataclass(slots=True)
class PuppetService:
    """Application service exposing Puppet configuration operations."""

    session: Session
    _cache_dir: Path | None = field(init=False, repr=False, default=None)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_cache_dir", _resolve_cache_dir())

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
    def list_configs(self) -> list[PuppetConfigEntity]:
        """List all Puppet configurations."""
        from infrastructure_atlas.db.models import PuppetConfig

        configs = self.session.query(PuppetConfig).all()
        return [_model_to_entity(c) for c in configs]

    def get_config(self, config_id: str) -> PuppetConfigEntity | None:
        """Get a specific Puppet configuration by ID."""
        from infrastructure_atlas.db.models import PuppetConfig

        identifier = (config_id or "").strip()
        if not identifier:
            return None
        config = self.session.get(PuppetConfig, identifier)
        return _model_to_entity(config) if config else None

    def create_config(
        self,
        *,
        name: str,
        remote_url: str,
        branch: str | None = None,
        ssh_key_path: str | None = None,
    ) -> PuppetConfigEntity:
        """Create a new Puppet configuration.

        Args:
            name: Configuration name (must be unique).
            remote_url: Git remote URL.
            branch: Git branch name (default: production).
            ssh_key_path: Path to SSH private key for authentication.

        Returns:
            Created configuration entity.

        Raises:
            ValueError: If validation fails or name already exists.
        """
        from infrastructure_atlas.db.models import PuppetConfig
        from infrastructure_atlas.infrastructure.security.secret_store import require_secret_store

        normalised_name = _normalise_name(name)
        if not normalised_name:
            raise ValueError("Name cannot be empty")
        normalised_url = _normalise_remote_url(remote_url)
        normalised_branch = _normalise_branch(branch)

        config_id = str(uuid.uuid4())
        local_path = str(self._cache_dir_path() / "repos" / config_id)

        # Store SSH key in secret store if provided
        ssh_key_secret = None
        if ssh_key_path:
            ssh_key_path = (ssh_key_path or "").strip()
            if ssh_key_path:
                store = require_secret_store(self.session)
                secret_name = f"puppet:{config_id}:ssh_key_path"
                store.set(secret_name, ssh_key_path)
                ssh_key_secret = secret_name

        try:
            config = PuppetConfig(
                id=config_id,
                name=normalised_name,
                remote_url=normalised_url,
                branch=normalised_branch,
                ssh_key_secret=ssh_key_secret,
                local_path=local_path,
            )
            self.session.add(config)
            self.session.commit()
            return _model_to_entity(config)
        except IntegrityError as exc:
            self.session.rollback()
            raise ValueError("A Puppet configuration with that name already exists") from exc

    def update_config(
        self,
        config_id: str,
        *,
        name: str | None = None,
        remote_url: str | None = None,
        branch: str | None = None,
        ssh_key_path: str | None = None,
    ) -> PuppetConfigEntity:
        """Update an existing Puppet configuration.

        Args:
            config_id: Configuration ID.
            name: New name (optional).
            remote_url: New remote URL (optional).
            branch: New branch (optional).
            ssh_key_path: New SSH key path (optional).

        Returns:
            Updated configuration entity.

        Raises:
            ValueError: If configuration not found or validation fails.
        """
        from infrastructure_atlas.db.models import PuppetConfig
        from infrastructure_atlas.infrastructure.security.secret_store import require_secret_store

        config = self.session.get(PuppetConfig, config_id)
        if config is None:
            raise ValueError("Puppet configuration not found")

        if name is not None:
            normalised = _normalise_name(name)
            if not normalised:
                raise ValueError("Name cannot be empty")
            config.name = normalised

        if remote_url is not None:
            config.remote_url = _normalise_remote_url(remote_url)

        if branch is not None:
            config.branch = _normalise_branch(branch)

        if ssh_key_path is not None:
            ssh_key_path = (ssh_key_path or "").strip()
            if ssh_key_path:
                store = require_secret_store(self.session)
                secret_name = f"puppet:{config_id}:ssh_key_path"
                store.set(secret_name, ssh_key_path)
                config.ssh_key_secret = secret_name
            else:
                # Clear SSH key
                if config.ssh_key_secret:
                    store = require_secret_store(self.session)
                    store.delete(config.ssh_key_secret)
                config.ssh_key_secret = None

        try:
            self.session.commit()
            return _model_to_entity(config)
        except IntegrityError as exc:
            self.session.rollback()
            raise ValueError("A Puppet configuration with that name already exists") from exc

    def delete_config(self, config_id: str) -> bool:
        """Delete a Puppet configuration.

        Args:
            config_id: Configuration ID.

        Returns:
            True if deleted, False if not found.
        """
        from infrastructure_atlas.db.models import PuppetConfig
        from infrastructure_atlas.infrastructure.security.secret_store import require_secret_store

        config = self.session.get(PuppetConfig, config_id)
        if config is None:
            return False

        # Clean up SSH key secret
        if config.ssh_key_secret:
            try:
                store = require_secret_store(self.session)
                store.delete(config.ssh_key_secret)
            except Exception:
                logger.warning("Failed to delete SSH key secret for config %s", config_id)

        # Clean up local repository
        if config.local_path:
            import shutil

            local_path = Path(config.local_path)
            if local_path.exists():
                try:
                    shutil.rmtree(local_path)
                except Exception:
                    logger.warning("Failed to delete local repo for config %s", config_id)

        self.session.delete(config)
        self.session.commit()
        return True

    def get_git_client(self, config_id: str) -> GitClient:
        """Get a GitClient instance for a configuration.

        Args:
            config_id: Configuration ID.

        Returns:
            Configured GitClient instance.

        Raises:
            ValueError: If configuration not found.
        """
        from infrastructure_atlas.infrastructure.security.secret_store import require_secret_store

        config = self.get_config(config_id)
        if config is None:
            raise ValueError("Puppet configuration not found")

        ssh_key_path = None
        if config.ssh_key_secret:
            try:
                store = require_secret_store(self.session)
                ssh_key_path = store.get(config.ssh_key_secret)
            except Exception:
                logger.warning("Failed to retrieve SSH key for config %s", config_id)

        local_path = Path(config.local_path) if config.local_path else self._cache_dir_path() / "repos" / config_id

        return GitClient(
            GitClientConfig(
                remote_url=config.remote_url,
                local_path=local_path,
                branch=config.branch,
                ssh_key_path=Path(ssh_key_path) if ssh_key_path else None,
            )
        )

    # ------------------------------------------------------------------
    # Inventory management with caching
    # ------------------------------------------------------------------
    def list_configs_with_status(self) -> list[tuple[PuppetConfigEntity, dict[str, Any]]]:
        """List all configurations with cache status metadata."""
        results: list[tuple[PuppetConfigEntity, dict[str, Any]]] = []
        for config in self.list_configs():
            cache = self._load_cache_entry(config.id)
            meta = cache.get("meta", {}) if cache else {}
            results.append((config, meta))
        return results

    def refresh_inventory(
        self,
        config_id: str,
    ) -> tuple[PuppetConfigEntity, PuppetInventory, dict[str, Any]]:
        """Refresh Puppet inventory by pulling latest from Git and parsing.

        Args:
            config_id: Configuration ID.

        Returns:
            Tuple of (config, inventory, metadata).

        Raises:
            ValueError: If configuration not found.
            GitClientError: If Git operations fail.
        """
        config = self.get_config(config_id)
        if config is None:
            raise ValueError("Puppet configuration not found")

        client = self.get_git_client(config_id)
        with client:
            repo_info = client.ensure_updated()

        # Parse the repository
        local_path = Path(config.local_path) if config.local_path else self._cache_dir_path() / "repos" / config_id
        parser = PuppetParser(local_path)
        inventory = parser.parse_inventory()

        generated_at = _now_utc()
        meta = {
            "generated_at": generated_at,
            "user_count": len(inventory.users),
            "group_count": len(inventory.groups),
            "commit_hash": repo_info.commit_hash,
            "commit_message": repo_info.commit_message,
            "commit_date": repo_info.commit_date,
            "source": "live",
        }

        self._write_cache(config, inventory, meta)
        return config, inventory, meta

    def get_inventory(
        self,
        config_id: str,
        *,
        refresh: bool = False,
    ) -> tuple[PuppetConfigEntity, PuppetInventory, dict[str, Any]]:
        """Get Puppet inventory, using cache if available.

        Args:
            config_id: Configuration ID.
            refresh: If True, force refresh from Git.

        Returns:
            Tuple of (config, inventory, metadata).

        Raises:
            ValueError: If configuration not found.
        """
        if refresh:
            return self.refresh_inventory(config_id)

        config = self.get_config(config_id)
        if config is None:
            raise ValueError("Puppet configuration not found")

        cache = self._load_cache_entry(config_id)
        if cache:
            meta = dict(cache["meta"])
            meta["source"] = "cache"
            return config, cache["inventory"], meta

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
            logger.warning("Failed to read Puppet cache for %s", config_id, exc_info=True)
            return None

        generated_at = _parse_iso_datetime(payload.get("generated_at"))

        # Reconstruct inventory from cached data
        inventory = PuppetInventory()

        users_data = payload.get("users") or {}
        for username, user_data in users_data.items():
            inventory.users[username] = PuppetUser(
                username=user_data.get("username", username),
                uid=user_data.get("uid"),
                key_type=user_data.get("key_type"),
                key_name=user_data.get("key_name"),
                has_password=user_data.get("has_password", False),
                has_ssh_key=user_data.get("has_ssh_key", False),
                source_file=user_data.get("source_file"),
                enabled=user_data.get("enabled", True),
                password_hash=user_data.get("password_hash"),
                password_algorithm=user_data.get("password_algorithm"),
                account_locked=user_data.get("account_locked", False),
                ssh_key=user_data.get("ssh_key"),
                ssh_key_bits=user_data.get("ssh_key_bits"),
            )

        groups_data = payload.get("groups") or {}
        for group_name, group_data in groups_data.items():
            inventory.groups[group_name] = PuppetGroup(
                name=group_data.get("name", group_name),
                gid=group_data.get("gid"),
                members=group_data.get("members", []),
                not_members=group_data.get("not_members", []),
                source_file=group_data.get("source_file"),
            )

        access_data = payload.get("user_access") or []
        for access in access_data:
            inventory.user_access.append(
                PuppetUserAccess(
                    username=access.get("username", ""),
                    group_name=access.get("group_name", ""),
                    has_sudo=access.get("has_sudo", False),
                    access_type=access.get("access_type", "user"),
                )
            )

        inventory.sudo_users = set(payload.get("sudo_users") or [])
        inventory.removed_users = set(payload.get("removed_users") or [])

        meta = {
            "generated_at": generated_at,
            "user_count": len(inventory.users),
            "group_count": len(inventory.groups),
            "commit_hash": payload.get("commit_hash"),
            "commit_message": payload.get("commit_message"),
            "commit_date": payload.get("commit_date"),
        }
        return {"meta": meta, "inventory": inventory}

    def _write_cache(
        self,
        config: PuppetConfigEntity,
        inventory: PuppetInventory,
        meta: Mapping[str, Any],
    ) -> None:
        """Write cache entry to disk."""
        path = self._cache_path(config.id)
        lock = _cache_lock_for(config.id)

        # Serialize inventory
        users_data = {}
        for username, user in inventory.users.items():
            users_data[username] = {
                "username": user.username,
                "uid": user.uid,
                "key_type": user.key_type,
                "key_name": user.key_name,
                "has_password": user.has_password,
                "has_ssh_key": user.has_ssh_key,
                "source_file": user.source_file,
                "enabled": user.enabled,
                "password_algorithm": user.password_algorithm,
                "account_locked": user.account_locked,
                "ssh_key_bits": user.ssh_key_bits,
                # Note: Not storing password_hash or ssh_key content for security
            }

        groups_data = {}
        for group_name, group in inventory.groups.items():
            groups_data[group_name] = {
                "name": group.name,
                "gid": group.gid,
                "members": group.members,
                "not_members": group.not_members,
                "source_file": group.source_file,
            }

        access_data = []
        for access in inventory.user_access:
            access_data.append(
                {
                    "username": access.username,
                    "group_name": access.group_name,
                    "has_sudo": access.has_sudo,
                    "access_type": access.access_type,
                }
            )

        payload: dict[str, Any] = {
            "config_id": config.id,
            "config_name": config.name,
            "generated_at": _isoformat(meta.get("generated_at")),
            "commit_hash": meta.get("commit_hash"),
            "commit_message": meta.get("commit_message"),
            "commit_date": meta.get("commit_date"),
            "user_count": len(inventory.users),
            "group_count": len(inventory.groups),
            "users": users_data,
            "groups": groups_data,
            "user_access": access_data,
            "sudo_users": list(inventory.sudo_users),
            "removed_users": list(inventory.removed_users),
        }

        with lock:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
                logger.debug(
                    "Wrote Puppet cache for %s (%d users, %d groups)",
                    config.id,
                    len(inventory.users),
                    len(inventory.groups),
                )
            except Exception:
                logger.exception("Failed to write Puppet cache for %s", config.id)
                raise


def create_puppet_service(session: Session) -> PuppetService:
    """Factory function to create a PuppetService instance."""
    return PuppetService(session=session)

