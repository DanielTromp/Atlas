from __future__ import annotations

import asyncio
import csv
import os
import shutil
import sys
from pathlib import Path
from typing import Literal

import duckdb
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from datetime import datetime

from enreach_tools.env import load_env, project_root

load_env()

app = FastAPI(title="Enreach Tools API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _data_dir() -> Path:
    root = project_root()
    raw = os.getenv("NETBOX_DATA_DIR", "netbox-export/data")
    return Path(raw) if os.path.isabs(raw) else (root / raw)


def _csv_path(name: str) -> Path:
    return _data_dir() / name

# Simple export log file (appends)
LOG_PATH = project_root() / "export.log"


def _write_log(msg: str) -> None:
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(f"[{ts}] {msg.rstrip()}\n")
    except Exception:
        # Logging failures should never crash the API
        pass


def _list_records(
    csv_name: str,
    limit: int | None,
    offset: int,
    order_by: str | None,
    order_dir: Literal["asc", "desc"],
) -> list[dict]:
    path = _csv_path(csv_name)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{csv_name} not found")
    # Read headers to validate order_by
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        headers = next(reader, [])
    if order_by and order_by not in headers:
        raise HTTPException(status_code=400, detail=f"Invalid order_by: {order_by}")

    ident = f'"{order_by}" {order_dir.upper()}' if order_by else None
    base = f"SELECT * FROM read_csv_auto('{path.as_posix()}', header=True)"
    if ident:
        base += f" ORDER BY {ident}"
    if limit is not None:
        base += f" LIMIT {int(limit)} OFFSET {int(offset)}"

    df = duckdb.query(base).df()
    # Normalize to JSON‑safe values: NaN/NaT/±Inf -> None
    if not df.empty:
        df = df.replace([np.inf, -np.inf], np.nan)
        df = df.astype(object).where(pd.notnull(df), None)
    return df.to_dict(orient="records")


@app.get("/health")
def health():
    d = _data_dir()
    dev = _csv_path("netbox_devices_export.csv")
    vms = _csv_path("netbox_vms_export.csv")
    merged = _csv_path("netbox_merged_export.csv")
    return {
        "status": "ok",
        "data_dir": str(d),
        "files": {
            "devices_csv": dev.exists(),
            "vms_csv": vms.exists(),
            "merged_csv": merged.exists(),
        },
    }


@app.get("/column-order")
def column_order() -> list[str]:
    """Return preferred column order based on Systems CMDB.xlsx if available.

    Falls back to merged CSV headers if Excel not found; otherwise empty list.
    """
    try:
        # Prefer the Excel produced by merge step
        xlsx_path = _csv_path("Systems CMDB.xlsx")
        if xlsx_path.exists():
            try:
                from openpyxl import load_workbook

                wb = load_workbook(xlsx_path, read_only=True, data_only=True)
                ws = wb.worksheets[0]
                headers: list[str] = []
                for cell in ws[1]:
                    v = cell.value
                    if v is not None:
                        headers.append(str(v))
                wb.close()
                if headers:
                    return headers
            except Exception:
                pass
        # Fallback to merged CSV header
        csv_path = _csv_path("netbox_merged_export.csv")
        if csv_path.exists():
            with csv_path.open("r", encoding="utf-8") as fh:
                import csv as _csv

                reader = _csv.reader(fh)
                headers = next(reader, [])
                return [str(h) for h in headers if h]
    except Exception:
        pass
    return []


@app.get("/")
def root_redirect():
    # Serve the frontend at /app/
    return RedirectResponse(url="/app/")


# Mount static frontend
_static_dir = Path(__file__).parent / "static"
app.mount("/app", StaticFiles(directory=_static_dir, html=True), name="app")


@app.get("/logs/tail")
def logs_tail(n: int = Query(200, ge=1, le=5000)) -> dict:
    """
    Return the last N lines of the export log.
    Response: { "lines": ["..", ".."] }
    """
    if not LOG_PATH.exists():
        return {"lines": []}
    try:
        with LOG_PATH.open("r", encoding="utf-8", errors="ignore") as fh:
            lines = fh.readlines()[-n:]
        return {"lines": [ln.rstrip("\n") for ln in lines]}
    except Exception:
        return {"lines": []}

@app.get("/export/stream")
async def export_stream(
    dataset: Literal["devices", "vms", "all"] = "devices",
):
    """
    Stream the output of an export run for the given dataset.
    - devices -> uv run netbox export devices
    - vms     -> uv run netbox export vms
    - all     -> uv run netbox export update
    """
    args_map = {
        "devices": ["netbox", "export", "devices"],
        "vms": ["netbox", "export", "vms"],
        "all": ["netbox", "export", "update"],
    }
    sub = args_map.get(dataset, args_map["devices"])
    if shutil.which("uv"):
        cmd = ["uv", "run", *sub]
    else:
        # Fallback to Python module invocation if uv isn't available
        cmd = [sys.executable, "-m", "enreach_tools.cli", *sub]

    async def runner():
        start_cmd = f"$ {' '.join(cmd)}"
        yield start_cmd + "\n"
        _write_log(start_cmd)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(project_root()),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            assert proc.stdout is not None
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

    return StreamingResponse(runner(), media_type="text/plain")


@app.get("/devices")
def devices(
    limit: int | None = Query(None, ge=1, description="Max rows to return (omit for all)"),
    offset: int = Query(0, ge=0),
    order_by: str | None = Query(None, description="Column name to order by"),
    order_dir: Literal["asc", "desc"] = Query("asc"),
):
    return _list_records("netbox_devices_export.csv", limit, offset, order_by, order_dir)


@app.get("/vms")
def vms(
    limit: int | None = Query(None, ge=1, description="Max rows to return (omit for all)"),
    offset: int = Query(0, ge=0),
    order_by: str | None = Query(None, description="Column name to order by"),
    order_dir: Literal["asc", "desc"] = Query("asc"),
):
    return _list_records("netbox_vms_export.csv", limit, offset, order_by, order_dir)

@app.get("/all")
def all_merged(
    limit: int | None = Query(None, ge=1, description="Max rows to return (omit for all)"),
    offset: int = Query(0, ge=0),
    order_by: str | None = Query(None, description="Column name to order by"),
    order_dir: Literal["asc", "desc"] = Query("asc"),
):
    return _list_records("netbox_merged_export.csv", limit, offset, order_by, order_dir)
