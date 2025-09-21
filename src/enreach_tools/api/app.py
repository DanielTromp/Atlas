from __future__ import annotations

import asyncio
import csv
import json
import os
import re
import secrets
import shutil
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Annotated, Any, Literal

import duckdb
import numpy as np
import pandas as pd
import requests
from dotenv import dotenv_values
from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from enreach_tools import backup_sync
from enreach_tools.application.dto import (
    AdminEnvResponseDTO,
    BackupInfoDTO,
    EnvSettingDTO,
    SuggestionCommentDTO,
    SuggestionCommentResponseDTO,
    SuggestionItemDTO,
    SuggestionListDTO,
    meta_to_dto,
    suggestion_to_dto,
    suggestions_to_dto,
)
from enreach_tools.application.security import hash_password, verify_password
from enreach_tools.db import get_sessionmaker, init_database
from enreach_tools.db.models import ChatMessage, ChatSession, GlobalAPIKey, User, UserAPIKey
from enreach_tools.env import load_env, project_root
from enreach_tools.interfaces.api import bootstrap_api
from enreach_tools.interfaces.api.dependencies import (
    CurrentUserDep,
    DbSessionDep,
    OptionalUserDep,
)

try:
    from openai import OpenAI  # type: ignore
except Exception:  # optional dependency
    OpenAI = None  # type: ignore

load_env()

# Ensure the application database is migrated to the latest revision so
# authentication state can be loaded lazily by request handlers.
try:
    init_database()
except Exception as exc:  # pragma: no cover - surfaces during boot
    print(f"[WARN] Failed to initialise database: {exc}")
    raise

SessionLocal = get_sessionmaker()


def ensure_default_admin() -> None:
    with SessionLocal() as db:
        existing = db.execute(select(User.id).limit(1)).scalar_one_or_none()
        if existing:
            return

        username = os.getenv("ENREACH_DEFAULT_ADMIN_USERNAME", "admin").strip().lower() or "admin"
        seed_password = os.getenv("ENREACH_DEFAULT_ADMIN_PASSWORD", "").strip() or UI_PASSWORD

        if not seed_password:
            print(
                "[WARN] No users exist and ENREACH_DEFAULT_ADMIN_PASSWORD is not set; "
                "set it (or ENREACH_UI_PASSWORD) to bootstrap the first login."
            )
            return

        user = User(
            username=username,
            display_name="Administrator",
            role="admin",
            password_hash=hash_password(seed_password),
            is_active=True,
        )
        db.add(user)
        db.commit()
        print(f"[INFO] Created default admin user '{username}'. Please change the password after login.")


ensure_default_admin()


def get_user_by_username(db: Session, username: str) -> User | None:
    uname = (username or "").strip().lower()
    if not uname:
        return None
    stmt = select(User).where(User.username == uname)
    return db.execute(stmt).scalar_one_or_none()


def authenticate_user(db: Session, username: str, password: str) -> User | None:
    user = get_user_by_username(db, username)
    if not user or not user.is_active:
        return None
    if verify_password(password, user.password_hash):
        return user
    return None


def _ensure_admin(user: User) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def _iso(dt: datetime | None) -> str | None:
    if not dt:
        return None
    if isinstance(dt, datetime):
        return dt.isoformat()
    try:
        return str(dt)
    except Exception:
        return None


def _serialize_user(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "created_at": _iso(user.created_at),
        "updated_at": _iso(user.updated_at),
    }


def _serialize_user_api_key(record: UserAPIKey) -> dict[str, Any]:
    return {
        "id": record.id,
        "provider": record.provider,
        "label": record.label,
        "created_at": _iso(record.created_at),
        "updated_at": _iso(record.updated_at),
    }


def _serialize_global_api_key(record: GlobalAPIKey) -> dict[str, Any]:
    return {
        "id": record.id,
        "provider": record.provider,
        "label": record.label,
        "created_at": _iso(record.created_at),
        "updated_at": _iso(record.updated_at),
    }


def _get_user_api_key(db: Session, user_id: str, provider: str) -> UserAPIKey | None:
    stmt = select(UserAPIKey).where(
        UserAPIKey.user_id == user_id,
        UserAPIKey.provider == provider,
    )
    return db.execute(stmt).scalar_one_or_none()


def _get_global_api_key(db: Session, provider: str) -> GlobalAPIKey | None:
    stmt = select(GlobalAPIKey).where(GlobalAPIKey.provider == provider)
    return db.execute(stmt).scalar_one_or_none()


