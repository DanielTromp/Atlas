"""Shared tasks functionality - dataset definitions, types, and helpers."""

from __future__ import annotations

import os
import shlex
import shutil
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from infrastructure_atlas.application.services import create_foreman_service, create_vcenter_service
from infrastructure_atlas.db import get_sessionmaker
from infrastructure_atlas.env import project_root

# Type aliases
CommandBuilder = Callable[["DatasetDefinition", "DatasetMetadata"], list[str] | None]
MetadataBuilder = Callable[["DatasetDefinition"], "DatasetMetadata"]

# Constants
TASK_OUTPUT_LINE_LIMIT = 500

SessionLocal = get_sessionmaker()


# Data classes


@dataclass(frozen=True, slots=True)
class DatasetDefinition:
    """Definition of a cached dataset task."""

    id: str
    label: str
    path_globs: tuple[str, ...]
    description: str | None = None
    since_source: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    command_builder: CommandBuilder | None = None
    metadata_builder: MetadataBuilder | None = None


@dataclass(slots=True)
class DatasetFileRecord:
    """Record of a file in a dataset."""

    relative_path: str
    absolute_path: Path
    exists: bool
    size_bytes: int | None
    modified: datetime | None


@dataclass(slots=True)
class DatasetMetadata:
    """Metadata about a dataset."""

    definition: DatasetDefinition
    files: list[DatasetFileRecord]
    last_updated: datetime | None
    extras: dict[str, Any] = field(default_factory=dict)

    def find_file(self, relative_path: str) -> DatasetFileRecord | None:
        """Find a file record by relative path."""
        for record in self.files:
            if record.relative_path == relative_path:
                return record
        return None


# Helper functions


def _data_dir() -> Path:
    """Return the data directory path."""
    root = project_root()
    raw = os.getenv("NETBOX_DATA_DIR", "data")
    path = Path(raw) if os.path.isabs(raw) else (root / raw)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _command_with_uv(args: Sequence[str]) -> list[str]:
    """Build command with uv if available, otherwise use python.

    Args should NOT include "atlas" - this function adds the correct prefix:
    - With uv: ["uv", "run", "atlas", *args]
    - Without uv: [sys.executable, "-m", "infrastructure_atlas.cli", *args]
    """
    if shutil.which("uv"):
        return ["uv", "run", "atlas", *args]
    return [sys.executable, "-m", "infrastructure_atlas.cli", *args]


def _append_task_output(buffer: list[str], line: str) -> None:
    """Append line to output buffer, maintaining size limit."""
    buffer.append(line)
    if len(buffer) > TASK_OUTPUT_LINE_LIMIT:
        del buffer[: len(buffer) - TASK_OUTPUT_LINE_LIMIT]


def _build_netbox_cache_command(defn: DatasetDefinition, meta: DatasetMetadata) -> list[str]:
    """Build command to refresh NetBox cache."""
    return _command_with_uv(["export", "cache"])


def _make_vcenter_command_builder(config_id: str) -> CommandBuilder:
    """Create a command builder for vCenter refresh."""

    def _builder(_: DatasetDefinition, __: DatasetMetadata) -> list[str]:
        return _command_with_uv(["vcenter", "refresh", "--id", config_id])

    return _builder


def _build_commvault_metadata(defn: DatasetDefinition) -> DatasetMetadata:
    """Build metadata for Commvault dataset, reading generated_at from JSON."""
    import json
    from datetime import datetime, UTC

    base = _data_dir()
    files: list[DatasetFileRecord] = []
    last_updated: datetime | None = None

    # Build file records
    for pattern in defn.path_globs:
        pattern_norm = (pattern or "").strip()
        if not pattern_norm:
            continue
        path = base / pattern_norm
        files.append(_dataset_file_record(base, path))

    # Read generated_at from the backups JSON (primary cache file)
    backups_path = base / "commvault_backups.json"
    if backups_path.exists():
        try:
            with backups_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
                generated_at_str = data.get("generated_at")
                if generated_at_str:
                    last_updated = datetime.fromisoformat(generated_at_str.replace("Z", "+00:00"))
        except Exception:
            pass

    # Fallback to file modification time if no generated_at
    if last_updated is None:
        for record in files:
            if record.modified and (last_updated is None or record.modified > last_updated):
                last_updated = record.modified

    return DatasetMetadata(definition=defn, files=files, last_updated=last_updated)


