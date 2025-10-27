"""Backup provider abstraction bridging the existing backup_sync helpers."""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path

from infrastructure_atlas.backup_sync import BackupConfig, _iter_paths, _load_config, sync_paths
from infrastructure_atlas.domain.integrations import BackupJobSummary


class BackupProvider:
    """Typed facade for invoking the legacy backup synchronisation helpers."""

    def __init__(self, config: BackupConfig) -> None:
        self._config = config

    @property
    def data_dir(self) -> Path:
        return self._config.data_dir

    @classmethod
    def from_env(cls) -> BackupProvider | None:
        config = _load_config()
        if config is None:
            return None
        return cls(config)

    def iter_paths(self, paths: Iterable[Path]) -> Sequence[tuple[Path, str]]:
        return _iter_paths(paths, self._config.data_dir)

    def run(self, paths: Iterable[Path], *, note: str | None = None) -> BackupJobSummary:
        files = tuple(Path(p) for p in paths)
        start = datetime.utcnow()
        result = sync_paths(list(files), note=note)
        timestamp_raw = result.get("timestamp")
        try:
            completed = datetime.fromisoformat(str(timestamp_raw).replace("Z", "+00:00"))
        except Exception:
            completed = datetime.utcnow()
        return BackupJobSummary(
            status=str(result.get("status", "unknown")),
            detail=result,
            started_at=start,
            completed_at=completed,
            files=files,
        )


__all__ = ["BackupProvider"]
