"""Chat API routes and AI provider integrations."""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import requests
from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from infrastructure_atlas.db.models import ChatMessage, ChatSession, User
from infrastructure_atlas.env import project_root
from infrastructure_atlas.infrastructure.logging import get_logger

try:
    from openai import OpenAI  # type: ignore
except Exception:  # optional dependency
    OpenAI = None  # type: ignore

logger = get_logger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

# Import dependencies (chat.py imported lazily in __init__.py to avoid circular import)
from infrastructure_atlas.api.app import (
    CurrentUserDep,
    DbSessionDep,
    OptionalUserDep,
    SessionLocal,
    _csv_path,
    _normalise_usage,
    _safe_json_loads,
    require_permission,
)


@dataclass(slots=True)
class ChatProviderResult:
    text: str
    usage: dict[str, int] | None = None
    metadata: dict[str, Any] | None = None
def _chat_default_temperature() -> float | None:
    raw = os.getenv("CHAT_DEFAULT_TEMPERATURE", "").strip().lower()
    if raw in {"", "default", "auto"}:
        return None
    try:
        return float(raw)
    except Exception:
        return None
@router.get("/config", include_in_schema=False)
def chat_config():
    return {
        "system_prompt": os.getenv("CHAT_SYSTEM_PROMPT", ""),
        "temperature": _chat_default_temperature(),
    }


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
        formatted.append(
            {
                "role": role,
                "content": [{"type": content_type, "text": text}],
            }
        )
    return formatted


def _get_chat_session(db: Session, session_id: str) -> ChatSession | None:
    """Get chat session by session_id."""
    from sqlalchemy import select

    stmt = select(ChatSession).where(ChatSession.session_id == session_id)
    return db.execute(stmt).scalar_one_or_none()


def _safe_to_str(value: Any) -> str | None:
    try:
        return str(value)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.debug("Skipping chat variable with non-stringable key", extra={"error": str(exc)})
        return None


def _safe_json_loads(data: str) -> Any | None:
    try:
        return json.loads(data)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.debug("Skipping streaming event with invalid JSON", extra={"error": str(exc)})
        return None