def _build_commvault_command(defn: DatasetDefinition, meta: DatasetMetadata) -> list[str]:
    """Build command to refresh all Commvault caches (backups, plans, storage)."""
    return _command_with_uv(["commvault", "refresh"])


def _collect_task_dataset_definitions() -> list[DatasetDefinition]:
    """Collect all dataset task definitions."""
    definitions: list[DatasetDefinition] = [
        DatasetDefinition(
            id="netbox-cache",
            label="NetBox Cache",
            path_globs=("netbox_cache.json",),
            description="Cached NetBox snapshot used for export diffing.",
            command_builder=_build_netbox_cache_command,
        ),
        DatasetDefinition(
            id="commvault",
            label="Commvault",
            path_globs=("commvault_backups.json", "commvault_plans.json", "commvault_storage.json"),
            description="Cached Commvault data (backups, plans, and storage pools).",
            command_builder=_build_commvault_command,
            metadata_builder=_build_commvault_metadata,
        ),
    ]
    definitions.extend(_discover_vcenter_task_definitions())
    definitions.extend(_discover_foreman_task_definitions())
    return definitions


def _discover_vcenter_task_definitions() -> list[DatasetDefinition]:
    """Discover vCenter dataset tasks from database and filesystem."""
    definitions: list[DatasetDefinition] = []
    known_configs: dict[str, str | None] = {}
    try:
        with SessionLocal() as session:
            service = create_vcenter_service(session)
            entries = service.list_configs_with_status()
    except Exception:
        entries = []
    for config, _meta in entries:
        label = f"vCenter: {config.name or config.id}"
        definitions.append(
            DatasetDefinition(
                id=f"vcenter-{config.id}",
                label=label,
                path_globs=(f"vcenter/{config.id}.json",),
                description="Cached vCenter inventory snapshot.",
                since_source=None,
                context={
                    "config_id": config.id,
                    "config_name": config.name,
                },
                command_builder=_make_vcenter_command_builder(config.id),
            )
        )
        known_configs[config.id] = config.name

    vcenter_dir = _data_dir() / "vcenter"
    if vcenter_dir.exists():
        for path in sorted(vcenter_dir.glob("*.json")):
            config_id = path.stem
            if config_id in known_configs:
                continue
            label = f"vCenter cache ({config_id})"
            definitions.append(
                DatasetDefinition(
                    id=f"vcenter-{config_id}",
                    label=label,
                    path_globs=(f"vcenter/{path.name}",),
                    description="Cached vCenter inventory snapshot.",
                    context={
                        "config_id": config_id,
                        "config_name": None,
                        "orphan": True,
                    },
                    command_builder=_make_vcenter_command_builder(config_id),
                )
            )
    return definitions


def _make_foreman_command_builder(config_id: str) -> CommandBuilder:
    """Create a command builder for Foreman refresh."""

    def _builder(_: DatasetDefinition, __: DatasetMetadata) -> list[str]:
        return _command_with_uv(["foreman", "refresh", "--config-id", config_id])

    return _builder


