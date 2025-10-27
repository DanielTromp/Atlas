"""In-memory asyncio-backed job queue for development and testing."""
from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from infrastructure_atlas.application.orchestration.queue import JobQueue, JobQueueStats
from infrastructure_atlas.domain.tasks import JobFailure, JobRecord, JobResult, JobSpec, JobStatus, JSONValue


class InMemoryJobQueue(JobQueue):
    """Simple queue that keeps state in-process using ``asyncio`` primitives."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._jobs: dict[str, JobRecord] = {}
        self._failures: dict[str, list[JobFailure]] = defaultdict(list)
        self._inflight: set[str] = set()
        self._lock = asyncio.Lock()
        self._scheduled_tasks: dict[str, asyncio.Task[None]] = {}

    async def enqueue(self, spec: JobSpec) -> JobRecord:
        job_id = uuid.uuid4().hex
        record = JobRecord(
            job_id=job_id,
            name=spec.name,
            status=JobStatus.PENDING,
            payload=spec.payload,
            run_at=spec.run_at,
            priority=spec.priority,
            tags=spec.tags,
        )
        async with self._lock:
            self._jobs[job_id] = record

        if spec.run_at and spec.run_at > datetime.now(UTC):
            delay = (spec.run_at - datetime.now(UTC)).total_seconds()
            self._scheduled_tasks[job_id] = asyncio.create_task(self._delayed_put(job_id, max(delay, 0)))
        else:
            await self._queue.put(job_id)
        return record

    async def reserve(self, *, timeout: float | None = None) -> JobRecord | None:
        try:
            job_id = await asyncio.wait_for(self._queue.get(), timeout=timeout) if timeout else await self._queue.get()
        except TimeoutError:
            return None

        async with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                self._queue.task_done()
                return None
            record.status = JobStatus.RUNNING
            record.started_at = datetime.now(UTC)
            record.attempts += 1
            self._inflight.add(job_id)
        return record

    async def complete(self, job_id: str, detail: Mapping[str, JSONValue] | None = None) -> JobResult:
        async with self._lock:
            record = self._jobs[job_id]
            record.status = JobStatus.COMPLETED
            record.finished_at = datetime.now(UTC)
            self._failures.pop(job_id, None)
            if job_id in self._inflight:
                self._inflight.remove(job_id)
                self._queue.task_done()
        return JobResult(job_id=job_id, status=JobStatus.COMPLETED, detail=dict(detail or {}))

    async def fail(self, job_id: str, failure: JobFailure) -> JobFailure:
        async with self._lock:
            record = self._jobs[job_id]
            record.finished_at = datetime.now(UTC)
            self._failures[job_id].append(failure)
            if job_id in self._inflight:
                self._inflight.remove(job_id)
                self._queue.task_done()

            if failure.retryable:
                record.status = JobStatus.PENDING
                record.started_at = None
                record.finished_at = None
                await self._queue.put(job_id)
            else:
                record.status = JobStatus.FAILED
        return failure

    async def heartbeat(self, job_id: str) -> None:
        async with self._lock:
            record = self._jobs.get(job_id)
            if record and record.status == JobStatus.RUNNING:
                record.started_at = datetime.now(UTC)

    async def stats(self) -> JobQueueStats:
        async with self._lock:
            values = list(self._jobs.values())
        return JobQueueStats(
            queued=sum(1 for job in values if job.status == JobStatus.PENDING),
            running=sum(1 for job in values if job.status == JobStatus.RUNNING),
            completed=sum(1 for job in values if job.status == JobStatus.COMPLETED),
            failed=sum(1 for job in values if job.status == JobStatus.FAILED),
        )

    async def list_jobs(
        self,
        *,
        limit: int = 100,
        statuses: Sequence[JobStatus] | None = None,
    ) -> Sequence[JobRecord]:
        async with self._lock:
            jobs = list(self._jobs.values())
        if statuses is not None:
            wanted = set(statuses)
            jobs = [job for job in jobs if job.status in wanted]
        jobs.sort(key=lambda job: (job.status != JobStatus.RUNNING, job.queued_at))
        return jobs[:limit]

    async def get_job(self, job_id: str) -> JobRecord | None:
        async with self._lock:
            job = self._jobs.get(job_id)
        return job

    async def _delayed_put(self, job_id: str, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
            await self._queue.put(job_id)
        finally:
            self._scheduled_tasks.pop(job_id, None)


__all__ = ["InMemoryJobQueue"]