def _normalise_chat_variables(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {}
    normalised: dict[str, Any] = {}
    for raw_key, raw_value in payload.items():
        key = _safe_to_str(raw_key)
        if key is None:
            continue
        if raw_value is None:
            # Explicit None is treated as removal; skip during normalisation.
            normalised[key] = None
            continue
        if isinstance(raw_value, str | int | float | bool):
            normalised[key] = raw_value
            continue
        try:
            json.dumps(raw_value)
            normalised[key] = raw_value
        except TypeError:
            normalised[key] = str(raw_value)
    return normalised


def _apply_chat_variables(
    session: ChatSession,
    updates: Mapping[str, Any] | None,
    *,
    merge: bool = True,
) -> dict[str, Any]:
    if updates is None:
        return dict(session.context_variables or {})
    sanitised = _normalise_chat_variables(updates)
    base = dict(session.context_variables or {}) if merge else {}
    for key, value in sanitised.items():
        if value is None:
            base.pop(key, None)
        else:
            base[key] = value
    session.context_variables = base
    return dict(base)


def _create_chat_session(
    db: Session,
    session_id: str | None = None,
    title: str | None = None,
    user_id: str | None = None,
    variables: Mapping[str, Any] | None = None,
) -> ChatSession:
    """Create a new chat session."""
    if not session_id:
        session_id = "c_" + secrets.token_hex(8)

    context_vars = {key: value for key, value in _normalise_chat_variables(variables).items() if value is not None}
    session = ChatSession(
        session_id=session_id,
        title=title or "New chat",
        user_id=user_id,
        context_variables=context_vars,
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


def _add_chat_message(
    db: Session,
    session: ChatSession,
    role: str,
    content: str,
    *,
    usage: dict[str, int] | None = None,
) -> ChatMessage:
    """Add a message to a chat session."""
    if usage:
        try:
            import json as _json

            content_with_usage = content.rstrip() + "\n[[TOKENS " + _json.dumps(usage) + "]]"
        except Exception:
            content_with_usage = content
    else:
        content_with_usage = content
    message = ChatMessage(
        session_id=session.id,
        role=role,
        content=content_with_usage,
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
        "variables": dict(session.context_variables or {}),
    }


def _serialize_chat_message(message: ChatMessage) -> dict[str, Any]:
    """Serialize chat message for API response."""
    content = message.content or ""
    usage = None
    if "[[TOKENS" in content:
        try:
            marker_start = content.rfind("[[TOKENS ")
            marker_end = content.rfind("]]", marker_start)
            if marker_start >= 0 and marker_end > marker_start:
                import json as _json

                payload = content[marker_start + len("[[TOKENS ") : marker_end]
                usage = _json.loads(payload)
                content = content[:marker_start].rstrip()
        except Exception:
            usage = None

    data = {
        "role": message.role,
        "content": content,
        "created_at": message.created_at.isoformat() + "Z",
    }
    if usage:
        data["usage"] = usage
    return data


class ChatRequest(BaseModel):
    provider: Literal["openai", "openrouter", "claude", "gemini"]
    model: str | None = None
    message: str
    session_id: str
    temperature: float | None = None
    system: str | None = None
    include_context: bool | None = False
    dataset: Literal["devices", "vms", "all", "merged"] | None = "merged"
    variables: dict[str, Any] | None = None
    tool: str | None = None


class ChatSessionCreate(BaseModel):
    name: str | None = None
    variables: dict[str, Any] | None = None


ChatRequestBody = Annotated[ChatRequest, Body(...)]
ChatSessionCreateBody = Annotated[ChatSessionCreate | None, Body()]
ToolSamplePayloadBody = Annotated[dict[str, Any] | None, Body()]


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
                    if err.get("param") == "stream" and err.get("code") == "unsupported_value":
                        return True
                    if (
                        isinstance(err.get("message"), str)
                        and "must be verified to stream" in err.get("message", "").lower()
                    ):
                        return True
    except Exception:
        pass
    return False


def _iter_chunks(text: str, size: int = 128):
    for i in range(0, len(text), size):
        yield text[i : i + size]


def _call_openai(
    model: str,
    messages: list[dict[str, str]],
    api_key: str,
    temperature: float = 0.2,
) -> ChatProviderResult:
    # Prefer the official SDK when available for reliability
    if OpenAI is not None:
        client = OpenAI(api_key=api_key)
        if _use_openai_responses(model):
            _kwargs: dict[str, Any] = {"model": model, "input": _format_responses_messages(messages)}
            if _responses_supports_temperature(model) and temperature is not None:
                _kwargs["temperature"] = temperature
            resp = client.responses.create(**_kwargs)
            usage = _normalise_usage(getattr(resp, "usage", None))
            try:
                text = getattr(resp, "output_text", None)
                if text:
                    return ChatProviderResult(str(text).strip(), usage)
                # Fallback: collect text parts
                chunks = []
                for item in getattr(resp, "output", []) or []:
                    for part in getattr(item, "content", []) or []:
                        if getattr(part, "type", "") == "output_text":
                            chunks.append(getattr(part, "text", ""))
                return ChatProviderResult("".join(chunks).strip(), usage)
            except Exception:
                return ChatProviderResult("", usage)
        else:
            resp = client.chat.completions.create(model=model, messages=messages, temperature=temperature)
            usage = _normalise_usage(getattr(resp, "usage", None))
            try:
                choice = (resp.choices or [None])[0]
                msg = getattr(choice, "message", None)
                return ChatProviderResult((getattr(msg, "content", "") or "").strip(), usage)
            except Exception:
                return ChatProviderResult("", usage)
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
        usage = _normalise_usage(data.get("usage"))
        text = (data.get("output_text") or "").strip()
        if text:
            return ChatProviderResult(text, usage)
        try:
            outs = data.get("output", [])
            chunks = []
            for item in outs:
                parts = item.get("content", []) if isinstance(item, dict) else []
                for p in parts:
                    if isinstance(p, dict) and p.get("type") == "output_text":
                        chunks.append(p.get("text") or "")
            if chunks:
                return ChatProviderResult("".join(chunks).strip(), usage)
        except Exception:
            pass
        return ChatProviderResult("", usage)
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
        usage = _normalise_usage(data.get("usage"))
        text = (data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
        return ChatProviderResult(text, usage)


def _call_openrouter(
    model: str,
    messages: list[dict[str, str]],
    api_key: str,
    temperature: float = 0.2,
) -> ChatProviderResult:
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        # Optional but recommended by OpenRouter
        "HTTP-Referer": os.getenv("OPENROUTER_REFERRER", ""),
        "X-Title": os.getenv("OPENROUTER_TITLE", "Infrastructure Atlas"),
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    r = requests.post(url, headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    data = r.json()
    usage = _normalise_usage(data.get("usage"))
    text = (data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
    return ChatProviderResult(text, usage)


def _call_claude(
    model: str,
    messages: list[dict[str, str]],
    api_key: str,
    temperature: float = 0.2,
) -> ChatProviderResult:
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
    usage = _normalise_usage(data.get("usage"))
    # content is a list of blocks; take first text
    blocks = data.get("content", [])
    if isinstance(blocks, list) and blocks:
        part = blocks[0]
        if isinstance(part, dict) and part.get("type") == "text":
            return ChatProviderResult((part.get("text") or "").strip(), usage)
    # Fallback: try candidates
    return ChatProviderResult((data.get("output_text") or "").strip(), usage)


def _call_gemini(
    model: str,
    messages: list[dict[str, str]],
    api_key: str,
    temperature: float = 0.2,
) -> ChatProviderResult:
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
    usage_meta = data.get("usageMetadata")
    try:
        text = (data["candidates"][0]["content"]["parts"][0]["text"] or "").strip()
        return ChatProviderResult(text, _normalise_usage(usage_meta))
    except Exception:
        return ChatProviderResult((data.get("text") or "").strip(), _normalise_usage(usage_meta))


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
                ors = [f"lower(CAST(\"{h}\" AS VARCHAR)) LIKE '%{safe_kw}%'" for h in headers]
                where_clauses.append("(" + " OR ".join(ors) + ")")

        def _run(where_clause: str | None = None) -> pd.DataFrame:
            sql = "SELECT * FROM read_csv_auto(?, header=True)"
            params: list[Any] = [p.as_posix()]
            if where_clause:
                sql += f" WHERE {where_clause}"
            sql += " LIMIT ?"
            params.append(int(limit))
            return duckdb.query(sql, params=params).df()

        if where_clauses:
            df = _run(" OR ".join(where_clauses))
        elif query.strip():
            safe = query.replace("'", "''")
            ors = [f"lower(CAST(\"{h}\" AS VARCHAR)) LIKE lower('%{safe}%')" for h in headers]
            df = _run(" OR ".join(ors))
            if df.empty:
                df = _run()
        else:
            df = _run()
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
                if hasattr(value, "isoformat") and not isinstance(value, str | int | float | bool):
                    try:
                        return value.isoformat()
                    except Exception:
                        return str(value)
                if isinstance(value, float) and np.isnan(value):
                    return None
                if isinstance(value, str | int | float | bool):
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


@router.get("/providers")
def chat_providers(request: Request, user: CurrentUserDep, db: DbSessionDep):
    require_permission(request, "chat.use")
    env = _chat_env(db=db, user=user)
    out = []
    for pid in ["openai", "openrouter", "claude", "gemini"]:
        cfg = env.get(pid, {})
        out.append(
            {
                "id": pid,
                "configured": bool(cfg.get("api_key")),
                "default_model": cfg.get("default_model"),
                "key_source": cfg.get("key_source"),
                "label": cfg.get("label"),
            }
        )
    return {"providers": out, "default_provider": env.get("default_provider", "openai")}


@router.get("/history")
def chat_history(
    request: Request,
    db: DbSessionDep,
    session_id: str = Query(...),
):
    require_permission(request, "chat.use")
    session = _get_chat_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")

    messages = [_serialize_chat_message(msg) for msg in session.messages]
    return {
        "session_id": session_id,
        "messages": messages,
        "variables": dict(session.context_variables or {}),
    }


@router.get("/sessions")
def chat_sessions(
    request: Request,
    db: DbSessionDep,
    user: OptionalUserDep,
    limit: int | None = Query(None, ge=1, le=200),
):
    require_permission(request, "chat.use")
    from sqlalchemy import select

    stmt = select(ChatSession).order_by(ChatSession.updated_at.desc())
    if user:
        stmt = stmt.where(ChatSession.user_id == user.id)
    if limit:
        stmt = stmt.limit(limit)

    sessions = db.execute(stmt).scalars().all()
    return {"sessions": [_serialize_chat_session(session) for session in sessions]}


@router.post("/session")
def chat_session_create(
    request: Request,
    db: DbSessionDep,
    user: OptionalUserDep,
    req: ChatSessionCreateBody = None,
):
    require_permission(request, "chat.use")
    title = (req.name if req else "") or "New chat"
    variables = req.variables if req else None
    session = _create_chat_session(
        db,
        title=title,
        user_id=user.id if user else None,
        variables=variables or None,
    )
    return _serialize_chat_session(session)


@router.delete("/session/{session_id}")
def chat_session_delete(
    request: Request,
    session_id: str,
    db: DbSessionDep,
    user: OptionalUserDep,
):
    """Delete a chat session and all its messages."""
    require_permission(request, "chat.use")
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


@router.post("/complete")
def chat_complete(
    request: Request,
    req: ChatRequestBody,
    user: OptionalUserDep,
    db: DbSessionDep,
):
    # AI/LangChain functionality has been disabled
    raise HTTPException(
        status_code=501,
        detail="AI chat functionality is currently disabled. LangChain dependencies have been removed."
    )


def _stream_openai_text(
    model: str,
    messages: list[dict[str, str]],
    api_key: str,
    temperature: float = 0.2,
    usage_target: list[dict[str, int]] | None = None,
):
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
                        event_type = getattr(event, "type", "")
                        if event_type == "response.output_text.delta":
                            delta = getattr(event, "delta", "")
                            if delta:
                                yield delta
                        if usage_target is not None:
                            usage = _normalise_usage(getattr(event, "usage", None))
                            if usage:
                                usage_target.clear()
                                usage_target.append(usage)
                    final_response = stream.get_final_response()
                    if usage_target is not None:
                        usage = _normalise_usage(getattr(final_response, "usage", None))
                        if usage:
                            usage_target.clear()
                            usage_target.append(usage)
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
                    choice = (chunk.choices or [None])[0]
                    delta = getattr(choice, "delta", None)
                    if delta is not None:
                        text = getattr(delta, "content", None)
                        if text:
                            yield text
                    if usage_target is not None:
                        usage = _normalise_usage(getattr(chunk, "usage", None))
                        if usage:
                            usage_target.clear()
                            usage_target.append(usage)
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
            for raw_line in r.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                line = raw_line
                if isinstance(line, bytes):
                    try:
                        line = line.decode("utf-8", errors="ignore")
                    except Exception:
                        line = str(line)
                if not isinstance(line, str):
                    line = str(line)
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                obj = _safe_json_loads(data)
                if not isinstance(obj, dict):
                    continue
                if obj.get("type") == "response.output_text.delta":
                    delta = obj.get("delta") or ""
                    if delta:
                        yield delta
                if usage_target is not None:
                    usage = _normalise_usage(obj.get("usage"))
                    if usage:
                        usage_target.clear()
                        usage_target.append(usage)
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
            for raw_line in r.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue
                line = raw_line
                if isinstance(line, bytes):
                    try:
                        line = line.decode("utf-8", errors="ignore")
                    except Exception:
                        line = str(line)
                if not isinstance(line, str):
                    line = str(line)
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                obj = _safe_json_loads(data)
                if not isinstance(obj, dict):
                    continue
                delta = obj.get("choices", [{}])[0].get("delta", {}).get("content")
                if delta:
                    yield delta
                if usage_target is not None:
                    usage = _normalise_usage(obj.get("usage"))
                    if usage:
                        usage_target.clear()
                        usage_target.append(usage)


def _stream_openrouter_text(
    model: str,
    messages: list[dict[str, str]],
    api_key: str,
    temperature: float = 0.2,
    usage_target: list[dict[str, int]] | None = None,
):
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "HTTP-Referer": os.getenv("OPENROUTER_REFERRER", ""),
        "X-Title": os.getenv("OPENROUTER_TITLE", "Infrastructure Atlas"),
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
    }
    with requests.post(url, headers=headers, json=payload, stream=True, timeout=300) as r:
        r.raise_for_status()
        for raw_line in r.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            line = raw_line
            if isinstance(line, bytes):
                try:
                    line = line.decode("utf-8", errors="ignore")
                except Exception:
                    line = str(line)
            if not isinstance(line, str):
                line = str(line)
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            obj = _safe_json_loads(data)
            if not isinstance(obj, dict):
                continue
            delta = obj.get("choices", [{}])[0].get("delta", {}).get("content")
            if delta:
                yield delta
            if usage_target is not None:
                usage = _normalise_usage(obj.get("usage"))
                if usage:
                    usage_target.clear()
                    usage_target.append(usage)


@router.post("/stream")
def chat_stream(
    request: Request,
    req: ChatRequestBody,
    user: OptionalUserDep,
    db: DbSessionDep,
):
    require_permission(request, "chat.use")
    try:
        result = chat_complete(req, user, db, request)
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive fallback
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    reply_text = str(result.get("reply") or "")

    async def generator():
        yield reply_text

    return StreamingResponse(generator(), media_type="text/plain; charset=utf-8")
