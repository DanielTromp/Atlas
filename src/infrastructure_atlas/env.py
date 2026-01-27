from __future__ import annotations

import os
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from infrastructure_atlas.infrastructure.security import sync_secure_settings


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

    Note: Database-stored settings are loaded FIRST so they take precedence
    over .env file values. This allows users to override defaults via the UI.
    """
    root = project_root()
    found = find_dotenv(filename=".env", usecwd=False) if not dotenv_path else None
    env_path = Path(dotenv_path) if dotenv_path else (Path(found) if found else None)
    # Fallback to root/.env if find_dotenv returned empty or a directory
    if not env_path or str(env_path) == "." or env_path.is_dir():
        env_path = root / ".env"
    # Load database-stored settings FIRST (user overrides via UI)
    sync_secure_settings()
    # Then load .env file (override=False means it won't overwrite existing vars)
    load_dotenv(dotenv_path=str(env_path), override=override)
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