def _discover_foreman_task_definitions() -> list[DatasetDefinition]:
    """Discover Foreman dataset tasks from database and filesystem."""
    definitions: list[DatasetDefinition] = []
    known_configs: dict[str, str | None] = {}
    try:
        with SessionLocal() as session:
            service = create_foreman_service(session)
            entries = service.list_configs_with_status()
    except Exception:
        entries = []
    for config, _meta in entries:
        label = f"Foreman: {config.name or config.id}"
        definitions.append(
            DatasetDefinition(
                id=f"foreman-{config.id}",
                label=label,
                path_globs=(f"foreman/{config.id}.json",),
                description="Cached Foreman hosts snapshot.",
                since_source=None,
                context={
                    "config_id": config.id,
                    "config_name": config.name,
                },
                command_builder=_make_foreman_command_builder(config.id),
            )
        )
        known_configs[config.id] = config.name

    foreman_dir = _data_dir() / "foreman"
    if foreman_dir.exists():
        for path in sorted(foreman_dir.glob("*.json")):
            config_id = path.stem
            if config_id in known_configs:
                continue
            label = f"Foreman cache ({config_id})"
            definitions.append(
                DatasetDefinition(
                    id=f"foreman-{config_id}",
                    label=label,
                    path_globs=(f"foreman/{path.name}",),
                    description="Cached Foreman hosts snapshot.",
                    context={
                        "config_id": config_id,
                        "config_name": None,
                        "orphan": True,
                    },
                    command_builder=_make_foreman_command_builder(config_id),
                )
            )
    return definitions


def _dataset_file_record(base: Path, path: Path) -> DatasetFileRecord:
    """Create a file record for a path."""
    try:
        relative = path.relative_to(base)
        relative_str = relative.as_posix()
    except ValueError:
        relative_str = path.as_posix()
    exists = path.exists()
    size = None
    modified: datetime | None = None
    if exists:
        try:
            stat = path.stat()
        except FileNotFoundError:
            exists = False
        else:
            size = stat.st_size
            modified = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
    return DatasetFileRecord(
        relative_path=relative_str,
        absolute_path=path,
        exists=exists,
        size_bytes=size,
        modified=modified,
    )


def _get_storage_backend() -> str:
    """Get the configured storage backend."""
    from infrastructure_atlas.infrastructure.repository_factory import get_storage_backend
    return get_storage_backend()


def _build_vcenter_metadata_mongodb(defn: DatasetDefinition) -> DatasetMetadata:
    """Build vCenter metadata from MongoDB cache."""
    config_id = defn.context.get("config_id")
    if not config_id:
        return DatasetMetadata(definition=defn, files=[], last_updated=None)

    try:
        from infrastructure_atlas.infrastructure.mongodb import get_mongodb_client
        from infrastructure_atlas.infrastructure.mongodb.cache_repositories import MongoDBVCenterCacheRepository

        client = get_mongodb_client()
        cache_repo = MongoDBVCenterCacheRepository(client.atlas_cache)
        meta = cache_repo.get_cache_metadata(config_id)

        if meta:
            vm_count = meta.get("vm_count", 0)
            last_updated = meta.get("generated_at")
            # Create a virtual file record representing the MongoDB cache
            files = [
                DatasetFileRecord(
                    relative_path=f"mongodb://atlas_cache/vcenter_vms?config_id={config_id}",
                    absolute_path=Path(f"/mongodb/vcenter_vms/{config_id}"),
                    exists=vm_count > 0,
                    size_bytes=vm_count,  # Use VM count as "size"
                    modified=last_updated,
                )
            ]
            return DatasetMetadata(
                definition=defn,
                files=files,
                last_updated=last_updated,
                extras={"vm_count": vm_count, "source": "mongodb"},
            )
    except Exception:
        pass

    return DatasetMetadata(definition=defn, files=[], last_updated=None)


