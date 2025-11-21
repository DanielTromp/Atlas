"""Tasks API routes - dataset cache management and refresh."""

from __future__ import annotations

import asyncio
import shlex
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from infrastructure_atlas.env import project_root
from infrastructure_atlas.infrastructure.logging import get_logger, logging_context
from infrastructure_atlas.interfaces.shared.tasks import (
    _append_task_output,
    _build_dataset_command,
    _build_dataset_metadata,
    _collect_task_dataset_definitions,
    _serialize_dataset,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])
logger = get_logger(__name__)


# Helper classes


class _TaskLogger:
    """Helper to track task success metadata."""

    def __init__(self):
        self.success_extra: dict[str, Any] = {}

    def add_success(self, **kwargs: Any) -> None:
        """Add success metadata."""
        self.success_extra.update(kwargs)


# Helper functions


@contextmanager
def task_logging(task: str, **context: Any):
    """Log lifecycle events around long-running UI-triggered tasks."""
    start = time.perf_counter()
    tracker = _TaskLogger()
    safe_context = {k: v for k, v in context.items() if v not in (None, "")}

    with logging_context(task=task, **safe_context):
        logger.info("Task started", extra={"event": "task_started"})
        try:
            yield tracker
        except Exception:
            duration_ms = int((time.perf_counter() - start) * 1000)
            with logging_context(duration_ms=duration_ms, **tracker.success_extra):
                logger.exception("Task failed", extra={"event": "task_failed"})
            raise
        else:
            duration_ms = int((time.perf_counter() - start) * 1000)
            with logging_context(duration_ms=duration_ms, **tracker.success_extra):
                logger.info("Task completed", extra={"event": "task_completed"})


def require_permission(request: Request, permission: str) -> None:
    """Require user to have a specific permission."""
    user = getattr(request.state, "user", None)
    if user is None:
        return
    if getattr(user, "role", "") == "admin":
        return
    permissions = getattr(request.state, "permissions", frozenset())
    if permission not in permissions:
        raise HTTPException(status_code=403, detail="Forbidden: missing permission")


def _write_log(msg: str) -> None:
    """Write to log (for task output)."""
    logger.info(msg)


# API Routes


@router.get("/datasets")
def list_task_datasets(request: Request) -> dict[str, Any]:
    """List all available dataset tasks."""
    require_permission(request, "export.run")
    definitions = _collect_task_dataset_definitions()
    payload = []
    for definition in definitions:
        meta = _build_dataset_metadata(definition)
        command = _build_dataset_command(definition, meta)
        payload.append(_serialize_dataset(definition, meta, command))
    payload.sort(key=lambda item: item["label"])
    return {"datasets": payload, "count": len(payload)}


@router.post("/datasets/{dataset_id}/refresh")
async def refresh_task_dataset(dataset_id: str, request: Request) -> dict[str, Any]:
    """Refresh a specific dataset by running its command."""
    require_permission(request, "export.run")
    definitions = {definition.id: definition for definition in _collect_task_dataset_definitions()}
    definition = definitions.get(dataset_id)
    if definition is None:
        raise HTTPException(status_code=404, detail="Dataset not found")

    meta_before = _build_dataset_metadata(definition)
    command = _build_dataset_command(definition, meta_before)
    if not command:
        raise HTTPException(status_code=400, detail="Dataset cannot be refreshed automatically")
    before_snapshot = _serialize_dataset(definition, meta_before, command)

    actor = getattr(request.state, "user", None)
    actor_name = getattr(actor, "username", None)
    command_display = shlex.join(command)
    started_at = datetime.now(UTC)
    output_lines: list[str] = []

    with task_logging(
        "tasks.refresh",
        dataset=dataset_id,
        command=command_display,
        actor=actor_name,
    ) as task_log:
        start_line = f"$ {command_display}"
        _append_task_output(output_lines, start_line)
        _write_log(start_line)
        proc = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(project_root()),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        rc = 0
        try:
            if proc.stdout is None:
                raise RuntimeError("task runner missing stdout pipe")
            while True:
                chunk = await proc.stdout.readline()
                if not chunk:
                    break
                try:
                    text = chunk.decode(errors="ignore").rstrip("\n")
                except Exception:
                    text = str(chunk)
                _append_task_output(output_lines, text)
                _write_log(text)
        finally:
            rc = await proc.wait()
            exit_line = f"[exit {rc}]"
            _append_task_output(output_lines, exit_line)
            _write_log(exit_line)
            task_log.add_success(return_code=rc)
            if rc != 0:
                logger.warning(
                    "Dataset refresh finished with non-zero exit code",
                    extra={
                        "event": "task_warning",
                        "return_code": rc,
                        "dataset": dataset_id,
                        "command": command_display,
                    },
                )

    completed_at = datetime.now(UTC)
    duration_ms = int((completed_at - started_at).total_seconds() * 1000)
    success = rc == 0

    meta_after = _build_dataset_metadata(definition)
    command_after = _build_dataset_command(definition, meta_after)
    after_snapshot = _serialize_dataset(definition, meta_after, command_after)

    return {
        "dataset": dataset_id,
        "label": definition.label,
        "success": success,
        "return_code": rc,
        "command": command,
        "command_display": command_display,
        "output": output_lines,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "duration_ms": duration_ms,
        "before": before_snapshot,
        "after": after_snapshot,
    }


__all__ = ["router"]