app = FastAPI(title="Enreach Tools API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(bootstrap_api())


# Reduce aggressive caching for the static UI during development to avoid stale assets
@app.middleware("http")
async def no_cache_static(request, call_next):
    response = await call_next(request)
    try:
        path = request.url.path
        if path.startswith("/app"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
    except Exception:
        pass
    return response


# ---------------------------
# Auth configuration
# ---------------------------

API_TOKEN = os.getenv("ENREACH_API_TOKEN", "").strip()
UI_PASSWORD = os.getenv("ENREACH_UI_PASSWORD", "").strip()  # legacy fallback
UI_SECRET = os.getenv("ENREACH_UI_SECRET", "").strip() or secrets.token_hex(32)
SESSION_COOKIE_NAME = "enreach_ui"
SESSION_USER_KEY = "user_id"

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path or "/"

        request.state.user = None
        user_id = request.session.get(SESSION_USER_KEY) if hasattr(request, "session") else None
        if user_id:
            with SessionLocal() as db:
                user = db.get(User, user_id)
                if user and user.is_active:
                    request.state.user = user
                else:
                    request.session.pop(SESSION_USER_KEY, None)
                    request.state.user = None

        # Public endpoints
        if path in ("/favicon.ico", "/health"):
            return await call_next(request)

        if path == "/":
            if not _has_ui_session(request):
                return RedirectResponse(url="/auth/login")
            return await call_next(request)
        if path.startswith("/app"):
            if not _has_ui_session(request):
                next_url = path
                if request.url.query:
                    next_url += f"?{request.url.query}"
                return RedirectResponse(url=f"/auth/login?next={next_url}")
            return await call_next(request)

        # Auth endpoints are always allowed
        if path.startswith("/auth/"):
            return await call_next(request)

        # API protection via Bearer token; allow UI session as alternative
        if API_TOKEN and _is_api_path(path):
            if _has_bearer_token(request) or _has_ui_session(request):
                return await call_next(request)
            # Unauthorized
            return JSONResponse({"detail": "Unauthorized"}, status_code=401, headers={"WWW-Authenticate": "Bearer"})

        return await call_next(request)


def _has_bearer_token(request: Request) -> bool:
    if not API_TOKEN:
        return False
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        return False
    token = auth[7:].strip()
    return secrets.compare_digest(token, API_TOKEN)


def _has_ui_session(request: Request) -> bool:
    try:
        return bool(request.session.get(SESSION_USER_KEY))
    except Exception:
        return False


def _is_api_path(path: str) -> bool:
    # Treat everything except static/frontend and auth endpoints as API
    if path.startswith("/app") or path.startswith("/auth"):
        return False
    if path in ("/", "/favicon.ico"):
        return False
    return True


app.add_middleware(AuthMiddleware)

# Session support for UI auth (cookie-based). Added AFTER AuthMiddleware so
# that Session is applied first (outermost), making request.session available.
app.add_middleware(
    SessionMiddleware,
    secret_key=UI_SECRET,
    session_cookie=SESSION_COOKIE_NAME,
    same_site="lax",
)


def _login_html(next_url: str, error: str | None = None) -> HTMLResponse:
    err_html = f"<div class=\"error\">{error}</div>" if error else ""
    logo_svg = ""
    try:
        raw_logo = (Path(__file__).parent / "static" / "enreach.svg").read_text(encoding="utf-8")
        start = raw_logo.find("<svg")
        if start != -1:
            logo_svg = raw_logo[start:]
        else:
            logo_svg = raw_logo
    except OSError:
        logo_svg = ""
    logo_html = logo_svg or "<span class=\"brand-logo__fallback\">Enreach</span>"
    return HTMLResponse(
        f"""
        <!doctype html>
        <html><head>
        <meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
        <title>Login — Enreach Tools</title>
        <style>
        * {{ box-sizing: border-box; }}
        body {{ font-family: -apple-system, system-ui, Segoe UI, Roboto, Ubuntu, Cantarell, 'Helvetica Neue', Arial, 'Noto Sans', 'Apple Color Emoji', 'Segoe UI Emoji', 'Segoe UI Symbol';
               background: radial-gradient(120% 160% at 50% 0%, rgba(156, 75, 255, 0.28) 0%, rgba(53, 20, 112, 0.68) 40%, #0b0424 75%, #050012 100%);
               color: #f5f3ff; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; padding: 24px; }}
        .box {{ background: rgba(26, 9, 55, 0.86); padding: 32px 30px; border-radius: 16px; width: min(400px, 100%);
                border: 1px solid rgba(155, 100, 255, 0.38); box-shadow: 0 28px 58px rgba(15, 5, 38, 0.55);
                backdrop-filter: blur(12px); display: flex; flex-direction: column; gap: 18px; }}
        .brand {{ display: flex; align-items: center; gap: 12px; }}
        .brand-logo {{ display: flex; align-items: center; justify-content: center; width: 42px; height: 42px; }}
        .brand-logo svg {{ width: 100%; height: auto; filter: brightness(0) invert(1); opacity: 0.92; display: block; }}
        .brand-logo__fallback {{ color: #f5f3ff; font-weight: 700; }}
        .brand h1 {{ font-size: 20px; margin: 0; letter-spacing: 0.28px; font-weight: 680; }}
        label {{ display: block; }}
        input[type=text], input[type=password] {{ width: 100%; padding: 12px 14px; border-radius: 10px; border: 1px solid rgba(170, 111, 255, 0.55);
                               background: rgba(31, 15, 66, 0.94); color: #f5f3ff; font-size: 14px; transition: border-color 160ms ease, box-shadow 160ms ease; }}
        input[type=text]::placeholder, input[type=password]::placeholder {{ color: rgba(212, 198, 255, 0.65); }}
        input[type=text]:focus, input[type=password]:focus {{ outline: none; border-color: #c084fc; box-shadow: 0 0 0 3px rgba(168, 85, 247, 0.45); }}
        button {{ display: block; width: 100%; padding: 12px 14px; border-radius: 10px; border: 1px solid rgba(138, 78, 255, 0.9);
                  background: linear-gradient(180deg, rgba(138, 78, 255, 0.96), rgba(98, 49, 209, 0.92)); color: #f8f5ff;
                  margin-top: 4px; cursor: pointer; font-weight: 600; transition: transform 120ms ease, box-shadow 160ms ease; }}
        button:hover {{ transform: translateY(-1px); box-shadow: 0 18px 46px rgba(98, 58, 178, 0.5); }}
        button:active {{ transform: translateY(0); }}
        .tagline {{ margin: 0; color: #d5ccff; font-size: 13px; }}
        .hint {{ color: #b2a8d9; font-size: 12px; text-align: center; margin-top: 8px; }}
        .error {{ background: rgba(127, 29, 29, 0.85); color: #fecaca; padding: 10px 12px; border-radius: 10px;
                  border: 1px solid rgba(248, 113, 113, 0.65); margin: 4px 0; }}
        </style>
        </head><body>
        <form class=\"box\" method=\"post\" action=\"/auth/login\">
          <div class=\"brand\">
            <div class=\"brand-logo\">{logo_html}</div>
            <h1>Enreach Tools</h1>
          </div>
          <p class=\"tagline\">Sign in to manage NetBox exports and tools.</p>
          {err_html}
          <input type=\"hidden\" name=\"next\" value=\"{next_url}\" />
          <label>
            <input type=\"text\" name=\"username\" placeholder=\"Username\" autofocus required />
          </label>
          <label>
            <input type=\"password\" name=\"password\" placeholder=\"Password\" required />
          </label>
          <button type=\"submit\">Sign in</button>
          <div class=\"hint\">UI access enables API calls from this browser.</div>
        </form>
        </body></html>
        """
    )


@app.get("/auth/login")
def auth_login_form(request: Request, next: str | None = None):
    n = next or "/app/"
    # If already logged in, hop to target
    if _has_ui_session(request):
        return RedirectResponse(url=n)
    return _login_html(n)


@app.post("/auth/login")
async def auth_login(request: Request):
    content_type = request.headers.get("content-type", "").lower()
    is_json = "application/json" in content_type

    if is_json:
        payload = await request.json()
    else:
        payload = await request.form()

    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    next_url = str(payload.get("next") or "/app/")
    if not next_url.startswith("/"):
        next_url = "/app/"

    with SessionLocal() as db:
        user = authenticate_user(db, username, password)
        if user:
            request.session.clear()
            request.session[SESSION_USER_KEY] = user.id
            request.session["username"] = user.username
            if is_json:
                return {"status": "ok", "next": next_url}
            return RedirectResponse(url=next_url, status_code=303)

    if is_json:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return _login_html(next_url, error="Invalid username or password")


@app.get("/auth/logout")
def auth_logout(request: Request):
    try:
        request.session.clear()
    except Exception:
        pass
    return RedirectResponse(url="/auth/login")

















@app.get("/admin/users")


def _data_dir() -> Path:
    root = project_root()
    raw = os.getenv("NETBOX_DATA_DIR", "data")
    path = Path(raw) if os.path.isabs(raw) else (root / raw)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _csv_path(name: str) -> Path:
    return _data_dir() / name

# Simple export log file (appends)
LOG_PATH = project_root() / "export.log"

SUGGESTIONS_FILE = "suggestions.csv"
SUGGESTION_FIELDS = [
    "id",
    "title",
    "summary",
    "classification",
    "status",
    "likes",
    "created_at",
    "updated_at",
    "comments",
]
SUGGESTION_CLASSIFICATIONS = {
    "Must have": {"color": "#7c3aed", "letter": "M"},
    "Should have": {"color": "#2563eb", "letter": "S"},
    "Could have": {"color": "#fbbf24", "letter": "C"},
    "Nice to have": {"color": "#22c55e", "letter": "N"},
    "Should not have": {"color": "#ef4444", "letter": "X"},
}
SUGGESTION_STATUSES = ["new", "accepted", "in progress", "done", "denied"]
_suggestions_lock = Lock()

ENV_SETTING_FIELDS: list[dict[str, Any]] = [
    # Zabbix
    {"key": "ZABBIX_API_URL", "label": "Zabbix API URL", "secret": False, "placeholder": "https://zabbix.example.com/api_jsonrpc.php", "category": "zabbix"},
    {"key": "ZABBIX_HOST", "label": "Zabbix Host", "secret": False, "placeholder": "https://zabbix.example.com", "category": "zabbix"},
    {"key": "ZABBIX_WEB_URL", "label": "Zabbix Web URL", "secret": False, "placeholder": "https://zabbix.example.com", "category": "zabbix"},
    {"key": "ZABBIX_API_TOKEN", "label": "Zabbix API Token", "secret": True, "placeholder": "paste-token-here", "category": "zabbix"},
    {"key": "ZABBIX_SEVERITIES", "label": "Zabbix Severities", "secret": False, "placeholder": "2,3,4", "category": "zabbix"},
    {"key": "ZABBIX_GROUP_ID", "label": "Zabbix Group ID", "secret": False, "placeholder": "optional", "category": "zabbix"},

    # NetBox & Atlassian
    {"key": "NETBOX_URL", "label": "NetBox URL", "secret": False, "placeholder": "https://netbox.example.com", "category": "net-atlassian"},
    {"key": "NETBOX_TOKEN", "label": "NetBox API Token", "secret": True, "placeholder": "paste-token-here", "category": "net-atlassian"},
    {"key": "NETBOX_DEBUG", "label": "NetBox Debug Logging", "secret": False, "placeholder": "0", "category": "net-atlassian"},
    {"key": "NETBOX_EXTRA_HEADERS", "label": "NetBox Extra Headers", "secret": False, "placeholder": "Key=Value;Other=Value", "category": "net-atlassian"},
    {"key": "NETBOX_DATA_DIR", "label": "NetBox Data Directory", "secret": False, "placeholder": "data", "category": "net-atlassian"},
    {"key": "ATLASSIAN_BASE_URL", "label": "Atlassian Base URL", "secret": False, "placeholder": "https://your-domain.atlassian.net", "category": "net-atlassian"},
    {"key": "ATLASSIAN_EMAIL", "label": "Atlassian Email", "secret": False, "placeholder": "user@example.com", "category": "net-atlassian"},
    {"key": "ATLASSIAN_API_TOKEN", "label": "Atlassian API Token", "secret": True, "placeholder": "paste-token-here", "category": "net-atlassian"},
    {"key": "CONFLUENCE_CMDB_PAGE_ID", "label": "Confluence CMDB Page ID", "secret": False, "placeholder": "981533033", "category": "net-atlassian"},
    {"key": "CONFLUENCE_DEVICES_PAGE_ID", "label": "Confluence Devices Page ID", "secret": False, "placeholder": "optional", "category": "net-atlassian"},
    {"key": "CONFLUENCE_VMS_PAGE_ID", "label": "Confluence VMs Page ID", "secret": False, "placeholder": "optional", "category": "net-atlassian"},
    {"key": "CONFLUENCE_ENABLE_TABLE_FILTER", "label": "Enable Table Filter Macro", "secret": False, "placeholder": "0 or 1", "category": "net-atlassian"},
    {"key": "CONFLUENCE_ENABLE_TABLE_SORT", "label": "Enable Table Sort Macro", "secret": False, "placeholder": "0 or 1", "category": "net-atlassian"},

    # Chat providers
    {"key": "OPENAI_API_KEY", "label": "OpenAI API Key", "secret": True, "placeholder": "sk-...", "category": "chat"},
    {"key": "CHAT_DEFAULT_MODEL_OPENAI", "label": "OpenAI Default Model", "secret": False, "placeholder": "gpt-4o-mini", "category": "chat"},
    {"key": "OPENROUTER_API_KEY", "label": "OpenRouter API Key", "secret": True, "placeholder": "or-...", "category": "chat"},
    {"key": "CHAT_DEFAULT_MODEL_OPENROUTER", "label": "OpenRouter Default Model", "secret": False, "placeholder": "openrouter/auto", "category": "chat"},
    {"key": "ANTHROPIC_API_KEY", "label": "Anthropic API Key", "secret": True, "placeholder": "api-key", "category": "chat"},
    {"key": "CHAT_DEFAULT_MODEL_CLAUDE", "label": "Anthropic Default Model", "secret": False, "placeholder": "claude-3-5-sonnet", "category": "chat"},
    {"key": "GOOGLE_API_KEY", "label": "Google (Gemini) API Key", "secret": True, "placeholder": "AIza...", "category": "chat"},
    {"key": "CHAT_DEFAULT_MODEL_GEMINI", "label": "Gemini Default Model", "secret": False, "placeholder": "gemini-1.5-flash", "category": "chat"},
    {"key": "CHAT_DEFAULT_PROVIDER", "label": "Default Chat Provider", "secret": False, "placeholder": "openai", "category": "chat"},
    {"key": "CHAT_DEFAULT_TEMPERATURE", "label": "Default Temperature", "secret": False, "placeholder": "0.2", "category": "chat"},
    {"key": "CHAT_SYSTEM_PROMPT", "label": "System Instructions", "secret": False, "placeholder": "Optional system prompt", "category": "chat"},

    # Export & reporting
    {"key": "NETBOX_XLSX_ORDER_FILE", "label": "Column Order Template", "secret": False, "placeholder": "path/to/column_order.xlsx", "category": "export"},

    # API & Web UI
    {"key": "LOG_LEVEL", "label": "Log Level", "secret": False, "placeholder": "INFO", "category": "api"},
    {"key": "ENREACH_API_TOKEN", "label": "Enreach API Token", "secret": True, "placeholder": "optional", "category": "api"},
    {"key": "ENREACH_UI_PASSWORD", "label": "UI Password", "secret": True, "placeholder": "optional", "category": "api"},
    {"key": "ENREACH_UI_SECRET", "label": "UI Session Secret", "secret": True, "placeholder": "auto-generated if empty", "category": "api"},
    {"key": "ENREACH_SSL_CERTFILE", "label": "SSL Certificate File", "secret": False, "placeholder": "certs/localhost.pem", "category": "api"},
    {"key": "ENREACH_SSL_KEYFILE", "label": "SSL Key File", "secret": False, "placeholder": "certs/localhost-key.pem", "category": "api"},
    {"key": "ENREACH_SSL_KEY_PASSWORD", "label": "SSL Key Password", "secret": True, "placeholder": "optional", "category": "api"},
    {"key": "UI_THEME_DEFAULT", "label": "Default Theme", "secret": False, "placeholder": "nebula", "category": "api"},

    # Backup
    {"key": "BACKUP_ENABLE", "label": "Backup Enabled", "secret": False, "placeholder": "1", "category": "backup"},
    {"key": "BACKUP_TYPE", "label": "Backup Type", "secret": False, "placeholder": "local", "category": "backup"},
    {"key": "BACKUP_HOST", "label": "Backup Host", "secret": False, "placeholder": "backup.example.com", "category": "backup"},
    {"key": "BACKUP_PORT", "label": "Backup Port", "secret": False, "placeholder": "22", "category": "backup"},
    {"key": "BACKUP_USERNAME", "label": "Backup Username", "secret": False, "placeholder": "backup_user", "category": "backup"},
    {"key": "BACKUP_PASSWORD", "label": "Backup Password", "secret": True, "placeholder": "password", "category": "backup"},
    {"key": "BACKUP_PRIVATE_KEY_PATH", "label": "Private Key Path", "secret": False, "placeholder": "~/.ssh/id_rsa", "category": "backup"},
    {"key": "BACKUP_REMOTE_PATH", "label": "Remote Path", "secret": False, "placeholder": "/backups/enreach-tools", "category": "backup"},
    {"key": "BACKUP_LOCAL_PATH", "label": "Local Backup Path", "secret": False, "placeholder": "backups", "category": "backup"},
    {"key": "BACKUP_CREATE_TIMESTAMPED_DIRS", "label": "Create Timestamped Directories", "secret": False, "placeholder": "false", "category": "backup"},
]


def _write_log(msg: str) -> None:
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(f"[{ts}] {msg.rstrip()}\n")
    except Exception:
        # Logging failures should never crash the API
        pass


def _suggestions_path() -> Path:
    path = _csv_path(SUGGESTIONS_FILE)
    if not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=SUGGESTION_FIELDS)
            writer.writeheader()
    return path


def _safe_classification(value: str | None) -> str:
    if not value:
        return "Could have"
    raw = str(value).strip().lower()
    for name in SUGGESTION_CLASSIFICATIONS:
        if raw == name.lower():
            return name
    return "Could have"


def _safe_status(value: str | None) -> str:
    if not value:
        return "new"
    raw = str(value).strip().lower()
    return raw if raw in SUGGESTION_STATUSES else "new"


def _require_classification(value: str | None) -> str:
    if value is None or str(value).strip() == "":
        return "Could have"
    raw = str(value).strip().lower()
    for name in SUGGESTION_CLASSIFICATIONS:
        if raw == name.lower():
            return name
    raise HTTPException(status_code=400, detail=f"Invalid classification: {value}")


def _require_status(value: str | None) -> str:
    if value is None or str(value).strip() == "":
        return "new"
    raw = str(value).strip().lower()
    if raw not in SUGGESTION_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status: {value}")
    return raw


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _decorate_suggestion(item: dict[str, Any]) -> dict[str, Any]:
    data = {**item}
    data["classification"] = _safe_classification(data.get("classification"))
    data["status"] = _safe_status(data.get("status"))
    data.setdefault("summary", "")
    try:
        data["likes"] = int(data.get("likes") or 0)
    except Exception:
        data["likes"] = 0
    comments_raw = data.get("comments") or []
    if isinstance(comments_raw, str):
        try:
            parsed = json.loads(comments_raw)
            comments = [c for c in parsed if isinstance(c, dict)] if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            comments = []
    elif isinstance(comments_raw, list):
        comments = [c for c in comments_raw if isinstance(c, dict)]
    else:
        comments = []
    data["comments"] = comments
    meta = SUGGESTION_CLASSIFICATIONS.get(data["classification"], {})
    data["classification_color"] = meta.get("color")
    data["classification_letter"] = meta.get("letter")
    data["status_label"] = data["status"].title()
    return data


def _load_suggestions() -> list[dict[str, Any]]:
    path = _suggestions_path()
    try:
        sql = f"SELECT * FROM read_csv_auto('{path.as_posix()}', header=True)"
        df = duckdb.query(sql).df()
    except Exception:
        df = pd.DataFrame(columns=SUGGESTION_FIELDS)
    if df.empty:
        return []
    for col in SUGGESTION_FIELDS:
        if col not in df.columns:
            df[col] = None
    df = df.replace([np.inf, -np.inf], np.nan)
    df = df.astype(object).where(pd.notnull(df), None)
    out: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        item = {k: row.get(k) for k in SUGGESTION_FIELDS}
        out.append(_decorate_suggestion(item))
    # Newest first
    def _sort_key(it: dict[str, Any]):
        try:
            raw = str(it.get("created_at") or "")
            if raw.endswith("Z"):
                raw = raw[:-1]
            return datetime.fromisoformat(raw)
        except Exception:
            return datetime.min

    out.sort(key=_sort_key, reverse=True)
    return out


def _write_suggestions(rows: list[dict[str, Any]]) -> None:
    path = _suggestions_path()
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=SUGGESTION_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            payload = row.copy()
            payload["likes"] = int(payload.get("likes") or 0)
            payload["classification"] = _safe_classification(payload.get("classification"))
            payload["status"] = _safe_status(payload.get("status"))
            comments = payload.get("comments") or []
            if not isinstance(comments, list):
                comments = []
            payload["comments"] = json.dumps(comments, ensure_ascii=False)
            writer.writerow(payload)


def _env_file_path() -> Path:
    env_path = load_env()
    if not env_path.exists():
        env_path.touch()
    return env_path


def _read_env_values() -> dict[str, str]:
    env_path = _env_file_path()
    values = dotenv_values(env_path)
    # dotenv_values returns OrderedDict[str, Optional[str]]
    clean: dict[str, str] = {}
    for key, value in values.items():
        if value is None:
            continue
        clean[str(key)] = str(value)
    return clean


def _read_env_defaults() -> dict[str, str]:
    example_path = project_root() / ".env.example"
    if not example_path.exists():
        return {}
    values = dotenv_values(example_path)
    return {str(k): str(v) for k, v in values.items() if v is not None}


def _write_env_value(key: str, value: str | None) -> None:
    key = key.strip()
    env_path = _env_file_path()
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    written = False
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            new_lines.append(line)
            continue
        current_key, _, _ = line.partition("=")
        if current_key.strip() == key:
            if value is None:
                written = True
                continue  # remove line
            new_lines.append(f"{key}={value}")
            written = True
        else:
            new_lines.append(line)
    if not written and value is not None:
        if new_lines and new_lines[-1] != "":
            new_lines.append("")
        new_lines.append(f"{key}={value}")
    env_path.write_text("\n".join(new_lines).rstrip() + "\n")
    load_env(override=True)


def _chat_default_temperature() -> float:
    raw = os.getenv("CHAT_DEFAULT_TEMPERATURE", "0.2").strip()
    try:
        return float(raw)
    except Exception:
        return 0.2


class SuggestionCreate(BaseModel):
    title: str
    summary: str | None = ""
    classification: str | None = None


class SuggestionUpdate(BaseModel):
    title: str | None = None
    summary: str | None = None
    classification: str | None = None
    status: str | None = None


class SuggestionLikeRequest(BaseModel):
    delta: int = 1


class SuggestionCommentCreate(BaseModel):
    text: str


class EnvUpdateRequest(BaseModel):
    key: str
    value: str | None = None


class EnvResetRequest(BaseModel):
    key: str


def _suggestion_meta() -> dict[str, Any]:
    classifications = [
        {
            "name": name,
            "color": meta.get("color"),
            "letter": meta.get("letter"),
        }
        for name, meta in SUGGESTION_CLASSIFICATIONS.items()
    ]
    statuses = [
        {
            "value": value,
            "label": value.title(),
        }
        for value in SUGGESTION_STATUSES
    ]
    return {"classifications": classifications, "statuses": statuses}


@app.get("/suggestions")
def suggestions_list() -> dict:
    with _suggestions_lock:
        items = _load_suggestions()
    meta = meta_to_dto(_suggestion_meta())
    dto = SuggestionListDTO(
        items=suggestions_to_dto(items),
        total=len(items),
        meta=meta,
    )
    return dto.dict_clean()


@app.get("/suggestions/{suggestion_id}")
def suggestions_detail(suggestion_id: str) -> dict:
    with _suggestions_lock:
        items = _load_suggestions()
    for item in items:
        if str(item.get("id")) == suggestion_id:
            meta = meta_to_dto(_suggestion_meta())
            dto = SuggestionItemDTO(
                item=suggestion_to_dto(item),
                meta=meta,
            )
            return dto.dict_clean()
    raise HTTPException(status_code=404, detail="Suggestion not found")


@app.post("/suggestions")
def suggestions_create(req: SuggestionCreate) -> dict:
    title = (req.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title is required")
    summary = (req.summary or "").strip()
    classification = _require_classification(req.classification)
    now = _now_iso()
    item = {
        "id": uuid.uuid4().hex,
        "title": title,
        "summary": summary,
        "classification": classification,
        "status": "new",
        "likes": 0,
        "created_at": now,
        "updated_at": now,
        "comments": [],
    }
    with _suggestions_lock:
        rows = _load_suggestions()
        rows.append(item)
        _write_suggestions(rows)
    decorated = _decorate_suggestion(item)
    dto = SuggestionItemDTO(item=suggestion_to_dto(decorated))
    return dto.dict_clean()


@app.put("/suggestions/{suggestion_id}")
def suggestions_update(suggestion_id: str, req: SuggestionUpdate) -> dict:
    with _suggestions_lock:
        rows = _load_suggestions()
        target = None
        target_index = -1
        for idx, existing in enumerate(rows):
            if str(existing.get("id")) == suggestion_id:
                target = existing
                target_index = idx
                break
        if target is None:
            raise HTTPException(status_code=404, detail="Suggestion not found")

        if req.title is not None:
            new_title = req.title.strip()
            if not new_title:
                raise HTTPException(status_code=400, detail="Title cannot be empty")
            target["title"] = new_title
        if req.summary is not None:
            target["summary"] = req.summary.strip() if req.summary else ""
        if req.classification is not None:
            target["classification"] = _require_classification(req.classification)
        if req.status is not None:
            target["status"] = _require_status(req.status)

        target["updated_at"] = _now_iso()
        rows[target_index] = target
        _write_suggestions(rows)
        saved = _decorate_suggestion(target)

    dto = SuggestionItemDTO(item=suggestion_to_dto(saved))
    return dto.dict_clean()


@app.post("/suggestions/{suggestion_id}/like")
def suggestions_like(suggestion_id: str, req: SuggestionLikeRequest) -> dict:
    delta = req.delta or 1
    with _suggestions_lock:
        rows = _load_suggestions()
        target = None
        target_index = -1
        for idx, existing in enumerate(rows):
            if str(existing.get("id")) == suggestion_id:
                target = existing
                target_index = idx
                break
        if target is None:
            raise HTTPException(status_code=404, detail="Suggestion not found")

        try:
            likes = int(target.get("likes") or 0)
        except Exception:
            likes = 0
        likes = max(0, likes + delta)
        target["likes"] = likes
        target["updated_at"] = _now_iso()
        rows[target_index] = target
        _write_suggestions(rows)
        saved = _decorate_suggestion(target)

    dto = SuggestionItemDTO(item=suggestion_to_dto(saved))
    return dto.dict_clean()


@app.post("/suggestions/{suggestion_id}/comments")
def suggestions_add_comment(suggestion_id: str, req: SuggestionCommentCreate) -> dict:
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Comment text is required")
    with _suggestions_lock:
        rows = _load_suggestions()
        target = None
        target_index = -1
        for idx, existing in enumerate(rows):
            if str(existing.get("id")) == suggestion_id:
                target = existing
                target_index = idx
                break
        if target is None:
            raise HTTPException(status_code=404, detail="Suggestion not found")

        comments = target.get("comments") or []
        if not isinstance(comments, list):
            comments = []
        comment = {
            "id": uuid.uuid4().hex,
            "text": text,
            "created_at": _now_iso(),
        }
        comments.append(comment)
        target["comments"] = comments
        target["updated_at"] = _now_iso()
        rows[target_index] = target
        _write_suggestions(rows)
        saved = _decorate_suggestion(target)

    dto = SuggestionCommentResponseDTO(
        item=suggestion_to_dto(saved),
        comment=SuggestionCommentDTO.model_validate(comment),
    )
    return dto.dict_clean()


@app.delete("/suggestions/{suggestion_id}/comments/{comment_id}")
def suggestions_delete_comment(suggestion_id: str, comment_id: str) -> dict:
    with _suggestions_lock:
        rows = _load_suggestions()
        target = None
        target_index = -1
        for idx, existing in enumerate(rows):
            if str(existing.get("id")) == suggestion_id:
                target = existing
                target_index = idx
                break
        if target is None:
            raise HTTPException(status_code=404, detail="Suggestion not found")

        comments = target.get("comments") or []
        if not isinstance(comments, list):
            comments = []
        new_comments = [c for c in comments if str(c.get("id")) != comment_id]
        if len(new_comments) == len(comments):
            raise HTTPException(status_code=404, detail="Comment not found")
        target["comments"] = new_comments
        target["updated_at"] = _now_iso()
        rows[target_index] = target
        _write_suggestions(rows)
        saved = _decorate_suggestion(target)

    dto = SuggestionItemDTO(item=suggestion_to_dto(saved))
    return dto.dict_clean()


@app.delete("/suggestions/{suggestion_id}")
def suggestions_delete(suggestion_id: str) -> dict:
    with _suggestions_lock:
        rows = _load_suggestions()
        new_rows = [row for row in rows if str(row.get("id")) != suggestion_id]
        if len(new_rows) == len(rows):
            raise HTTPException(status_code=404, detail="Suggestion not found")
        _write_suggestions(new_rows)
    return {"ok": True}


def _build_admin_settings() -> list[dict[str, Any]]:
    env_values = _read_env_values()
    defaults = _read_env_defaults()
    settings: list[dict[str, Any]] = []
    for field in ENV_SETTING_FIELDS:
        key = field["key"]
        secret = bool(field.get("secret"))
        placeholder = field.get("placeholder") or ""
        category = field.get("category") or "general"
        current_value = os.getenv(key, "")
        has_value = bool(current_value)
        value = "" if secret else current_value
        placeholder_effective = placeholder
        if secret and has_value:
            placeholder_effective = "•••••• (hidden)"
        elif not placeholder_effective and not has_value:
            placeholder_effective = defaults.get(key, "")
        settings.append({
            "key": key,
            "label": field.get("label", key),
            "secret": secret,
            "value": value,
            "has_value": has_value,
            "placeholder": placeholder,
            "placeholder_effective": placeholder_effective,
            "source": "file" if key in env_values else "env",
            "default": defaults.get(key, ""),
            "category": category,
        })
    return settings


@app.get("/admin/env")
def admin_env_settings():
    settings = _build_admin_settings()
    backup_enabled = os.getenv("BACKUP_ENABLE", "1").strip().lower() not in {"0", "false", "no", "off"}
    backup_type = os.getenv("BACKUP_TYPE", "local").strip().lower()
    
    # Determine if backup is properly configured based on type
    backup_configured = False
    backup_target = ""
    
    if backup_type == "local":
        backup_path = os.getenv("BACKUP_LOCAL_PATH", "backups").strip()
        backup_configured = bool(backup_path)
        backup_target = backup_path
    elif backup_type in {"sftp", "scp"}:
        host = os.getenv("BACKUP_HOST", "").strip()
        username = os.getenv("BACKUP_USERNAME", "").strip()
        password = os.getenv("BACKUP_PASSWORD", "").strip()
        private_key = os.getenv("BACKUP_PRIVATE_KEY_PATH", "").strip()
        remote_path = os.getenv("BACKUP_REMOTE_PATH", "").strip()
        
        backup_configured = bool(host and username and (password or private_key))
        backup_target = f"{username}@{host}:{remote_path}" if host and username and remote_path else f"{username}@{host}" if host and username else ""
    
    settings_dto = [EnvSettingDTO.model_validate(setting) for setting in settings]
    backup_dto = BackupInfoDTO(
        enabled=backup_enabled,
        configured=backup_configured,
        type=backup_type,
        target=backup_target or None,
    )
    dto = AdminEnvResponseDTO(settings=settings_dto, backup=backup_dto)
    return dto.dict_clean()


@app.post("/admin/env")
def admin_env_update(req: EnvUpdateRequest):
    key = req.key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="Key is required")
    field = next((f for f in ENV_SETTING_FIELDS if f["key"] == key), None)
    if field is None:
        raise HTTPException(status_code=404, detail="Unknown setting")
    if req.value is None:
        return admin_env_settings()
    _write_env_value(key, req.value)
    return admin_env_settings()


@app.post("/admin/env/reset")
def admin_env_reset(req: EnvResetRequest):
    key = req.key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="Key is required")
    field = next((f for f in ENV_SETTING_FIELDS if f["key"] == key), None)
    if field is None:
        raise HTTPException(status_code=404, detail="Unknown setting")
    _write_env_value(key, None)
    return admin_env_settings()


