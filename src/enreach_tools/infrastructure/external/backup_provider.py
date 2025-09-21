"""Backup provider abstraction bridging the existing backup_sync helpers."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from enreach_tools.backup_sync import BackupConfig, _iter_paths, sync_paths, _load_config


@dataclass(slots=True)
class BackupJobResult:
    status: str
    detail: dict


class BackupProvider:
    def __init__(self, config: BackupConfig) -> None:
        self._config = config

    @classmethod
    def from_env(cls) -> "BackupProvider | None":
        config = _load_config()
        if config is None:
            return None
        return cls(config)

    def iter_paths(self, paths: Iterable[Path]) -> Sequence[tuple[Path, str]]:
        return _iter_paths(paths, self._config.data_dir)

    def run(self, paths: Iterable[Path], *, note: str | None = None) -> BackupJobResult:
        files = list(paths)
        result = sync_paths(files, note=note)
        return BackupJobResult(status=result.get("status", "unknown"), detail=result)


__all__ = ["BackupProvider", "BackupJobResult"]
