"""Domain models for asynchronous jobs and orchestration."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum, IntEnum
from typing import Mapping, Sequence, TypeAlias

JSONPrimitive: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONPrimitive | Sequence["JSONValue"] | Mapping[str, "JSONValue"]


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobPriority(IntEnum):
    LOW = 10
    NORMAL = 50
    HIGH = 90


@dataclass(slots=True)
class JobSpec:
    """Requested job to enqueue."""

    name: str
    payload: Mapping[str, JSONValue]
    priority: JobPriority = JobPriority.NORMAL
    run_at: datetime | None = None
    tags: tuple[str, ...] = ()


@dataclass(slots=True)
class JobRecord:
    """Materialised job tracked by a queue implementation."""

    job_id: str
    name: str
    status: JobStatus
    payload: Mapping[str, JSONValue]
    queued_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    run_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    priority: JobPriority = JobPriority.NORMAL
    attempts: int = 0
    tags: tuple[str, ...] = ()


@dataclass(slots=True)
class JobResult:
    """Outcome metadata for a completed job."""

    job_id: str
    status: JobStatus
    detail: Mapping[str, JSONValue]
    finished_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(slots=True)
class JobFailure:
    """Recorded failure info for observability and retries."""

    job_id: str
    error_type: str
    message: str
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    retryable: bool = False
    detail: Mapping[str, JSONValue] = field(default_factory=dict)


__all__ = [
    "JobFailure",
    "JobPriority",
    "JobRecord",
    "JobResult",
    "JobSpec",
    "JobStatus",
    "JSONValue",
]