@app.post("/admin/backup-sync")
def admin_backup_sync():
    try:
        result = backup_sync.sync_data_dir(note="manual-ui")
        return result
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/config/ui")
def ui_config():
    theme = os.getenv("UI_THEME_DEFAULT", "nebula").strip() or "nebula"
    return {"theme_default": theme}


@app.get("/config/chat")
def chat_config():
    return {
        "system_prompt": os.getenv("CHAT_SYSTEM_PROMPT", ""),
        "temperature": _chat_default_temperature(),
    }


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


# ---------------------------
# Chat integration (simple)
# ---------------------------

# Chat sessions are now stored in the database
CHAT_QUERY_STOP_WORDS: set[str] = {
    "show",
    "list",
    "give",
    "get",
    "display",
    "please",
    "provide",
    "tell",
    "which",
    "what",
    "where",
    "find",
    "return",
    "me",
    "the",
    "latest",
    "recent",
    "top",
    "all",
    "any",
    "about",
    "for",
    "with",
    "those",
    "these",
    "new",
    "first",
    "last",
    "server",
    "servers",
    "device",
    "devices",
    "data",
    "information",
}


def _chat_env(*, db: Session | None = None, user: User | None = None) -> dict[str, Any]:
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        env = {
            "openai": {
                "api_key": os.getenv("OPENAI_API_KEY", "").strip(),
                "default_model": os.getenv("CHAT_DEFAULT_MODEL_OPENAI", "gpt-5-mini"),
                "key_source": "env",
            },
            "openrouter": {
                "api_key": os.getenv("OPENROUTER_API_KEY", "").strip(),
                "default_model": os.getenv("CHAT_DEFAULT_MODEL_OPENROUTER", "openrouter/auto"),
                "key_source": "env",
            },
            "claude": {
                "api_key": os.getenv("ANTHROPIC_API_KEY", "").strip(),
                "default_model": os.getenv("CHAT_DEFAULT_MODEL_CLAUDE", "claude-3-5-sonnet-20240620"),
                "key_source": "env",
            },
            "gemini": {
                "api_key": os.getenv("GOOGLE_API_KEY", "").strip(),
                "default_model": os.getenv("CHAT_DEFAULT_MODEL_GEMINI", "gemini-1.5-flash"),
                "key_source": "env",
            },
            "default_provider": os.getenv("CHAT_DEFAULT_PROVIDER", "openai"),
        }

        for provider_id in ("openai", "openrouter", "claude", "gemini"):
            override_label: str | None = None
            override_secret: str | None = None
            if user:
                user_key = _get_user_api_key(db, user.id, provider_id)
                if user_key and user_key.secret:
                    override_secret = user_key.secret
                    override_label = user_key.label
                    env[provider_id]["key_source"] = "user"
            if not override_secret:
                global_key = _get_global_api_key(db, provider_id)
                if global_key and global_key.secret:
                    override_secret = global_key.secret
                    override_label = global_key.label or override_label
                    env[provider_id]["key_source"] = "global"
            if override_secret:
                env[provider_id]["api_key"] = override_secret
                if override_label:
                    env[provider_id]["label"] = override_label
            elif env[provider_id]["api_key"]:
                env[provider_id]["key_source"] = "env"
            else:
                env[provider_id]["key_source"] = None

        return env
    finally:
        if close_db:
            db.close()


def _format_responses_messages(messages: list[dict[str, str]]) -> list[dict[str, Any]]:
    formatted: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role", "user")
        text = str(msg.get("content", ""))
        # OpenAI Responses API requires input_text for prompts and output_text for responses
        content_type = "output_text" if role == "assistant" else "input_text"
        formatted.append({
            "role": role,
            "content": [{"type": content_type, "text": text}],
        })
    return formatted


