"""LangChain tools for export workflows."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime
from typing import Any, ClassVar, Literal

from pydantic.v1 import BaseModel, Field, validator

from enreach_tools.env import load_env, project_root

from .base import EnreachTool, ToolExecutionError

__all__ = ["ExportRunTool", "ExportStatusTool"]


class _ExportRunArgs(BaseModel):
    dataset: Literal["devices", "vms", "all"] = Field(default="all", description="Which export task to run")
    force: bool = Field(default=False, description="Force NetBox refresh before export")
    timeout_seconds: int = Field(default=900, ge=60, le=3600)


class ExportRunTool(EnreachTool):
    name: ClassVar[str] = "export_run_job"
    description: ClassVar[str] = "Trigger the NetBox export pipeline via the CLI and return a log summary."
    args_schema: ClassVar[type[_ExportRunArgs]] = _ExportRunArgs

    def _run(self, **kwargs: Any) -> str:
        args = self.args_schema(**kwargs)
        load_env()
        cmd = self._build_command(args.dataset, args.force)
        try:
            result = subprocess.run(
                cmd,
                check=False, cwd=str(project_root()),
                capture_output=True,
                text=True,
                timeout=int(args.timeout_seconds),
            )
        except subprocess.TimeoutExpired as exc:
            raise ToolExecutionError(f"Export command timed out after {args.timeout_seconds}s") from exc
        except FileNotFoundError as exc:  # pragma: no cover - depends on runtime env
            raise ToolExecutionError(f"Executable not found: {exc}") from exc
        payload = {
            "command": " ".join(cmd),
            "returncode": result.returncode,
            "stdout": (result.stdout or "").strip(),
            "stderr": (result.stderr or "").strip(),
        }
        return json.dumps(payload)

    def _build_command(self, dataset: str, force: bool) -> list[str]:
        args_map = {
            "devices": ["enreach", "export", "devices"],
            "vms": ["enreach", "export", "vms"],
            "all": ["enreach", "export", "update"],
        }
        subcommand = args_map.get(dataset, args_map["all"])
        if shutil.which("uv"):
            cmd = ["uv", "run", *subcommand]
        else:
            cmd = [os.getenv("PYTHON", "python"), "-m", "enreach_tools.cli", *subcommand]
        if force and "--force" not in cmd:
            cmd.append("--force")
        return cmd


class _ExportStatusArgs(BaseModel):
    limit: int = Field(default=10, description="Limit number of files reported (1-50)")

    @validator("limit")
    def _validate_limit(cls, value: int) -> int:
        ivalue = int(value)
        if not 1 <= ivalue <= 50:
            raise ValueError("limit must be between 1 and 50")
        return ivalue


class ExportStatusTool(EnreachTool):
    name: ClassVar[str] = "export_status_overview"
    description: ClassVar[str] = "Summarise the latest export artefacts from the data directory."
    args_schema: ClassVar[type[_ExportStatusArgs]] = _ExportStatusArgs

    def _run(self, **kwargs: Any) -> str:
        args = self.args_schema(**kwargs)
        data_dir = project_root() / "data"
        if not data_dir.exists():
            raise ToolExecutionError(f"Data directory not found: {data_dir}")
        files = sorted(
            (p for p in data_dir.glob("netbox_*")),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        rows: list[dict[str, Any]] = []
        for path in files[: args.limit]:
            stat = path.stat()
            rows.append(
                {
                    "name": path.name,
                    "size_bytes": stat.st_size,
                    "modified_ts": int(stat.st_mtime),
                    "modified_ams": self.format_ams_timestamp(datetime.fromtimestamp(stat.st_mtime)),
                }
            )
        payload = {"files": rows, "count": len(rows), "directory": str(data_dir)}
        return json.dumps(payload)
