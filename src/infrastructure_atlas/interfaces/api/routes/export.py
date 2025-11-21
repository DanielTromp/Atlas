"""Export streaming API routes."""

from __future__ import annotations

import asyncio
import shutil
import sys
from typing import TYPE_CHECKING, Literal

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from infrastructure_atlas.env import project_root
from infrastructure_atlas.infrastructure.logging import get_logger

if TYPE_CHECKING:
    from infrastructure_atlas.domain.entities import User

logger = get_logger(__name__)

router = APIRouter(prefix="/export", tags=["export"])


# Import helpers from app.py
from infrastructure_atlas.api.app import (
    OptionalUserDep,
    _write_log,
    require_permission,
    task_logging,
)


@router.get("/stream")
async def export_stream(
    request: Request,
    dataset: Literal["devices", "vms", "all"] = "devices",
    user: OptionalUserDep = None,
):
    """
    Stream the output of an export run for the given dataset.
    - devices -> uv run atlas export devices
    - vms     -> uv run atlas export vms
    - all     -> uv run atlas export update
    """
    require_permission(request, "export.run")

    args_map = {
        "devices": ["atlas", "export", "devices"],
        "vms": ["atlas", "export", "vms"],
        "all": ["atlas", "export", "update"],
    }
    sub = args_map.get(dataset, args_map["devices"])
    if shutil.which("uv"):
        cmd = ["uv", "run", *sub]
    else:
        # Fallback to Python module invocation if uv isn't available
        cmd = [sys.executable, "-m", "infrastructure_atlas.cli", *sub]

    command_str = " ".join(cmd)
    actor = getattr(user, "username", None)

    async def runner():
        with task_logging(
            "export.stream",
            dataset=dataset,
            command=command_str,
            actor=actor,
        ) as task_log:
            start_cmd = f"$ {command_str}"
            yield start_cmd + "\n"
            _write_log(start_cmd)
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(project_root()),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                if proc.stdout is None:
                    raise RuntimeError("export runner missing stdout pipe")
                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        break
                    try:
                        txt = line.decode(errors="ignore")
                    except Exception:
                        txt = str(line)
                    yield txt
                    _write_log(txt)
            finally:
                rc = await proc.wait()
                exit_line = f"[exit {rc}]"
                yield f"\n{exit_line}\n"
                _write_log(exit_line)
                task_log.add_success(return_code=rc)
                if rc != 0:
                    logger.warning(
                        "Export stream finished with non-zero exit code",
                        extra={
                            "event": "task_warning",
                            "return_code": rc,
                            "dataset": dataset,
                        },
                    )

    return StreamingResponse(runner(), media_type="text/plain")
