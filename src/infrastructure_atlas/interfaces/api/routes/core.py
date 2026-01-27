"""Core API routes (health, configuration, logs, etc.)."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, RedirectResponse

from infrastructure_atlas.env import project_root

router = APIRouter(tags=["core"])


def _data_dir() -> Path:
    """Get the data directory path from environment."""
    root = project_root()
    raw = os.getenv("NETBOX_DATA_DIR", "data")
    path = Path(raw) if os.path.isabs(raw) else (root / raw)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _csv_path(name: str) -> Path:
    """Get path to a file in the data directory."""
    return _data_dir() / name


def _chat_default_temperature() -> float | None:
    """Get default chat temperature from environment."""
    raw = os.getenv("CHAT_DEFAULT_TEMPERATURE", "").strip().lower()
    if raw in {"", "default", "auto"}:
        return None
    try:
        return float(raw)
    except Exception:
        return None


@router.get("/")
def root_redirect():
    """Redirect root to the web UI."""
    return RedirectResponse(url="/app/")


@router.get("/favicon.png")
def favicon_png():
    """Serve favicon from project package location."""
    # Path: interfaces/api/routes/core.py -> need to go up to infrastructure_atlas then into api/static
    # __file__.parent = routes/, .parent.parent = interfaces/, .parent.parent.parent = infrastructure_atlas/
    base = Path(__file__).parent.parent.parent.parent  # -> infrastructure_atlas/
    static_png = base / "api" / "static" / "favicon.png"
    if static_png.exists():
        return FileResponse(static_png, media_type="image/png")
    from fastapi import HTTPException

    raise HTTPException(status_code=404, detail="favicon not found")


@router.get("/health")
def health():
    """Health check endpoint with data directory status."""
    d = _data_dir()
    return {
        "status": "ok",
        "data_dir": str(d),
    }


@router.get("/config/ui")
def ui_config():
    """Get UI configuration (theme, etc.)."""
    theme = os.getenv("UI_THEME_DEFAULT", "nebula").strip() or "nebula"
    return {"theme_default": theme}


@router.get("/config/chat")
def chat_config():
    """Get chat configuration (system prompt, temperature)."""
    return {
        "system_prompt": os.getenv("CHAT_SYSTEM_PROMPT", ""),
        "temperature": _chat_default_temperature(),
    }
