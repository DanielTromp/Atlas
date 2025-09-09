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
