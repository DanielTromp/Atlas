from __future__ import annotations

import asyncio
import csv
import os
import shutil
import sys
from pathlib import Path
from typing import Literal, Any

import duckdb
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Body
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from datetime import datetime
from starlette.middleware.base import BaseHTTPMiddleware

from enreach_tools.env import load_env, project_root
import requests
try:
    from openai import OpenAI  # type: ignore
except Exception:  # optional dependency
    OpenAI = None  # type: ignore

load_env()

app = FastAPI(title="Enreach Tools API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


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


# ---------------------------
# Chat integration (simple)
# ---------------------------

# Ephemeral in-memory sessions; keyed by client-provided session_id
CHAT_SESSIONS: dict[str, list[dict[str, Any]]] = {}


def _chat_env() -> dict[str, Any]:
    return {
        "openai": {
            "api_key": os.getenv("OPENAI_API_KEY", "").strip(),
            "default_model": os.getenv("CHAT_DEFAULT_MODEL_OPENAI", "gpt-5-mini"),
        },
        "openrouter": {
            "api_key": os.getenv("OPENROUTER_API_KEY", "").strip(),
            "default_model": os.getenv("CHAT_DEFAULT_MODEL_OPENROUTER", "openrouter/auto"),
        },
        "claude": {
            "api_key": os.getenv("ANTHROPIC_API_KEY", "").strip(),
            "default_model": os.getenv("CHAT_DEFAULT_MODEL_CLAUDE", "claude-3-5-sonnet-20240620"),
        },
        "gemini": {
            "api_key": os.getenv("GOOGLE_API_KEY", "").strip(),
            "default_model": os.getenv("CHAT_DEFAULT_MODEL_GEMINI", "gemini-1.5-flash"),
        },
        "default_provider": os.getenv("CHAT_DEFAULT_PROVIDER", "openai"),
    }


class ChatRequest(BaseModel):
    provider: Literal["openai", "openrouter", "claude", "gemini"]
    model: str | None = None
    message: str
    session_id: str
    temperature: float | None = 0.2
    system: str | None = None
    include_context: bool | None = False
    dataset: Literal["devices", "vms", "all"] | None = "all"


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
    if "must be verified to stream" in msg or "stream" in msg and "unsupported" in msg:
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
    def _to_responses_input(msgs: list[dict[str, str]]):
        out = []
        for m in msgs:
            role = m.get("role", "user")
            text = m.get("content", "")
            # Responses API expects content parts with type 'input_text'
            out.append({"role": role, "content": [{"type": "input_text", "text": str(text)}]})
        return out

    # Prefer the official SDK when available for reliability
    if OpenAI is not None:
        client = OpenAI(api_key=api_key)
        if _use_openai_responses(model):
            _kwargs: dict[str, Any] = {"model": model, "input": _to_responses_input(messages)}
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
        payload = {"model": model, "input": _to_responses_input(messages)}
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
    if dataset == "devices":
        p = _csv_path("netbox_devices_export.csv")
    elif dataset == "vms":
        p = _csv_path("netbox_vms_export.csv")
    else:
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
        # Build LIKE predicate across all columns
        safe = query.replace("'", "''")
        ors = [f"lower(CAST(\"{h}\" AS VARCHAR)) LIKE lower('%{safe}%')" for h in headers]
        sql = (
            f"SELECT * FROM read_csv_auto('{p.as_posix()}', header=True)"
            + (f" WHERE { ' OR '.join(ors) }" if query.strip() else "")
            + f" LIMIT {int(max_rows)}"
        )
        df = duckdb.query(sql).df()
        # Render context text
        parts: list[str] = []
        parts.append(f"Columns: {', '.join(map(str, headers))}")
        if not df.empty:
            parts.append("Relevant rows (JSON):")
            for _, row in df.iterrows():
                try:
                    obj = {str(k): (None if pd.isna(v) else v) for k, v in row.items()}
                except Exception:
                    obj = {str(k): str(v) for k, v in row.items()}
                import json as _json

                parts.append(_json.dumps(obj, ensure_ascii=False)[:400])
        context = "\n".join(parts)
        if len(context) > max_chars:
            context = context[: max_chars - 20] + "\n…"
        return context
    except Exception:
        return ""


@app.get("/chat/providers")
def chat_providers():
    env = _chat_env()
    out = []
    for pid in ["openai", "openrouter", "claude", "gemini"]:
        cfg = env.get(pid, {})
        out.append({
            "id": pid,
            "configured": bool(cfg.get("api_key")),
            "default_model": cfg.get("default_model"),
        })
    return {"providers": out, "default_provider": env.get("default_provider", "openai")}


@app.get("/chat/history")
def chat_history(session_id: str = Query(...)):
    return {"session_id": session_id, "messages": CHAT_SESSIONS.get(session_id, [])}


@app.post("/chat/complete")
def chat_complete(req: ChatRequest = Body(...)):
    env = _chat_env()
    pid = req.provider
    if pid not in env:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {pid}")
    api_key = env[pid].get("api_key")
    if not api_key:
        raise HTTPException(status_code=400, detail=f"Provider '{pid}' not configured (missing API key)")
    model = (req.model or env[pid].get("default_model") or "").strip()
    if not model:
        raise HTTPException(status_code=400, detail=f"No model specified for provider '{pid}'")

    # Accumulate messages in session, respecting max turns
    history = CHAT_SESSIONS.setdefault(req.session_id, [])
    # Optional: include a system instruction to avoid automatic actions
    if req.system:
        if not history or history[0].get("role") != "system":
            history.insert(0, {"role": "system", "content": str(req.system)[:4000]})
    # Optionally include data context
    if req.include_context:
        ctx_text = _build_data_context(req.dataset or "all", req.message)
        if ctx_text:
            history.append({
                "role": "system",
                "content": f"Data context from {req.dataset or 'all'}: \n" + ctx_text,
            })
    user_msg = {"role": "user", "content": str(req.message)[:8000]}
    history.append(user_msg)
    clipped = _messages_for_provider(history)

    try:
        if pid == "openai":
            text = _call_openai(model, clipped, api_key, temperature=req.temperature or 0.2)
        elif pid == "openrouter":
            text = _call_openrouter(model, clipped, api_key, temperature=req.temperature or 0.2)
        elif pid == "claude":
            text = _call_claude(model, clipped, api_key, temperature=req.temperature or 0.2)
        elif pid == "gemini":
            text = _call_gemini(model, clipped, api_key, temperature=req.temperature or 0.2)
        else:
            raise ValueError(f"Unsupported provider: {pid}")
    except requests.HTTPError as ex:
        # Keep the user message in history; add an assistant error message
        err = f"Provider error: {ex.response.status_code if ex.response else ''} {str(ex)}"
        history.append({"role": "assistant", "content": err})
        return {"session_id": req.session_id, "provider": pid, "model": model, "reply": err, "messages": history}
    except Exception as ex:
        err = f"Error: {ex}"
        history.append({"role": "assistant", "content": err})
        return {"session_id": req.session_id, "provider": pid, "model": model, "reply": err, "messages": history}

    # Append assistant reply and return
    history.append({"role": "assistant", "content": text})
    return {"session_id": req.session_id, "provider": pid, "model": model, "reply": text, "messages": history}


def _stream_openai_text(model: str, messages: list[dict[str, str]], api_key: str, temperature: float = 0.2):
    # Prefer SDK streaming
    if OpenAI is not None:
        client = OpenAI(api_key=api_key)
        if _use_openai_responses(model):
            try:
                kwargs: dict[str, Any] = {
                    "model": model,
                    "input": [
                        {"role": m.get("role", "user"), "content": [{"type": "input_text", "text": m.get("content", "")}]} for m in messages
                    ],
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
            "input": [
                {"role": m.get("role", "user"), "content": [{"type": "input_text", "text": m.get("content", "")}]} for m in messages
            ],
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
def chat_stream(req: ChatRequest = Body(...)):
    env = _chat_env()
    pid = req.provider
    if pid not in env:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {pid}")
    api_key = env[pid].get("api_key")
    if not api_key:
        raise HTTPException(status_code=400, detail=f"Provider '{pid}' not configured (missing API key)")
    model = (req.model or env[pid].get("default_model") or "").strip()
    if not model:
        raise HTTPException(status_code=400, detail=f"No model specified for provider '{pid}'")

    history = CHAT_SESSIONS.setdefault(req.session_id, [])
    # Ensure system instruction
    sys_default = (
        req.system
        or "Je geeft alleen voorstellen en voorbeeldteksten. Je voert geen acties uit."
    )
    if not history or history[0].get("role") != "system":
        history.insert(0, {"role": "system", "content": sys_default[:4000]})
    # Include optional data context
    if req.include_context:
        ctx_text = _build_data_context(req.dataset or "all", req.message)
        if ctx_text:
            history.append({"role": "system", "content": f"Data context from {req.dataset or 'all'}:\n" + ctx_text})
    # Add user message
    user_msg = {"role": "user", "content": str(req.message)[:8000]}
    history.append(user_msg)

    clipped = _messages_for_provider(history)

    def generator():
        full_text = []
        try:
            if pid == "openai":
                try:
                    for chunk in _stream_openai_text(model, clipped, api_key, temperature=req.temperature or 0.2):
                        full_text.append(chunk)
                        yield chunk
                except Exception as ex:  # smart fallback when streaming is not allowed
                    if _is_openai_streaming_unsupported(ex):
                        # Fallback to non-streaming call and emit in chunks
                        try:
                            text = _call_openai(model, clipped, api_key, temperature=req.temperature or 0.2)
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
                    for chunk in _stream_openrouter_text(model, clipped, api_key, temperature=req.temperature or 0.2):
                        full_text.append(chunk)
                        yield chunk
                except Exception as ex:
                    msg = f"\n[error] {getattr(getattr(ex, 'response', None), 'status_code', '')} {ex}"
                    full_text.append(msg)
                    yield msg
            else:
                # Fallback to non-streaming and chunk locally
                if pid == "claude":
                    text = _call_claude(model, clipped, api_key, temperature=req.temperature or 0.2)
                elif pid == "gemini":
                    text = _call_gemini(model, clipped, api_key, temperature=req.temperature or 0.2)
                else:
                    text = ""
                for i in range(0, len(text), 64):
                    part = text[i : i + 64]
                    full_text.append(part)
                    yield part
        finally:
            # Save assistant message
            out = "".join(full_text).strip()
            history.append({"role": "assistant", "content": out})

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
    if "error" in data and data["error"]:
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
        cql = f"space in ({', '.join([f'\"{k}\"' for k in space_keys])}) AND " + cql
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
