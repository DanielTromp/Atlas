"""Protocols and helpers for job queue orchestration."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Awaitable, Callable, Mapping, MutableMapping, Protocol, Sequence

from enreach_tools.domain.tasks import (
    JobFailure,
    JobPriority,
    JobRecord,
    JobResult,
    JobSpec,
    JobStatus,
    JSONValue,
)


class JobQueueError(Exception):
    """Raised when queue operations fail."""


class JobQueue(Protocol):
    """Abstract interface consumed by the application layer."""

    async def enqueue(self, spec: JobSpec) -> JobRecord:
        ...

    async def reserve(self, *, timeout: float | None = None) -> JobRecord | None:
        ...

    async def complete(self, job_id: str, detail: Mapping[str, JSONValue] | None = None) -> JobResult:
        ...

    async def fail(self, job_id: str, failure: JobFailure) -> JobFailure:
        ...

    async def heartbeat(self, job_id: str) -> None:
        ...

    async def stats(self) -> "JobQueueStats":
        ...

    async def list_jobs(self, *, limit: int = 100, statuses: Sequence[JobStatus] | None = None) -> Sequence[JobRecord]:
        ...

    async def get_job(self, job_id: str) -> JobRecord | None:
        ...


JobHandler = Callable[[JobRecord], Awaitable[Mapping[str, JSONValue] | None]]


@dataclass(slots=True)
class JobQueueStats:
    queued: int
    running: int
    completed: int
    failed: int


class AsyncJobRunner:
    """Background worker that consumes jobs from a queue and invokes handlers."""

    def __init__(
        self,
        queue: JobQueue,
        *,
        poll_interval: float = 0.5,
    ) -> None:
        self._queue = queue
        self._poll_interval = poll_interval
        self._handlers: MutableMapping[str, JobHandler] = {}
        self._stop_event = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []

    def register_handler(self, job_name: str, handler: JobHandler) -> None:
        self._handlers[job_name] = handler

    async def start(self, *, concurrency: int = 1) -> None:
        if concurrency <= 0:
            raise ValueError("concurrency must be >= 1")
        self._stop_event.clear()
        for _ in range(concurrency):
            self._tasks.append(asyncio.create_task(self._worker()))

    async def stop(self) -> None:
        self._stop_event.set()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()

    async def _worker(self) -> None:
        while not self._stop_event.is_set():
            try:
                record = await self._queue.reserve(timeout=self._poll_interval)
            except Exception as exc:  # pragma: no cover - defensive guard
                await asyncio.sleep(self._poll_interval)
                continue

            if record is None:
                await asyncio.sleep(self._poll_interval)
                continue

            handler = self._handlers.get(record.name)
            if handler is None:
                await self._queue.fail(
                    record.job_id,
                    JobFailure(
                        job_id=record.job_id,
                        error_type="MissingHandler",
                        message=f"No handler registered for job '{record.name}'",
                        retryable=False,
                        occurred_at=datetime.now(UTC),
                    ),
                )
                continue

            try:
                detail = await handler(record) or {}
                await self._queue.complete(record.job_id, detail)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - handler errors
                await self._queue.fail(
                    record.job_id,
                    JobFailure(
                        job_id=record.job_id,
                        error_type=exc.__class__.__name__,
                        message=str(exc),
                        retryable=True,
                        detail={"job_name": record.name},
                        occurred_at=datetime.now(UTC),
                    ),
                )


__all__ = [
    "AsyncJobRunner",
    "JobHandler",
    "JobQueue",
    "JobQueueError",
    "JobQueueStats",
]
