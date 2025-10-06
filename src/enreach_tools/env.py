from __future__ import annotations

import os
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from enreach_tools.infrastructure.security import sync_secure_settings


def project_root() -> Path:
    """Return the repo root (directory containing pyproject.toml)."""
    p = Path(__file__).resolve()
    for cand in [p, *list(p.parents)]:
        if (cand / "pyproject.toml").exists():
            return cand
    return Path.cwd()


def load_env(override: bool = False, dotenv_path: Path | None = None) -> Path:
    """Load environment variables from the nearest .env (defaults to repo root).

    - If `dotenv_path` is provided, load that file.
    - Else, search from project root using python-dotenv's find_dotenv.
    Returns the resolved .env path that was loaded (or where it would be).
    """
    root = project_root()
    env_path = Path(dotenv_path) if dotenv_path else Path(find_dotenv(filename=".env", usecwd=False))
    if not env_path or not str(env_path):
        # Fallback to root/.env even if it doesn't exist
        env_path = root / ".env"
    load_dotenv(dotenv_path=str(env_path), override=override)
    sync_secure_settings()
    return env_path


def require_env(keys: list[str]) -> None:
    """Ensure required keys exist; raise ValueError if any missing."""
    missing = [k for k in keys if not os.getenv(k)]
    if missing:
        example = project_root() / ".env.example"
        hint = f" (copy {example} to .env)" if example.exists() else ""
        raise ValueError(f"Missing required env vars: {', '.join(missing)}{hint}")


def get_env(key: str, default: str | None = None, required: bool = False) -> str | None:
    """Get an env var with optional required flag."""
    val = os.getenv(key, default)
    if required and (val is None or val == ""):
        raise ValueError(f"Missing required env var: {key}")
    return val


def apply_extra_headers(session) -> None:
    """Apply optional extra HTTP headers from NETBOX_EXTRA_HEADERS env var to a requests.Session.
    Format: semicolon-separated k=v pairs, e.g. "Header1=abc;Header2=xyz".
    """
    raw = os.getenv("NETBOX_EXTRA_HEADERS", "").strip()
    if not raw:
        return
    for part in raw.split(";"):
        if not part.strip() or "=" not in part:
            continue
        k, v = part.split("=", 1)
        session.headers[str(k).strip()] = str(v).strip()