def _build_netbox_metadata_mongodb(defn: DatasetDefinition) -> DatasetMetadata:
    """Build NetBox metadata from MongoDB cache."""
    try:
        from infrastructure_atlas.infrastructure.mongodb import get_mongodb_client
        from infrastructure_atlas.infrastructure.mongodb.cache_repositories import MongoDBNetBoxCacheRepository

        client = get_mongodb_client()
        cache_repo = MongoDBNetBoxCacheRepository(client.atlas_cache)

        # Get cache metadata (includes generated_at timestamp)
        meta = cache_repo.get_cache_metadata()
        stats = cache_repo.get_cache_stats()

        device_count = stats.get("devices", {}).get("count", 0)
        vm_count = stats.get("vms", {}).get("count", 0)

        # Use generated_at from metadata
        last_updated = meta.get("generated_at") if meta else None

        files = [
            DatasetFileRecord(
                relative_path="mongodb://atlas_cache/netbox_devices",
                absolute_path=Path("/mongodb/netbox_devices"),
                exists=device_count > 0,
                size_bytes=device_count,
                modified=last_updated,
            ),
            DatasetFileRecord(
                relative_path="mongodb://atlas_cache/netbox_vms",
                absolute_path=Path("/mongodb/netbox_vms"),
                exists=vm_count > 0,
                size_bytes=vm_count,
                modified=last_updated,
            ),
        ]
        return DatasetMetadata(
            definition=defn,
            files=files,
            last_updated=last_updated,
            extras={"device_count": device_count, "vm_count": vm_count, "source": "mongodb"},
        )
    except Exception:
        pass

    return DatasetMetadata(definition=defn, files=[], last_updated=None)


def _build_dataset_metadata(defn: DatasetDefinition) -> DatasetMetadata:
    """Build metadata for a dataset definition."""
    # Use custom metadata builder if provided
    if defn.metadata_builder is not None:
        return defn.metadata_builder(defn)

    # Check if using MongoDB backend for vCenter/NetBox datasets
    backend = _get_storage_backend()
    if backend == "mongodb":
        if defn.id.startswith("vcenter-"):
            return _build_vcenter_metadata_mongodb(defn)
        if defn.id == "netbox-cache":
            return _build_netbox_metadata_mongodb(defn)

    # Default metadata building logic (JSON files)
    base = _data_dir()
    files: list[DatasetFileRecord] = []
    for pattern in defn.path_globs:
        pattern_norm = (pattern or "").strip()
        if not pattern_norm:
            continue
        if any(ch in pattern_norm for ch in "*?["):
            matches = sorted(base.glob(pattern_norm))
            for match in matches:
                files.append(_dataset_file_record(base, match))
        else:
            files.append(_dataset_file_record(base, base / pattern_norm))
    last_updated: datetime | None = None
    for record in files:
        if record.modified and (last_updated is None or record.modified > last_updated):
            last_updated = record.modified
    return DatasetMetadata(definition=defn, files=files, last_updated=last_updated)


def _build_dataset_command(defn: DatasetDefinition, meta: DatasetMetadata) -> list[str] | None:
    """Build refresh command for a dataset."""
    if defn.command_builder is None:
        return None
    return defn.command_builder(defn, meta)


def _serialize_dataset(defn: DatasetDefinition, meta: DatasetMetadata, command: list[str] | None) -> dict[str, Any]:
    """Serialize dataset definition and metadata to dict."""
    command_display = shlex.join(command) if command else None
    files_payload = [
        {
            "path": record.relative_path,
            "exists": record.exists,
            "size": record.size_bytes,
            "modified": record.modified.isoformat() if record.modified else None,
            "modified_epoch": int(record.modified.timestamp()) if record.modified else None,
        }
        for record in meta.files
    ]
    # Count files and present files
    file_count = len(files_payload)
    present_files = sum(1 for f in files_payload if f.get("exists"))

    payload: dict[str, Any] = {
        "id": defn.id,
        "label": defn.label,
        "description": defn.description,
        "files": files_payload,
        "file_count": file_count,
        "present_files": present_files,
        "last_updated": meta.last_updated.isoformat() if meta.last_updated else None,
        "last_updated_epoch": int(meta.last_updated.timestamp()) if meta.last_updated else None,
        "command": command_display,
        "can_refresh": command is not None,
        "context": defn.context,
        "extras": meta.extras if meta.extras else {},
    }
    return payload
