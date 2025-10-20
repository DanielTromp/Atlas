"""Typed models for backup synchronization results."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(slots=True)
class BackupJobSummary:
    """Summary of a backup sync invocation."""

    status: str
    detail: Mapping[str, object]
    started_at: datetime | None = None
    completed_at: datetime | None = None
    files: tuple[Path, ...] = ()