def _get_chat_session(db: Session, session_id: str) -> ChatSession | None:
    """Get chat session by session_id."""
    from sqlalchemy import select
    stmt = select(ChatSession).where(ChatSession.session_id == session_id)
    return db.execute(stmt).scalar_one_or_none()


def _create_chat_session(db: Session, session_id: str | None = None, title: str | None = None, user_id: str | None = None) -> ChatSession:
    """Create a new chat session."""
    if not session_id:
        session_id = "c_" + secrets.token_hex(8)
    
    session = ChatSession(
        session_id=session_id,
        title=title or "New chat",
        user_id=user_id,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def _update_session_title_from_message(db: Session, session: ChatSession, message: str) -> None:
    """Update session title based on first user message if title is still default."""
    if session.title in ("New chat", "", None) and message.strip():
        session.title = message.strip()[:60]
        db.add(session)
        db.commit()


def _add_chat_message(db: Session, session: ChatSession, role: str, content: str) -> ChatMessage:
    """Add a message to a chat session."""
    message = ChatMessage(
        session_id=session.id,
        role=role,
        content=content,
    )
    db.add(message)
    
    # Update session timestamp
    session.updated_at = datetime.now(UTC)
    db.add(session)
    
    db.commit()
    db.refresh(message)
    return message


def _serialize_chat_session(session: ChatSession) -> dict[str, Any]:
    """Serialize chat session for API response."""
    return {
        "session_id": session.session_id,
        "title": session.title,
        "created_at": session.created_at.isoformat() + "Z",
        "updated_at": session.updated_at.isoformat() + "Z",
    }


def _serialize_chat_message(message: ChatMessage) -> dict[str, Any]:
    """Serialize chat message for API response."""
    return {
        "role": message.role,
        "content": message.content,
        "created_at": message.created_at.isoformat() + "Z",
    }


class ChatRequest(BaseModel):
    provider: Literal["openai", "openrouter", "claude", "gemini"]
    model: str | None = None
    message: str
    session_id: str
    temperature: float | None = None
    system: str | None = None
    include_context: bool | None = False
    dataset: Literal["devices", "vms", "all", "merged"] | None = "merged"


class ChatSessionCreate(BaseModel):
    name: str | None = None




ChatRequestBody = Annotated[ChatRequest, Body(...)]


def _messages_for_provider(messages: list[dict[str, str]], max_turns: int = 16) -> list[dict[str, str]]:
    # Keep last N turns to keep payloads light
    if len(messages) <= max_turns:
        return messages
    # keep the last max_turns messages
    return messages[-max_turns:]


def _use_openai_responses(model: str) -> bool:
    m = (model or "").lower()
    return m.startswith("gpt-5")


def _responses_supports_temperature(model: str) -> bool:
    m = (model or "").lower()
    # Current gpt-5 family rejects 'temperature'; omit when using Responses API
    return not m.startswith("gpt-5")


def _is_openai_streaming_unsupported(ex: Exception) -> bool:
    """Heuristics to detect OpenAI responses error that disallows streaming for the model/org."""
    msg = str(ex).lower()
    if "must be verified to stream" in msg or ("stream" in msg and "unsupported" in msg):
        return True
    # Try to inspect HTTPError JSON payload
    try:
        resp = getattr(ex, "response", None)
        if resp is not None:
            try:
                data = resp.json()
            except Exception:
                data = None
            if isinstance(data, dict):
                err = data.get("error") or {}
                if isinstance(err, dict):
                    if (err.get("param") == "stream" and err.get("code") == "unsupported_value"):
                        return True
                    if isinstance(err.get("message"), str) and "must be verified to stream" in err.get("message", "").lower():
                        return True
    except Exception:
        pass
    return False


def _iter_chunks(text: str, size: int = 128):
    for i in range(0, len(text), size):
        yield text[i : i + size]


def _call_openai(model: str, messages: list[dict[str, str]], api_key: str, temperature: float = 0.2) -> str:
    # Prefer the official SDK when available for reliability
    if OpenAI is not None:
        client = OpenAI(api_key=api_key)
        if _use_openai_responses(model):
            _kwargs: dict[str, Any] = {"model": model, "input": _format_responses_messages(messages)}
            if _responses_supports_temperature(model) and temperature is not None:
                _kwargs["temperature"] = temperature
            resp = client.responses.create(**_kwargs)
            try:
                text = getattr(resp, "output_text", None)
                if text:
                    return str(text).strip()
                # Fallback: collect text parts
                chunks = []
                for item in getattr(resp, "output", []) or []:
                    for part in getattr(item, "content", []) or []:
                        if getattr(part, "type", "") == "output_text":
                            chunks.append(getattr(part, "text", ""))
                return "".join(chunks).strip()
            except Exception:
                return ""
        else:
            resp = client.chat.completions.create(model=model, messages=messages, temperature=temperature)
            try:
                choice = (resp.choices or [None])[0]
                msg = getattr(choice, "message", None)
                return (getattr(msg, "content", "") or "").strip()
            except Exception:
                return ""
    # SDK not available — fall back to HTTP
    if _use_openai_responses(model):
        url = "https://api.openai.com/v1/responses"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {"model": model, "input": _format_responses_messages(messages)}
        if _responses_supports_temperature(model) and temperature is not None:
            payload["temperature"] = temperature
        r = requests.post(url, headers=headers, json=payload, timeout=90)
        r.raise_for_status()
        data = r.json()
        text = (data.get("output_text") or "").strip()
        if text:
            return text
        try:
            outs = data.get("output", [])
            chunks = []
            for item in outs:
                parts = item.get("content", []) if isinstance(item, dict) else []
                for p in parts:
                    if isinstance(p, dict) and p.get("type") == "output_text":
                        chunks.append(p.get("text") or "")
            if chunks:
                return "".join(chunks).strip()
        except Exception:
            pass
        return ""
    else:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        r = requests.post(url, headers=headers, json=payload, timeout=60)
        r.raise_for_status()
        data = r.json()
        return (data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()


def _call_openrouter(model: str, messages: list[dict[str, str]], api_key: str, temperature: float = 0.2) -> str:
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        # Optional but recommended by OpenRouter
        "HTTP-Referer": os.getenv("OPENROUTER_REFERRER", ""),
        "X-Title": os.getenv("OPENROUTER_TITLE", "Enreach Tools"),
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    r = requests.post(url, headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    data = r.json()
    return (data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()


def _call_claude(model: str, messages: list[dict[str, str]], api_key: str, temperature: float = 0.2) -> str:
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    # Anthropic expects messages array without an initial system item; support optional separate system
    sys_prompt = None
    if messages and messages[0]["role"] == "system":
        sys_prompt = messages[0].get("content")
        messages = messages[1:]
    payload = {
        "model": model,
        "max_tokens": 800,
        "messages": messages,
        "temperature": temperature,
    }
    if sys_prompt:
        payload["system"] = sys_prompt
    r = requests.post(url, headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    data = r.json()
    # content is a list of blocks; take first text
    blocks = data.get("content", [])
    if isinstance(blocks, list) and blocks:
        part = blocks[0]
        if isinstance(part, dict) and part.get("type") == "text":
            return (part.get("text") or "").strip()
    # Fallback: try candidates
    return (data.get("output_text") or "").strip()


def _call_gemini(model: str, messages: list[dict[str, str]], api_key: str, temperature: float = 0.2) -> str:
    # Convert to Gemini content format
    def to_parts(msgs: list[dict[str, str]]):
        parts = []
        for m in msgs:
            role = m.get("role", "user")
            text = m.get("content", "")
            if role == "system":
                # prepend system to first user message
                parts.append({"role": "user", "parts": [{"text": f"[SYSTEM]\n{text}"}]})
            elif role == "assistant":
                parts.append({"role": "model", "parts": [{"text": text}]})
            else:
                parts.append({"role": "user", "parts": [{"text": text}]})
        return parts

    base = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": to_parts(messages),
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": 800,
        },
    }
    r = requests.post(base, json=payload, timeout=60)
    r.raise_for_status()
    data = r.json()
    try:
        return (data["candidates"][0]["content"]["parts"][0]["text"] or "").strip()
    except Exception:
        return (data.get("text") or "").strip()


def _csv_for_dataset(dataset: str) -> Path | None:
    target = (dataset or "").strip().lower()
    if target == "devices":
        p = _csv_path("netbox_devices_export.csv")
    elif target == "vms":
        p = _csv_path("netbox_vms_export.csv")
    else:
        # "all" (legacy) and "merged" both map to the merged export
        p = _csv_path("netbox_merged_export.csv")
    return p if p.exists() else None


def _build_data_context(dataset: str, query: str, max_rows: int = 6, max_chars: int = 1800) -> str:
    """Return a compact textual context from CSV based on a keyword query.
    Includes columns and up to N matching rows across all columns (case-insensitive LIKE).
    """
    p = _csv_for_dataset(dataset)
    if not p:
        return ""
    try:
        # Read headers
        import csv as _csv

        with p.open("r", encoding="utf-8", errors="ignore") as fh:
            rdr = _csv.reader(fh)
            headers = next(rdr, [])
        if not headers:
            return ""

        tokens = re.findall(r"[A-Za-z0-9]+", query.lower()) if query else []
        text_keywords: list[str] = []
        numeric_keywords: list[str] = []
        numeric_tokens: list[int] = []
        seen_text: set[str] = set()
        seen_numeric: set[str] = set()
        for token in tokens:
            if not token:
                continue
            if token.isdigit():
                try:
                    numeric_tokens.append(int(token))
                except ValueError:
                    continue
                if len(token) >= 2 and token not in seen_numeric:
                    numeric_keywords.append(token)
                    seen_numeric.add(token)
                continue
            if token in CHAT_QUERY_STOP_WORDS:
                continue
            if len(token) < 3:
                continue
            if token not in seen_text:
                text_keywords.append(token)
                seen_text.add(token)

        keywords = text_keywords if text_keywords else numeric_keywords

        limit = max_rows
        if numeric_tokens:
            limit = max(3, min(max(numeric_tokens), 20))

        where_clauses: list[str] = []
        if keywords:
            for kw in keywords[:5]:
                safe_kw = kw.replace("'", "''")
                ors = [
                    f"lower(CAST(\"{h}\" AS VARCHAR)) LIKE '%{safe_kw}%'"
                    for h in headers
                ]
                where_clauses.append("(" + " OR ".join(ors) + ")")

        base_sql = f"SELECT * FROM read_csv_auto('{p.as_posix()}', header=True)"
        limit_sql = f" LIMIT {int(limit)}"

        def _run(sql: str):
            return duckdb.query(sql + limit_sql).df()

        if where_clauses:
            df = _run(base_sql + " WHERE " + " OR ".join(where_clauses))
        elif query.strip():
            safe = query.replace("'", "''")
            ors = [f"lower(CAST(\"{h}\" AS VARCHAR)) LIKE lower('%{safe}%')" for h in headers]
            df = _run(base_sql + " WHERE " + " OR ".join(ors))
            if df.empty:
                df = _run(base_sql)
        else:
            df = _run(base_sql)
        # Render context text
        parts: list[str] = []
        parts.append(f"Source file: {p.name}")
        parts.append(f"Columns: {', '.join(map(str, headers))}")
        if not df.empty:
            parts.append("Relevant rows:")
            preferred = [
                "Name",
                "Status",
                "Tenant",
                "Site",
                "Location",
                "Rack",
                "Rack Position",
                "Role",
                "Manufacturer",
                "Type",
                "Platform",
                "IP Address",
                "IPv4 Address",
                "IPv6 Address",
                "ID",
                "Serial number",
                "Asset tag",
                "Region",
                "Server Group",
                "Cluster",
                "DTAP state",
                "CPU",
                "VCPUs",
                "Memory",
                "Memory (MB)",
                "Disk",
                "Harddisk",
                "Backup",
            ]
            preferred_lower = [p.lower() for p in preferred]

            def normalise_value(value: Any) -> Any:
                if value is None:
                    return None
                if isinstance(value, pd.Timestamp):
                    return value.isoformat()
                if hasattr(value, "isoformat") and not isinstance(value, (str, int, float, bool)):
                    try:
                        return value.isoformat()
                    except Exception:
                        return str(value)
                if isinstance(value, float) and np.isnan(value):
                    return None
                if isinstance(value, (str, int, float, bool)):
                    return value
                return str(value)

            for idx, (_, row) in enumerate(df.iterrows(), start=1):
                try:
                    obj = {str(k): normalise_value(v) for k, v in row.items()}
                except Exception:
                    obj = {str(k): normalise_value(str(v)) for k, v in row.items()}

                # Filter out empty/null values
                non_empty = {k: v for k, v in obj.items() if v not in (None, "", "null", "None")}
                if not non_empty:
                    continue

                title = non_empty.get("Name") or non_empty.get("Device") or non_empty.get("ID") or f"Row {idx}"
                parts.append(f"- {title}")

                seen: set[str] = set()
                for field in preferred:
                    if field in non_empty:
                        value = non_empty[field]
                        parts.append(f"    - **{field}:** {value}")
                        seen.add(field)
                for field, value in non_empty.items():
                    if field in seen:
                        continue
                    if field.lower() in preferred_lower:
                        continue
                    parts.append(f"    - **{field}:** {value}")
        context = "\n".join(parts)
        if len(context) > max_chars:
            context = context[: max_chars - 20] + "\n…"
        return context
    except Exception:
        return ""


@app.get("/chat/providers")
def chat_providers(user: CurrentUserDep, db: DbSessionDep):
    env = _chat_env(db=db, user=user)
    out = []
    for pid in ["openai", "openrouter", "claude", "gemini"]:
        cfg = env.get(pid, {})
        out.append({
            "id": pid,
            "configured": bool(cfg.get("api_key")),
            "default_model": cfg.get("default_model"),
            "key_source": cfg.get("key_source"),
            "label": cfg.get("label"),
        })
    return {"providers": out, "default_provider": env.get("default_provider", "openai")}


@app.get("/chat/history")
def chat_history(db: DbSessionDep, session_id: str = Query(...)):
    session = _get_chat_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")
    
    messages = [_serialize_chat_message(msg) for msg in session.messages]
    return {
        "session_id": session_id,
        "messages": messages,
    }


@app.get("/chat/sessions")
def chat_sessions(db: DbSessionDep, user: OptionalUserDep, limit: int | None = Query(None, ge=1, le=200)):
    from sqlalchemy import select
    
    stmt = select(ChatSession).order_by(ChatSession.updated_at.desc())
    if user:
        stmt = stmt.where(ChatSession.user_id == user.id)
    if limit:
        stmt = stmt.limit(limit)
    
    sessions = db.execute(stmt).scalars().all()
    return {"sessions": [_serialize_chat_session(session) for session in sessions]}


@app.post("/chat/session")
def chat_session_create(db: DbSessionDep, user: OptionalUserDep, req: ChatSessionCreate = Body(default=None)):
    title = (req.name if req else "") or "New chat"
    session = _create_chat_session(db, title=title, user_id=user.id if user else None)
    return _serialize_chat_session(session)


@app.delete("/chat/session/{session_id}")
def chat_session_delete(session_id: str, db: DbSessionDep, user: OptionalUserDep):
    """Delete a chat session and all its messages."""
    session = _get_chat_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")
    
    # Optional: Only allow users to delete their own sessions
    if user and session.user_id and session.user_id != user.id:
        raise HTTPException(status_code=403, detail="You can only delete your own chat sessions")
    
    # Delete the session (messages will be deleted automatically due to cascade)
    db.delete(session)
    db.commit()
    
    return {"status": "deleted", "session_id": session_id}


@app.post("/chat/complete")
def chat_complete(
    req: ChatRequestBody,
    user: OptionalUserDep,
    db: DbSessionDep,
):
    env = _chat_env(db=db, user=user)
    pid = req.provider
    if pid not in env:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {pid}")
    api_key = env[pid].get("api_key")
    if not api_key:
        raise HTTPException(status_code=400, detail=f"Provider '{pid}' not configured (missing API key)")
    model = (req.model or env[pid].get("default_model") or "").strip()
    if not model:
        raise HTTPException(status_code=400, detail=f"No model specified for provider '{pid}'")

    # Get or create chat session
    session = _get_chat_session(db, req.session_id)
    if not session:
        session = _create_chat_session(db, req.session_id, user_id=user.id if user else None)

    # Build message history from database
    history = [_serialize_chat_message(msg) for msg in session.messages]
    
    # Optional: include a system instruction
    system_prompt = (req.system or os.getenv("CHAT_SYSTEM_PROMPT", "")).strip()
    if system_prompt:
        if history and history[0].get("role") == "system":
            history[0]["content"] = system_prompt[:4000]
        else:
            history.insert(0, {"role": "system", "content": system_prompt[:4000]})
    
    # Optionally include data context
    if req.include_context:
        ctx_text = _build_data_context(req.dataset or "all", req.message)
        if ctx_text:
            history.append({
                "role": "system",
                "content": f"Data context from {req.dataset or 'all'}: \n" + ctx_text,
            })
    
    # Add user message to database
    user_message = str(req.message)[:8000]
    _add_chat_message(db, session, "user", user_message)
    
    # Update session title if it's the first user message
    _update_session_title_from_message(db, session, user_message)
    
    # Add user message to history for API call
    history.append({"role": "user", "content": user_message})
    clipped = _messages_for_provider(history)

    temperature = req.temperature if req.temperature is not None else _chat_default_temperature()

    try:
        if pid == "openai":
            text = _call_openai(model, clipped, api_key, temperature=temperature)
        elif pid == "openrouter":
            text = _call_openrouter(model, clipped, api_key, temperature=temperature)
        elif pid == "claude":
            text = _call_claude(model, clipped, api_key, temperature=temperature)
        elif pid == "gemini":
            text = _call_gemini(model, clipped, api_key, temperature=temperature)
        else:
            raise ValueError(f"Unsupported provider: {pid}")
    except requests.HTTPError as ex:
        # Add error message to database
        err = f"Provider error: {ex.response.status_code if ex.response else ''} {ex!s}"
        _add_chat_message(db, session, "assistant", err)
        return {"session_id": req.session_id, "provider": pid, "model": model, "reply": err}
    except Exception as ex:
        err = f"Error: {ex}"
        _add_chat_message(db, session, "assistant", err)
        return {"session_id": req.session_id, "provider": pid, "model": model, "reply": err}

    # Add assistant reply to database
    _add_chat_message(db, session, "assistant", text)
    return {"session_id": req.session_id, "provider": pid, "model": model, "reply": text}


def _stream_openai_text(model: str, messages: list[dict[str, str]], api_key: str, temperature: float = 0.2):
    # Prefer SDK streaming
    if OpenAI is not None:
        client = OpenAI(api_key=api_key)
        if _use_openai_responses(model):
            try:
                kwargs: dict[str, Any] = {
                    "model": model,
                    "input": _format_responses_messages(messages),
                }
                if _responses_supports_temperature(model) and temperature is not None:
                    kwargs["temperature"] = temperature
                with client.responses.stream(**kwargs) as stream:
                    for event in stream:
                        try:
                            if getattr(event, "type", "") == "response.output_text.delta":
                                delta = getattr(event, "delta", "")
                                if delta:
                                    yield delta
                        except Exception:
                            continue
                    _ = stream.get_final_response()
                return
            except Exception:
                # bubble up to caller; do not fall back to raw HTTP when SDK is present
                raise
        else:
            try:
                gen = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    stream=True,
                )
                for chunk in gen:
                    try:
                        delta = (chunk.choices or [None])[0]
                        if delta and getattr(delta, "delta", None):
                            txt = getattr(delta.delta, "content", None)
                            if txt:
                                yield txt
                    except Exception:
                        continue
                return
            except Exception:
                raise
    # HTTP fallback (SSE parsing)
    if _use_openai_responses(model):
        url = "https://api.openai.com/v1/responses"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        payload = {
            "model": model,
            "input": _format_responses_messages(messages),
            "stream": True,
        }
        if _responses_supports_temperature(model) and temperature is not None:
            payload["temperature"] = temperature
        with requests.post(url, headers=headers, json=payload, stream=True, timeout=300) as r:
            r.raise_for_status()
            for raw in r.iter_lines(decode_unicode=True):
                if not raw:
                    continue
                if isinstance(raw, bytes):
                    try:
                        raw = raw.decode("utf-8", errors="ignore")
                    except Exception:
                        raw = str(raw)
                if not raw.startswith("data:"):
                    continue
                data = raw[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    import json as _json
                    obj = _json.loads(data)
                    if obj.get("type") == "response.output_text.delta":
                        delta = obj.get("delta") or ""
                        if delta:
                            yield delta
                except Exception:
                    continue
    else:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        with requests.post(url, headers=headers, json=payload, stream=True, timeout=300) as r:
            r.raise_for_status()
            for raw in r.iter_lines(decode_unicode=True):
                if not raw:
                    continue
                if isinstance(raw, bytes):
                    try:
                        raw = raw.decode("utf-8", errors="ignore")
                    except Exception:
                        raw = str(raw)
                if not raw.startswith("data:"):
                    continue
                data = raw[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    import json as _json
                    obj = _json.loads(data)
                    delta = obj.get("choices", [{}])[0].get("delta", {}).get("content")
                    if delta:
                        yield delta
                except Exception:
                    continue


def _stream_openrouter_text(model: str, messages: list[dict[str, str]], api_key: str, temperature: float = 0.2):
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "HTTP-Referer": os.getenv("OPENROUTER_REFERRER", ""),
        "X-Title": os.getenv("OPENROUTER_TITLE", "Enreach Tools"),
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
    }
    with requests.post(url, headers=headers, json=payload, stream=True, timeout=300) as r:
        r.raise_for_status()
        for raw in r.iter_lines(decode_unicode=True):
            if not raw:
                continue
            if isinstance(raw, bytes):
                try:
                    raw = raw.decode("utf-8", errors="ignore")
                except Exception:
                    raw = str(raw)
            if not raw.startswith("data:"):
                continue
            data = raw[5:].strip()
            if data == "[DONE]":
                break
            try:
                import json as _json

                obj = _json.loads(data)
                delta = obj.get("choices", [{}])[0].get("delta", {}).get("content")
                if delta:
                    yield delta
            except Exception:
                continue


@app.post("/chat/stream")
def chat_stream(
    req: ChatRequestBody,
    user: OptionalUserDep,
    db: DbSessionDep,
):
    env = _chat_env(db=db, user=user)
    pid = req.provider
    if pid not in env:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {pid}")
    api_key = env[pid].get("api_key")
    if not api_key:
        raise HTTPException(status_code=400, detail=f"Provider '{pid}' not configured (missing API key)")
    model = (req.model or env[pid].get("default_model") or "").strip()
    if not model:
        raise HTTPException(status_code=400, detail=f"No model specified for provider '{pid}'")

    # Get or create chat session
    session = _get_chat_session(db, req.session_id)
    if not session:
        session = _create_chat_session(db, req.session_id, user_id=user.id if user else None)

    # Build message history from database
    history = [_serialize_chat_message(msg) for msg in session.messages]
    
    # Optional: include a system instruction
    system_prompt = (req.system or os.getenv("CHAT_SYSTEM_PROMPT", "")).strip()
    if system_prompt:
        if history and history[0].get("role") == "system":
            history[0]["content"] = system_prompt[:4000]
        else:
            history.insert(0, {"role": "system", "content": system_prompt[:4000]})
    
    # Optionally include data context
    if req.include_context:
        ctx_text = _build_data_context(req.dataset or "all", req.message)
        if ctx_text:
            history.append({"role": "system", "content": f"Data context from {req.dataset or 'all'}:\n" + ctx_text})
    
    # Add user message to database
    user_message = str(req.message)[:8000]
    _add_chat_message(db, session, "user", user_message)
    
    # Update session title if it's the first user message
    _update_session_title_from_message(db, session, user_message)
    
    # Add user message to history for API call
    history.append({"role": "user", "content": user_message})
    clipped = _messages_for_provider(history)
    temperature = req.temperature if req.temperature is not None else _chat_default_temperature()

    def generator():
        full_text = []
        try:
            if pid == "openai":
                try:
                    for chunk in _stream_openai_text(model, clipped, api_key, temperature=temperature):
                        full_text.append(chunk)
                        yield chunk
                except Exception as ex:  # smart fallback when streaming is not allowed
                    if _is_openai_streaming_unsupported(ex):
                        try:
                            text = _call_openai(model, clipped, api_key, temperature=temperature)
                        except Exception as ex2:
                            text = f"[error] {getattr(getattr(ex2, 'response', None), 'status_code', '')} {ex2}"
                        for part in _iter_chunks(text or ""):
                            full_text.append(part)
                            yield part
                    else:
                        msg = f"\n[error] {getattr(getattr(ex, 'response', None), 'status_code', '')} {ex}"
                        full_text.append(msg)
                        yield msg
            elif pid == "openrouter":
                try:
                    for chunk in _stream_openrouter_text(model, clipped, api_key, temperature=temperature):
                        full_text.append(chunk)
                        yield chunk
                except Exception as ex:
                    msg = f"\n[error] {getattr(getattr(ex, 'response', None), 'status_code', '')} {ex}"
                    full_text.append(msg)
                    yield msg
            else:
                if pid == "claude":
                    text = _call_claude(model, clipped, api_key, temperature=temperature)
                elif pid == "gemini":
                    text = _call_gemini(model, clipped, api_key, temperature=temperature)
                else:
                    text = ""
                for i in range(0, len(text), 64):
                    part = text[i : i + 64]
                    full_text.append(part)
                    yield part
        finally:
            # Add assistant response to database
            out = "".join(full_text).strip()
            _add_chat_message(db, session, "assistant", out)

    return StreamingResponse(generator(), media_type="text/plain; charset=utf-8")


# ---------------------------
# Zabbix integration (read-only)
# ---------------------------

def _zbx_base_url() -> str | None:
    raw = os.getenv("ZABBIX_API_URL", "").strip()
    if raw:
        return raw
    host = os.getenv("ZABBIX_HOST", "").strip()
    if host:
        if host.endswith("/api_jsonrpc.php"):
            return host
        return host.rstrip("/") + "/api_jsonrpc.php"
    return None


def _zbx_headers() -> dict[str, str]:
    token = os.getenv("ZABBIX_API_TOKEN", "").strip()
    h = {"Content-Type": "application/json"}
    if token:
        # Send Authorization header for API token auth (Zabbix 5.4+)
        h["Authorization"] = f"Bearer {token}"
    return h


def _zbx_web_base() -> str | None:
    web = os.getenv("ZABBIX_WEB_URL", "").strip()
    if web:
        return web.rstrip("/")
    api = _zbx_base_url()
    if api and api.endswith("/api_jsonrpc.php"):
        return api[: -len("/api_jsonrpc.php")]
    return None


def _zbx_rpc(method: str, params: dict) -> dict:
    url = _zbx_base_url()
    if not url:
        raise HTTPException(status_code=400, detail="ZABBIX_API_URL or ZABBIX_HOST not configured")
    token = os.getenv("ZABBIX_API_TOKEN", "").strip()
    headers = _zbx_headers()
    body = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": 1,
    }
    # Always include 'auth' in body for compatibility (some proxies strip Authorization)
    if token:
        body["auth"] = token
    r = requests.post(url, headers=headers, json=body, timeout=30)
    r.raise_for_status()
    data = r.json()
    if data.get("error"):
        # Map not authorized to 401
        err = data["error"]
        msg = str(err)
        if "Not authorized" in msg or (isinstance(err, dict) and "Not authorized" in str(err.get("data", ""))):
            raise HTTPException(status_code=401, detail=f"Zabbix error: {err}")
        raise HTTPException(status_code=502, detail=f"Zabbix error: {err}")
    return data.get("result", {})


def _zbx_expand_groupids(base_group_ids: list[int]) -> list[int]:
    """Return base_group_ids plus all subgroup IDs by name prefix matching.

    This uses hostgroup.get to fetch all groups and includes those whose name
    starts with any base group name followed by '/'. Works across Zabbix versions
    without relying on wildcard search support.
    """
    try:
        if not base_group_ids:
            return base_group_ids
        groups = _zbx_rpc("hostgroup.get", {"output": ["groupid", "name"], "limit": 10000})
        if not isinstance(groups, list):
            return base_group_ids
        # Map id->name and collect target prefixes
        id_to_name: dict[int, str] = {}
        for g in groups:
            try:
                gid = int(g.get("groupid"))
                nm = str(g.get("name") or "").strip()
                id_to_name[gid] = nm
            except Exception:
                continue
        prefixes = [id_to_name.get(gid, "").strip() for gid in base_group_ids]
        prefixes = [p for p in prefixes if p]
        if not prefixes:
            return base_group_ids
        # Include any group whose name equals the prefix or starts with 'prefix/'
        out: set[int] = set()
        for g in groups:
            try:
                gid = int(g.get("groupid"))
                nm = str(g.get("name") or "").strip()
            except Exception:
                continue
            for p in prefixes:
                if nm == p or nm.startswith(p + "/"):
                    out.add(gid)
                    break
        # Ensure base ids included
        for gid in base_group_ids:
            out.add(int(gid))
        return sorted(out)
    except Exception:
        return base_group_ids


@app.get("/zabbix/problems")
def zabbix_problems(
    severities: str | None = Query(None, description="Comma-separated severities 0..5 (e.g. '2,3,4')"),
    groupids: str | None = Query(None, description="Comma-separated group IDs"),
    hostids: str | None = Query(None, description="Comma-separated host IDs"),
    unacknowledged: int = Query(0, ge=0, le=1),
    suppressed: int = Query(0, ge=0, le=1),
    limit: int = Query(300, ge=1, le=2000),
    include_subgroups: int = Query(0, ge=0, le=1, description="When filtering by groupids, include all subgroup IDs"),
):
    """Return problems from Zabbix using problem.get with basic filters."""
    # Do not hard-fail on missing token here; let downstream return a clear error
    try:
        sev_list = [int(s) for s in (severities.split(",") if severities else []) if str(s).strip() != ""]
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid severities")
    try:
        grp_list = [int(s) for s in (groupids.split(",") if groupids else []) if str(s).strip() != ""]
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid groupids")
    try:
        host_list = [int(s) for s in (hostids.split(",") if hostids else []) if str(s).strip() != ""]
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid hostids")

    # Defaults to match the provided filter when env not set
    if not sev_list:
        env_sev = os.getenv("ZABBIX_SEVERITIES", "2,3,4").strip()
        if env_sev:
            try:
                sev_list = [int(x) for x in env_sev.split(",") if x.strip()]
            except Exception:
                sev_list = [2, 3, 4]
        else:
            sev_list = [2, 3, 4]
    if not grp_list:
        gid = os.getenv("ZABBIX_GROUP_ID", "").strip()
        if gid.isdigit():
            grp_list = [int(gid)]
    # Expand group ids to include all subgroups when requested
    if grp_list and include_subgroups == 1:
        grp_list = _zbx_expand_groupids(grp_list)

    params: dict = {
        "output": [
            "eventid",
            "name",
            "opdata",
            "severity",
            "clock",
            "acknowledged",
            "r_eventid",
            "source",
            "object",
            "objectid",
        ],
        "selectTags": "extend",
        "selectAcknowledges": "extend",
        "selectSuppressionData": "extend",
        # Some Zabbix installations do not allow sorting by 'clock' via API.
        # We'll fetch recent problems and sort by clock server-side.
        "limit": limit,
    }
    if sev_list:
        params["severities"] = sev_list
    if grp_list:
        params["groupids"] = grp_list
    if host_list:
        params["hostids"] = host_list
    # Acknowledged filter: when unacknowledged=1 -> only unacknowledged; when 0 -> no filter (show all)
    if unacknowledged == 1:
        params["acknowledged"] = 0
    if suppressed in (0, 1):
        params["suppressed"] = suppressed

    res = _zbx_rpc("problem.get", params)
    rows = []
    base_web = _zbx_web_base() or ""

    # Build map triggerid -> first host (hostid, name) for richer UI
    trig_ids: list[str] = []
    if isinstance(res, list):
        seen = set()
        for it in res:
            tid = str(it.get("objectid") or "").strip()
            if tid and tid not in seen:
                seen.add(tid)
                trig_ids.append(tid)
    host_by_trigger: dict[str, dict] = {}
    if trig_ids:
        try:
            trigs = _zbx_rpc("trigger.get", {
                "output": ["triggerid"],
                "selectHosts": ["hostid", "name"],
                "triggerids": trig_ids,
            })
            if isinstance(trigs, list):
                for t in trigs:
                    tid = str(t.get("triggerid"))
                    hs = t.get("hosts") or []
                    if isinstance(hs, list) and hs:
                        h = hs[0] or {}
                        host_by_trigger[tid] = {"hostid": h.get("hostid"), "name": h.get("name")}
        except HTTPException:
            pass

    for it in res if isinstance(res, list) else []:
        try:
            clk = int(it.get("clock") or 0)
        except Exception:
            clk = 0
        status = "RESOLVED" if str(it.get("r_eventid", "0")) not in ("0", "", "None", "none") else "PROBLEM"
        # No server-side opdata filtering; GUI-equivalent filters are applied in the client.
        # Prefer trigger->host lookup (more reliable across versions)
        trig_id = str(it.get("objectid") or "")
        host_name = host_by_trigger.get(trig_id, {}).get("name")
        host_id = host_by_trigger.get(trig_id, {}).get("hostid")
        # Fallback to hosts array if present
        if (not host_name or not host_id) and isinstance(it.get("hosts"), list) and it.get("hosts"):
            h0 = (it.get("hosts") or [None])[0] or {}
            host_name = host_name or h0.get("name")
            host_id = host_id or h0.get("hostid")
        host_url = f"{base_web}/zabbix.php?action=host.view&hostid={host_id}" if (base_web and host_id) else None
        problem_url = f"{base_web}/zabbix.php?action=problem.view&eventid={it.get('eventid')}" if base_web and it.get("eventid") else None
        rows.append({
            "eventid": it.get("eventid"),
            "name": it.get("name"),
            "opdata": it.get("opdata"),
            "severity": int(it.get("severity") or 0),
            "acknowledged": int(it.get("acknowledged") or 0),
            "clock": clk,
            "clock_iso": datetime.utcfromtimestamp(clk).strftime("%Y-%m-%d %H:%M:%S") if clk else None,
            "tags": it.get("tags", []),
            "suppressed": int(it.get("suppressed") or 0),
            "status": status,
            "host": host_name,
            "hostid": host_id,
            "host_url": host_url,
            "problem_url": problem_url,
        })
    # Sort by clock DESC server-side to mimic the UI
    rows.sort(key=lambda x: x.get("clock") or 0, reverse=True)
    return {"items": rows, "count": len(rows)}


@app.get("/zabbix/host")
def zabbix_host(hostid: int = Query(..., description="Host ID")):
    """Return extended information about a single host for debugging/analysis."""
    params = {
        "output": "extend",
        "hostids": [hostid],
        "selectInterfaces": "extend",
        "selectGroups": ["groupid", "name"],
        "selectInventory": "extend",
        "selectMacros": "extend",
        "selectTags": "extend",
    }
    res = _zbx_rpc("host.get", params)
    if isinstance(res, list) and res:
        try:
            h = res[0]
            return {"host": h}
        except Exception:
            pass
    raise HTTPException(status_code=404, detail="Host not found")


class ZabbixAckRequest(BaseModel):
    eventids: list[str] | list[int]
    message: str | None = None


@app.post("/zabbix/ack")
def zabbix_ack(req: ZabbixAckRequest):
    """Acknowledge one or more events in Zabbix.

    Uses event.acknowledge with action=6 (acknowledge + message). Requires API token.
    """
    try:
        ids: list[str] = [str(x) for x in (req.eventids or []) if str(x).strip()]
        if not ids:
            raise HTTPException(status_code=400, detail="No event IDs provided")
        params = {
            "eventids": ids,
            "message": (req.message or "Acknowledged via Enreach Tools").strip(),
            "action": 6,
        }
        res = _zbx_rpc("event.acknowledge", params)
        return {"ok": True, "result": res}
    except HTTPException:
        raise
    except Exception as ex:
        raise HTTPException(status_code=500, detail=f"Ack failed: {ex}")


# Serve favicon from project package location (png) as /favicon.ico
@app.get("/favicon.ico")
def favicon_ico():
    # Prefer png present at src/enreach_tools/api/favicon.png
    png_path = Path(__file__).parent / "favicon.png"
    if png_path.exists():
        # Serve PNG under .ico path; browsers accept image/png
        return FileResponse(png_path, media_type="image/png")
    # Else, try static path under /app
    static_png = Path(__file__).parent / "static" / "favicon.png"
    if static_png.exists():
        return FileResponse(static_png, media_type="image/png")
    raise HTTPException(status_code=404, detail="favicon not found")


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
    - devices -> uv run enreach export devices
    - vms     -> uv run enreach export vms
    - all     -> uv run enreach export update
    """
    args_map = {
        "devices": ["enreach", "export", "devices"],
        "vms": ["enreach", "export", "vms"],
        "all": ["enreach", "export", "update"],
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


# ---------------------------
# Home aggregator (Zabbix, Jira, Confluence, NetBox)
# ---------------------------

def _ts_iso(ts: int | str | None) -> str:
    try:
        t = int(ts or 0)
        if t <= 0:
            return ""
        return datetime.utcfromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


@app.get("/home/aggregate")
def home_aggregate(
    q: str = Query(..., description="Object name to search across systems"),
    zlimit: int = Query(10, ge=0, le=500, description="Max Zabbix items per list (0 = no limit)"),
    jlimit: int = Query(10, ge=0, le=200, description="Max Jira issues (0 = no limit, capped upstream)"),
    climit: int = Query(10, ge=0, le=200, description="Max Confluence results (0 = no limit, capped upstream)"),
):
    out: dict[str, Any] = {"q": q}

    # Zabbix: active (problems) and historical (events)
    try:
        hostids: list[int] = []
        try:
            # Fuzzy host search on both 'name' and 'host', allow partial matches and wildcards
            patt = f"*{q}*"
            res = _zbx_rpc(
                "host.get",
                {
                    "output": ["hostid", "host", "name"],
                    "search": {"name": patt, "host": patt},
                    "searchByAny": 1,
                    "searchWildcardsEnabled": 1,
                    "limit": 200,
                },
            )
            for h in (res or []):
                try:
                    hostids.append(int(h.get("hostid")))
                except Exception:
                    pass
            # If q looks like an IP, match host interfaces by IP as well
            import re as _re
            if _re.match(r"^\d{1,3}(?:\.\d{1,3}){3}$", q.strip()):
                try:
                    intfs = _zbx_rpc(
                        "hostinterface.get",
                        {"output": ["interfaceid", "hostid", "ip"], "search": {"ip": q.strip()}, "limit": 200},
                    )
                    for itf in (intfs or []):
                        try:
                            hostids.append(int(itf.get("hostid")))
                        except Exception:
                            pass
                except Exception:
                    pass
            # Deduplicate
            hostids = sorted({i for i in hostids if isinstance(i, int)})
        except Exception:
            hostids = []
        zbx = {"active": [], "historical": []}
        base_web = _zbx_web_base() or ""
        # Active problems (prefer hostids; fallback to name search)
        p_params = {
            "output": ["eventid", "name", "severity", "clock", "acknowledged", "r_eventid"],
            "selectTags": "extend",
            "limit": 200,
        }
        if hostids:
            p_params["hostids"] = hostids
        else:
            p_params["search"] = {"name": f"*{q}*"}
            p_params["searchWildcardsEnabled"] = 1
        # Also request hosts to allow client-side fallback filtering
        p_params["selectHosts"] = ["host", "name", "hostid"]
        p = _zbx_rpc("problem.get", p_params)
        items = []
        try:
            p = sorted(p or [], key=lambda x: int(x.get("clock") or 0), reverse=True)
        except Exception:
            p = p or []
        # Apply limit
        lim = int(zlimit) if int(zlimit) > 0 else len(p)
        for it in p[:lim]:
            items.append(
                {
                    "eventid": it.get("eventid"),
                    "name": it.get("name"),
                    "severity": it.get("severity"),
                    "clock": _ts_iso(it.get("clock")),
                    "acknowledged": it.get("acknowledged"),
                    "resolved": 1 if (str(it.get("r_eventid") or "") not in ("", "0")) else 0,
                    "status": ("ACTIVE" if str(it.get("r_eventid") or "").strip() in ("", "0") else "RESOLVED"),
                    "problem_url": (f"{base_web}/zabbix.php?action=problem.view&eventid={it.get('eventid')}" if base_web and it.get("eventid") else None),
                    "host_url": (f"{base_web}/zabbix.php?action=host.view&hostid={(it.get('hosts') or [{}])[0].get('hostid')}" if base_web and (it.get('hosts') or [{}])[0].get('hostid') else None),
                }
            )
        # Extra fallback: if still empty and we didn't have hostids, try a broader recent scan and filter locally
        if not items and not hostids:
            try:
                alt = _zbx_rpc(
                    "problem.get",
                    {
                        "output": ["eventid", "name", "severity", "clock", "acknowledged", "r_eventid"],
                        "selectHosts": ["host", "name", "hostid"],
                        "limit": 200,
                        "sortfield": ["clock"],
                        "sortorder": "DESC",
                    },
                )
                ql = q.lower().strip()
                for it in (alt or []):
                    host_list = it.get("hosts", []) or []
                    host_match = any(
                        (str(h.get("host") or "") + " " + str(h.get("name") or "")).lower().find(ql) >= 0
                        for h in host_list
                    )
                    if host_match or (str(it.get("name") or "").lower().find(ql) >= 0):
                        items.append(
                            {
                                "eventid": it.get("eventid"),
                                "name": it.get("name"),
                                "severity": it.get("severity"),
                                "clock": _ts_iso(it.get("clock")),
                                "acknowledged": it.get("acknowledged"),
                                "resolved": 1 if (str(it.get("r_eventid") or "") not in ("", "0")) else 0,
                            }
                        )
            except Exception:
                pass
        zbx["active"] = items
        # Historical events (prefer hostids; fallback to name search)
        ev_params = {
            "output": ["eventid", "name", "clock", "value"],
            "selectTags": "extend",
            "source": 0,  # triggers
            "limit": 200,
        }
        if hostids:
            ev_params["hostids"] = hostids
        else:
            ev_params["search"] = {"name": f"*{q}*"}
            ev_params["searchWildcardsEnabled"] = 1
        ev = _zbx_rpc("event.get", ev_params)
        ev_items = []
        try:
            ev = sorted(ev or [], key=lambda x: int(x.get("clock") or 0), reverse=True)
        except Exception:
            ev = ev or []
        limh = int(zlimit) if int(zlimit) > 0 else len(ev)
        for it in ev[:limh]:
            ev_items.append(
                {
                    "eventid": it.get("eventid"),
                    "name": it.get("name"),
                    "clock": _ts_iso(it.get("clock")),
                    "value": it.get("value"),
                    "status": ("PROBLEM" if str(it.get("value") or "").strip() == "1" else "OK"),
                    "event_url": (f"{base_web}/zabbix.php?action=event.view&eventid={it.get('eventid')}" if base_web and it.get("eventid") else None),
                    "host_url": (f"{base_web}/zabbix.php?action=host.view&hostid={(it.get('hosts') or [{}])[0].get('hostid')}" if base_web and (it.get('hosts') or [{}])[0].get('hostid') else None),
                }
            )
        zbx["historical"] = ev_items
        out["zabbix"] = zbx
    except HTTPException as ex:
        out["zabbix"] = {"error": ex.detail}
    except Exception as ex:
        out["zabbix"] = {"error": str(ex)}

    # Jira: tickets containing text (last 365d to be practical)
    try:
        mr = int(jlimit) if int(jlimit) > 0 else 50
        res = jira_search(q=q, jql=None, project=None, status=None, assignee=None, priority=None, issuetype=None, updated="-365d", team=None, only_open=0, max_results=mr)
        out["jira"] = {"total": res.get("total", 0), "issues": res.get("issues", [])}
    except HTTPException as ex:
        out["jira"] = {"error": ex.detail}
    except Exception as ex:
        out["jira"] = {"error": str(ex)}

    # Confluence: pages mentioning the object (last 365d)
    try:
        mc = int(climit) if int(climit) > 0 else 50
        res = confluence_search(q=q, space=None, ctype="page", labels=None, updated="-365d", max_results=mc)
        out["confluence"] = {"total": res.get("total", 0), "results": res.get("results", [])}
    except HTTPException as ex:
        out["confluence"] = {"error": ex.detail}
    except Exception as ex:
        out["confluence"] = {"error": str(ex)}

    # NetBox: objects matching the name; also include IPs when dataset=all
    try:
        # NetBox: no limit by default
        res = netbox_search(dataset="all", q=q, limit=0)
        out["netbox"] = {"total": res.get("total", 0), "items": res.get("rows", [])}
    except HTTPException as ex:
        out["netbox"] = {"error": ex.detail}
    except Exception as ex:
        out["netbox"] = {"error": str(ex)}

    return out


# ---------------------------
# Jira integration (search)
# ---------------------------

def _jira_cfg() -> dict[str, str]:
    """Return Atlassian (Jira) credentials.

    Preferred envs: ATLASSIAN_BASE_URL, ATLASSIAN_EMAIL, ATLASSIAN_API_TOKEN
    Backwards-compatible fallbacks: JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN
    """
    base = os.getenv("ATLASSIAN_BASE_URL", "").strip() or os.getenv("JIRA_BASE_URL", "").strip()
    email = os.getenv("ATLASSIAN_EMAIL", "").strip() or os.getenv("JIRA_EMAIL", "").strip()
    token = os.getenv("ATLASSIAN_API_TOKEN", "").strip() or os.getenv("JIRA_API_TOKEN", "").strip()
    return {"base": base, "email": email, "token": token}


def _jira_configured() -> bool:
    cfg = _jira_cfg()
    return bool(cfg["base"] and cfg["email"] and cfg["token"])


def _jira_session() -> tuple[requests.Session, str]:
    cfg = _jira_cfg()
    if not (cfg["base"] and cfg["email"] and cfg["token"]):
        raise HTTPException(status_code=400, detail="Jira not configured: set ATLASSIAN_BASE_URL, ATLASSIAN_EMAIL, ATLASSIAN_API_TOKEN in .env")
    sess = requests.Session()
    sess.auth = (cfg["email"], cfg["token"])  # Basic auth for Jira Cloud
    sess.headers.update({"Accept": "application/json"})
    base = cfg["base"].rstrip("/")
    return sess, base


def _jira_build_jql(
    q: str | None = None,
    project: str | None = None,
    status: str | None = None,
    assignee: str | None = None,
    priority: str | None = None,
    issuetype: str | None = None,
    updated: str | None = None,
    team: str | None = None,
    only_open: bool = True,
) -> str:
    parts: list[str] = []
    # Only open maps better via statusCategory != Done (workflow agnostic)
    if only_open:
        parts.append('statusCategory != Done')
    if project:
        # Accept both key and name
        p = project.strip()
        if p:
            if any(ch.isspace() for ch in p) or not p.isalnum():
                parts.append(f'project = "{p}"')
            else:
                parts.append(f"project = {p}")
    if status:
        s = status.strip()
        if s:
            # Allow comma separated
            if "," in s:
                vals = ",".join([f'"{v.strip()}"' for v in s.split(",") if v.strip()])
                if vals:
                    parts.append(f"status in ({vals})")
            else:
                parts.append(f'status = "{s}"')
    if assignee:
        a = assignee.strip()
        if a:
            parts.append(f'assignee = "{a}"')
    if priority:
        pr = priority.strip()
        if pr:
            if "," in pr:
                vals = ",".join([f'"{v.strip()}"' for v in pr.split(",") if v.strip()])
                if vals:
                    parts.append(f"priority in ({vals})")
            else:
                parts.append(f'priority = "{pr}"')
    if issuetype:
        it = issuetype.strip()
        if it:
            parts.append(f'issuetype = "{it}"')
    # Custom field: Team (Service Desk) -> cf[10575]
    if team:
        tv = team.strip()
        if tv:
            if "," in tv:
                vals = ",".join([f'"{v.strip()}"' for v in tv.split(",") if v.strip()])
                if vals:
                    parts.append(f"cf[10575] in ({vals})")
            else:
                parts.append(f'cf[10575] = "{tv}"')
    if updated:
        up = updated.strip()
        if up:
            # Accept absolute date (YYYY-MM-DD) or relative (-7d / -4w)
            parts.append(f"updated >= {up}")
    # Jira /search/jql requires bounded queries; if user provided no limiting filters,
    # apply a safe default of last 30 days to avoid 400 errors.
    if not any([project, status, assignee, priority, issuetype, team, (updated and updated.strip()), (q and q.strip())]):
        parts.append("updated >= -30d")
    if q and q.strip():
        # text ~ search across summary, description, comments (Cloud behavior)
        # Escape quotes in q
        qq = q.replace('"', '\\"')
        parts.append(f'text ~ "{qq}"')
    jql = " AND ".join(parts) if parts else "order by updated desc"
    if "order by" not in jql.lower():
        jql += " ORDER BY updated DESC"
    return jql


@app.get("/jira/config")
def jira_config():
    cfg = _jira_cfg()
    return {"configured": _jira_configured(), "base_url": cfg.get("base")}


@app.get("/jira/search")
def jira_search(
    q: str | None = Query(None, description="Free-text search (text ~ '...')"),
    jql: str | None = Query(None, description="Explicit JQL overrides other filters"),
    project: str | None = Query(None),
    status: str | None = Query(None),
    assignee: str | None = Query(None),
    priority: str | None = Query(None),
    issuetype: str | None = Query(None),
    updated: str | None = Query(None, description=">= constraint, e.g. -14d or 2025-01-01"),
    team: str | None = Query(None, description='Team (Servicedesk), e.g. "Systems Infrastructure"'),
    only_open: int = Query(1, ge=0, le=1),
    max_results: int = Query(50, ge=1, le=200),
):
    sess, base = _jira_session()
    # Build JQL
    jql_str = jql.strip() if jql and jql.strip() else _jira_build_jql(
        q=q,
        project=project,
        status=status,
        assignee=assignee,
        priority=priority,
        issuetype=issuetype,
        updated=updated,
        team=team,
        only_open=bool(only_open),
    )
    fields = [
        "key",
        "summary",
        "status",
        "assignee",
        "priority",
        "updated",
        "created",
        "issuetype",
        "project",
    ]

    # Use the new /search/jql endpoint with GET + query params (legacy /search is removed)
    data: dict[str, Any] | None = None
    used_endpoint = ""
    try:
        url_jql = f"{base}/rest/api/3/search/jql"
        params = {
            "jql": jql_str,
            "startAt": 0,
            "maxResults": int(max_results),
            "fields": ",".join(fields),
        }
        r = sess.get(url_jql, params=params, timeout=60)
        if r.status_code == 401:
            raise HTTPException(status_code=401, detail="Unauthorized: check ATLASSIAN_EMAIL/ATLASSIAN_API_TOKEN")
        if r.status_code == 403:
            raise HTTPException(status_code=403, detail="Forbidden: missing permissions for this JQL/fields")
        if r.status_code == 400:
            # Jira may return a generic 400 for unbounded queries; surface detail
            raise HTTPException(status_code=400, detail=r.text or "Bad request to Jira /search/jql")
        r.raise_for_status()
        data = r.json()
        used_endpoint = "/rest/api/3/search/jql (GET)"
    except HTTPException:
        raise
    except requests.HTTPError as ex:
        msg = getattr(ex.response, "text", "")
        raise HTTPException(status_code=502, detail=f"Jira /search/jql error: {ex} {msg[:300]}")
    except Exception as ex:
        raise HTTPException(status_code=502, detail=f"Jira /search/jql error: {ex}")

    # Normalize issues list from either shape
    issues = []
    if isinstance(data, dict):
        if isinstance(data.get("issues"), list):
            issues = data.get("issues")
        elif isinstance(data.get("results"), list) and data["results"] and isinstance(data["results"][0], dict):
            issues = data["results"][0].get("issues", [])
    out: list[dict[str, Any]] = []
    for it in issues:
        try:
            k = it.get("key") or ""
            f = it.get("fields", {}) or {}
            out.append({
                "key": k,
                "summary": f.get("summary") or "",
                "status": ((f.get("status") or {}).get("name") or ""),
                "assignee": ((f.get("assignee") or {}).get("displayName") or ""),
                "priority": ((f.get("priority") or {}).get("name") or ""),
                "issuetype": ((f.get("issuetype") or {}).get("name") or ""),
                "project": ((f.get("project") or {}).get("key") or ((f.get("project") or {}).get("name") or "")),
                "updated": (f.get("updated") or ""),
                "created": (f.get("created") or ""),
                "url": f"{base}/browse/{k}" if k else "",
            })
        except Exception:
            continue
    total = 0
    if isinstance(data, dict):
        # New endpoint may not return 'total'; compute from page or use provided
        total = int(data.get("total", 0) or 0)
        if not total and isinstance(data.get("isLast"), bool):
            total = len(out)
        if not total and isinstance(data.get("results"), list) and data["results"] and isinstance(data["results"][0], dict):
            total = int(data["results"][0].get("total", 0) or 0)
        if not total:
            total = len(out)
    else:
        total = len(out)
    return {"total": total, "issues": out, "jql": jql_str, "endpoint": used_endpoint}


"""
Confluence integration (read-only search)
- Uses same ATLASSIAN_* credentials
- Queries CQL via /wiki/rest/api/search (GET) with bounded defaults
"""


def _conf_session() -> tuple[requests.Session, str]:
    sess, base = _jira_session()
    # Confluence Cloud REST base is under /wiki
    wiki = base.rstrip("/") + "/wiki"
    return sess, wiki


def _cql_build(
    q: str | None = None,
    space: str | None = None,
    ctype: str | None = None,
    labels: str | None = None,
    updated: str | None = None,
) -> str:
    parts: list[str] = []
    if space and space.strip():
        s = space.strip()
        # If looks like a key (no spaces), use space = "KEY"; otherwise match by title
        esc = s.replace('"', '\\"')
        if any(ch.isspace() for ch in s):
            parts.append(f'space.title = "{esc}"')
        else:
            parts.append(f'space = "{esc}"')
    if ctype and ctype.strip():
        # Confluence types: page, blogpost, attachment, comment, etc.
        parts.append(f"type = {ctype.strip()}")
    if labels and labels.strip():
        arr = [v.strip() for v in labels.split(",") if v.strip()]
        if len(arr) == 1:
            parts.append(f"label = '{arr[0]}'")
        elif arr:
            parts.append("(" + " OR ".join([f"label = '{v}'" for v in arr]) + ")")
    if updated and updated.strip():
        up = updated.strip()
        if up.startswith("-"):
            parts.append(f"lastmodified >= now('{up}')")
        else:
            parts.append(f"lastmodified >= '{up}'")
    # Add text query last to help relevance
    if q and q.strip():
        qq = q.replace("\"", "\\\"")
        parts.append(f'text ~ "{qq}"')
    # Bound the query if still empty (avoid unbounded errors/pagination surprises)
    if not parts:
        parts.append("lastmodified >= now(-90d)")
    # Order by last modified desc
    cql = " AND ".join(parts)
    cql += " order by lastmodified desc"
    return cql


@app.get("/confluence/config")
def confluence_config():
    cfg = _jira_cfg()
    ok = bool(cfg.get("base") and cfg.get("email") and cfg.get("token"))
    base = (cfg.get("base") or "").rstrip("/")
    return {"configured": ok, "base_url": base + "/wiki" if ok else base}


@app.get("/confluence/search")
def confluence_search(
    q: str | None = Query(None, description="Full-text query"),
    space: str | None = Query(None, description="Space key (e.g., DOCS)"),
    ctype: str | None = Query("page", description="Type: page, blogpost, attachment"),
    labels: str | None = Query(None, description="Comma-separated labels"),
    updated: str | None = Query(None, description="-30d or 2025-01-01"),
    max_results: int = Query(50, ge=1, le=100),
):
    sess, wiki = _conf_session()

    # Resolve space names to keys when needed (names often contain spaces; CQL expects keys)
    def _resolve_space_keys(raw: str) -> list[str]:
        toks = [t.strip() for t in (raw or '')
                .split(',') if t.strip()]
        keys: list[str] = []
        for t in toks:
            # Likely a key if no spaces and matches typical key charset
            if t and all((ch.isalnum() or ch in ('_', '-')) for ch in t) and (not any(ch.isspace() for ch in t)):
                keys.append(t)
                continue
            # 1) Lookup by name using CQL; then keep only exact title/name matches
            exact_keys: list[str] = []
            try:
                esc = t.replace('"', '\\"')
                url_s = wiki + "/rest/api/search"
                r_s = sess.get(url_s, params={"cql": f'type = space AND title ~ "{esc}"', "limit": 50}, timeout=30)
                if r_s.ok:
                    data_s = r_s.json()
                    for it in data_s.get("results", []) or []:
                        sp = it.get("space", {}) if isinstance(it, dict) else {}
                        name = (sp.get("name") or it.get("title") or "") if isinstance(sp, dict) else (it.get("title") or "")
                        if isinstance(name, str) and name.strip().lower() == t.strip().lower():
                            k = sp.get("key") if isinstance(sp, dict) else None
                            if k and (k not in exact_keys):
                                exact_keys.append(k)
            except Exception:
                pass
            # 2) Fallback: spaces REST listing filtered by q, then exact name match
            if not exact_keys:
                try:
                    rs = sess.get(wiki + "/rest/api/space", params={"q": t, "limit": 50}, timeout=30)
                    if rs.ok:
                        ds = rs.json()
                        for sp in ds.get("results", []) or []:
                            nm = sp.get("name") or ""
                            if isinstance(nm, str) and nm.strip().lower() == t.strip().lower():
                                k = sp.get("key") or ""
                                if k and (k not in exact_keys):
                                    exact_keys.append(k)
                except Exception:
                    pass
            # Only add exact match keys to avoid partial-space spills
            keys.extend([k for k in exact_keys if k and k not in keys])
        return keys

    space_keys: list[str] = []
    if space and space.strip():
        space_keys = _resolve_space_keys(space)

    cql = _cql_build(q=q, space=None, ctype=ctype, labels=labels, updated=updated)
    if space and space.strip() and not space_keys:
        # Space provided but not resolved exactly -> return empty set
        return {"total": 0, "cql": f"space unresolved: {space}", "results": []}
    if space_keys:
        quoted_keys = ", ".join(f'"{k}"' for k in space_keys)
        cql = f"space in ({quoted_keys}) AND " + cql
    url = wiki + "/rest/api/search"
    # Ask Confluence to include space + history info so we can display Space and Updated reliably
    params = {"cql": cql, "limit": int(max_results), "expand": "content.space,content.history"}
    try:
        r = sess.get(url, params=params, timeout=60)
        if r.status_code == 401:
            raise HTTPException(status_code=401, detail="Unauthorized: check ATLASSIAN_EMAIL/ATLASSIAN_API_TOKEN")
        if r.status_code == 403:
            raise HTTPException(status_code=403, detail="Forbidden: missing permissions for this CQL/fields")
        r.raise_for_status()
        data = r.json()
    except requests.HTTPError as ex:
        msg = getattr(ex.response, "text", "")
        raise HTTPException(status_code=502, detail=f"Confluence error: {ex} {msg[:300]}")
    except Exception as ex:
        raise HTTPException(status_code=502, detail=f"Confluence error: {ex}")

    items = data.get("results", []) if isinstance(data, dict) else []
    out: list[dict[str, Any]] = []
    for it in (items or []):
        try:
            content = it.get("content", {}) if isinstance(it, dict) else {}
            title = content.get("title") or it.get("title") or ""
            ctype_val = content.get("type") or it.get("type") or ""
            space_obj = content.get("space", {}) if isinstance(content, dict) else {}
            space_key = space_obj.get("key") if isinstance(space_obj, dict) else None
            space_name = space_obj.get("name") if isinstance(space_obj, dict) else None
            # Fallbacks for space: resultGlobalContainer title/displayUrl
            if not space_name:
                rgc = it.get("resultGlobalContainer", {}) if isinstance(it, dict) else {}
                if isinstance(rgc, dict):
                    space_name = space_name or rgc.get("title")
                    disp = rgc.get("displayUrl") or ""
                    if (not space_key) and isinstance(disp, str) and "/spaces/" in disp:
                        try:
                            space_key = disp.split("/spaces/")[1].split("/")[0]
                        except Exception:
                            pass
            links = (content.get("_links") or it.get("_links") or {})
            webui = links.get("webui") or links.get("base")
            link = wiki + webui if (isinstance(webui, str) and webui.startswith("/")) else (wiki + "/" + webui if webui else "")
            # last modified
            lastmod = None
            hist = content.get("history") if isinstance(content, dict) else None
            if isinstance(hist, dict):
                last = hist.get("lastUpdated")
                if isinstance(last, dict):
                    lastmod = last.get("when")
            # Fallbacks for updated
            if not lastmod:
                lastmod = it.get("lastModified") or it.get("friendlyLastModified") or ""
            out.append({
                "title": title,
                "type": ctype_val,
                # Prefer human-friendly space name; fall back to key
                "space": (space_name or space_key or ""),
                "space_key": (space_key or ""),
                "space_name": (space_name or ""),
                "updated": lastmod or "",
                "url": link,
            })
        except Exception:
            continue
    total = int(data.get("size", 0) or 0) if isinstance(data, dict) else len(out)
    if not total:
        total = len(out)
    return {"total": total, "cql": cql, "results": out}

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


@app.get("/netbox/config")
def netbox_config():
    """Return minimal NetBox config for the UI (base URL only)."""
    base = os.getenv("NETBOX_URL", "").strip()
    return {"configured": bool(base), "base_url": base}


def _nb_session() -> tuple[requests.Session, str]:
    base = os.getenv("NETBOX_URL", "").strip()
    token = os.getenv("NETBOX_TOKEN", "").strip()
    if not base or not token:
        raise HTTPException(status_code=400, detail="NETBOX_URL/NETBOX_TOKEN not configured in .env")
    sess = requests.Session()
    sess.headers.update({"Authorization": f"Token {token}", "Accept": "application/json"})
    try:
        from .env import apply_extra_headers as _apply
        _apply(sess)
    except Exception:
        pass
    return sess, base.rstrip("/")


@app.get("/netbox/search")
def netbox_search(
    dataset: Literal["devices", "vms", "all"] = Query("all"),
    q: str = Query("", description="Full-text query passed to NetBox ?q="),
    limit: int = Query(50, ge=0, le=5000, description="0 = no limit (fetch all pages)")
):
    """Search NetBox live (no CSV) using the built-in ?q= filter.

    Returns rows with common fields across devices/VMs and a suggested column list.
    """
    if not (q and q.strip()):
        return {"columns": [], "rows": [], "total": 0}
    sess, base = _nb_session()

    def _status_label(x):
        if isinstance(x, dict):
            return x.get("label") or x.get("value") or x.get("name") or ""
        return str(x or "")

    def _get(addr):
        r = sess.get(addr, timeout=30)
        if r.status_code == 401 or r.status_code == 403:
            raise HTTPException(status_code=r.status_code, detail=f"NetBox auth failed: {r.text[:200]}")
        r.raise_for_status()
        return r.json()

    def _collect(endpoint: str, q: str, max_items: int | None) -> list[dict]:
        items: list[dict] = []
        # NetBox uses DRF pagination: limit/offset/next
        page_limit = 200  # reasonable page size
        url = f"{base}{endpoint}?q={requests.utils.quote(q)}&limit={page_limit}&offset=0"
        while url:
            data = _get(url)
            results = data.get("results", []) if isinstance(data, dict) else []
            if not isinstance(results, list):
                break
            items.extend(results)
            if max_items is not None and len(items) >= max_items:
                return items[:max_items]
            url = data.get("next") if isinstance(data, dict) else None
        return items

    def _map_device(it):
        name = it.get("name") or ""
        site = (it.get("site") or {}).get("name") or ""
        tenant = (it.get("tenant") or {}).get("name") or ""
        role = (it.get("device_role") or it.get("role") or {}).get("name") or ""
        status = _status_label(it.get("status"))
        pip4 = (it.get("primary_ip4") or {}).get("address") or ""
        pip6 = (it.get("primary_ip6") or {}).get("address") or ""
        pip = pip4 or pip6
        platform = (it.get("platform") or {}).get("name") or ""
        dtype = (it.get("device_type") or {}).get("model") or ""
        # Try to find an explicit out-of-band management IP from custom fields if present
        cf = it.get("custom_fields") or {}
        oob = ""
        try:
            if isinstance(cf, dict):
                # Common variants people use for OOB/IPMI management
                for key in [
                    "oob_ip", "oob_ip4", "oob_ip6",
                    "out_of_band_ip", "out_of_band",
                    "management_ip", "mgmt_ip", "mgmt_ip4", "mgmt_ip6",
                ]:
                    val = cf.get(key)
                    if isinstance(val, (str, int, float)) and str(val).strip():
                        oob = str(val).strip()
                        break
        except Exception:
            pass
        if not oob:
            oob = pip  # fallback to primary IP when no explicit OOB is found
        ui_path = f"/dcim/devices/{it.get('id')}/" if it.get("id") is not None else ""
        updated = it.get("last_updated") or it.get("last_updated") or ""
        return {
            "Name": name,
            "Status": status,
            "Site": site,
            "Role": role,
            "Tenant": tenant,
            "Primary IP": pip,
            "Out-of-band IP": oob,
            "Platform": platform,
            "Device Type": dtype,
            "Updated": updated,
            "ui_path": ui_path,
        }

    def _map_vm(it):
        name = it.get("name") or ""
        status = _status_label(it.get("status"))
        tenant = (it.get("tenant") or {}).get("name") or ""
        role = (it.get("role") or {}).get("name") or ""
        cluster = (it.get("cluster") or {}).get("name") or ""
        pip4 = (it.get("primary_ip4") or {}).get("address") or ""
        pip6 = (it.get("primary_ip6") or {}).get("address") or ""
        pip = pip4 or pip6
        ui_path = f"/virtualization/virtual-machines/{it.get('id')}/" if it.get("id") is not None else ""
        updated = it.get("last_updated") or ""
        return {
            "Name": name,
            "Status": status,
            "Cluster": cluster,
            "Role": role,
            "Tenant": tenant,
            "Primary IP": pip,
            "Updated": updated,
            "Out-of-band IP": "",
            "ui_path": ui_path,
        }

    rows: list[dict[str, Any]] = []
    try:
        max_items = None if int(limit) == 0 else int(limit)
        if dataset in ("devices", "all"):
            results = _collect("/api/dcim/devices/", q, max_items)
            for it in results:
                d = _map_device(it)
                if dataset == "all":
                    d["Type"] = "device"
                rows.append(d)
        if dataset in ("vms", "all"):
            results = _collect("/api/virtualization/virtual-machines/", q, max_items)
            for it in results:
                v = _map_vm(it)
                if dataset == "all":
                    v["Type"] = "vm"
                rows.append(v)
        # Always include IP addresses when searching 'all'
        if dataset == "all":
            def _map_ip(it: dict) -> dict[str, Any]:
                addr = it.get("address") or ""
                status = _status_label(it.get("status"))
                vrf = ((it.get("vrf") or {}).get("name") or "")
                assigned = ""
                ao = it.get("assigned_object") or {}
                if isinstance(ao, dict):
                    assigned = (ao.get("display") or ao.get("name") or "")
                ui_path = f"/ipam/ip-addresses/{it.get('id')}/" if it.get("id") is not None else ""
                updated = it.get("last_updated") or ""
                return {
                    "Name": addr,
                    "Status": status,
                    "VRF": vrf,
                    "Assigned Object": assigned,
                    "Primary IP": "",
                    "Out-of-band IP": "",
                    "Type": "ip address",
                    "Updated": updated,
                    "ui_path": ui_path,
                }
            ip_results = _collect("/api/ipam/ip-addresses/", q, max_items)
            for it in ip_results:
                rows.append(_map_ip(it))
    except HTTPException:
        raise
    except Exception as ex:
        raise HTTPException(status_code=502, detail=f"NetBox search error: {ex}")

    # Determine columns from first row
    columns: list[str] = []
    if rows:
        keys = list(rows[0].keys())
        # Hide internal helper field from table
        if "ui_path" in keys:
            keys.remove("ui_path")
        columns = keys
    return {"columns": columns, "rows": rows, "total": len(rows)}
