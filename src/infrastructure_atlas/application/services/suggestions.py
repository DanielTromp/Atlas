"""Suggestions service with support for CSV and Airtable backends."""
from __future__ import annotations

import csv
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from infrastructure_atlas.infrastructure.external.airtable_client import (
    AirtableClient,
    AirtableClientConfig,
    AirtableConfigError,
    AirtableError,
    create_airtable_client,
    get_airtable_config_from_env,
)

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
    "Could have": {"color": "#16a34a", "letter": "C"},
    "Would be nice": {"color": "#eab308", "letter": "W"},
    "Should not have": {"color": "#ef4444", "letter": "X"},
}

SUGGESTION_STATUSES = ["new", "accepted", "in progress", "done", "denied"]


class SuggestionServiceError(Exception):
    """Base error for suggestion service."""


class SuggestionNotFoundError(SuggestionServiceError):
    """Raised when a suggestion is not found."""


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


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _decorate_suggestion(item: dict[str, Any]) -> dict[str, Any]:
    """Add computed fields to a suggestion."""
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


def _sort_suggestions(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort suggestions by created_at descending (newest first)."""
    def _sort_key(it: dict[str, Any]):
        try:
            raw = str(it.get("created_at") or "")
            if raw.endswith("Z"):
                raw = raw[:-1]
            return datetime.fromisoformat(raw)
        except Exception:
            return datetime.min

    return sorted(items, key=_sort_key, reverse=True)


class CSVSuggestionBackend:
    """CSV file-based suggestion storage."""

    def __init__(self, csv_path: Path):
        self._path = csv_path
        self._lock = Lock()
        self._ensure_file()

    def _ensure_file(self) -> None:
        if not self._path.parent.exists():
            self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            with self._path.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=SUGGESTION_FIELDS)
                writer.writeheader()

    def _load(self) -> list[dict[str, Any]]:
        try:
            sql = "SELECT * FROM read_csv_auto(?, header=True)"
            df = duckdb.query(sql, params=[self._path.as_posix()]).df()
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

        return _sort_suggestions(out)

    def _write(self, rows: list[dict[str, Any]]) -> None:
        with self._path.open("w", newline="", encoding="utf-8") as fh:
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

    def list_suggestions(self) -> list[dict[str, Any]]:
        with self._lock:
            return self._load()

    def get_suggestion(self, suggestion_id: str) -> dict[str, Any] | None:
        with self._lock:
            items = self._load()
        for item in items:
            if str(item.get("id")) == suggestion_id:
                return item
        return None

    def create_suggestion(self, suggestion: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            rows = self._load()
            rows.append(suggestion)
            self._write(rows)
        return _decorate_suggestion(suggestion)

    def update_suggestion(self, suggestion_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            rows = self._load()
            target = None
            target_index = -1
            for idx, existing in enumerate(rows):
                if str(existing.get("id")) == suggestion_id:
                    target = existing
                    target_index = idx
                    break
            if target is None:
                raise SuggestionNotFoundError(f"Suggestion not found: {suggestion_id}")

            for key, value in updates.items():
                target[key] = value
            target["updated_at"] = _now_iso()
            rows[target_index] = target
            self._write(rows)
            return _decorate_suggestion(target)

    def delete_suggestion(self, suggestion_id: str) -> bool:
        with self._lock:
            rows = self._load()
            new_rows = [row for row in rows if str(row.get("id")) != suggestion_id]
            if len(new_rows) == len(rows):
                return False
            self._write(new_rows)
            return True


class AirtableSuggestionBackend:
    """Airtable-based suggestion storage."""

    def __init__(self, client: AirtableClient):
        self._client = client

    def list_suggestions(self) -> list[dict[str, Any]]:
        items = self._client.list_suggestions()
        decorated = [_decorate_suggestion(item) for item in items]
        return _sort_suggestions(decorated)

    def get_suggestion(self, suggestion_id: str) -> dict[str, Any] | None:
        item = self._client.get_suggestion(suggestion_id)
        if item:
            return _decorate_suggestion(item)
        return None

    def create_suggestion(self, suggestion: dict[str, Any]) -> dict[str, Any]:
        created = self._client.create_suggestion(suggestion)
        return _decorate_suggestion(created)

    def update_suggestion(self, suggestion_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        updates["updated_at"] = _now_iso()
        updated = self._client.update_suggestion(suggestion_id, updates)
        if updated is None:
            raise SuggestionNotFoundError(f"Suggestion not found: {suggestion_id}")
        return _decorate_suggestion(updated)

    def delete_suggestion(self, suggestion_id: str) -> bool:
        return self._client.delete_suggestion(suggestion_id)

    def bulk_create(self, suggestions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        created = self._client.bulk_create(suggestions)
        return [_decorate_suggestion(item) for item in created]


class SuggestionService:
    """High-level suggestion service with configurable backend."""

    def __init__(self, backend: CSVSuggestionBackend | AirtableSuggestionBackend):
        self._backend = backend

    @property
    def backend_type(self) -> str:
        if isinstance(self._backend, AirtableSuggestionBackend):
            return "airtable"
        return "csv"

    def list_suggestions(self) -> list[dict[str, Any]]:
        return self._backend.list_suggestions()

    def get_suggestion(self, suggestion_id: str) -> dict[str, Any] | None:
        return self._backend.get_suggestion(suggestion_id)

    def create_suggestion(
        self,
        title: str,
        summary: str = "",
        classification: str | None = None,
    ) -> dict[str, Any]:
        now = _now_iso()
        item = {
            "id": uuid.uuid4().hex,
            "title": title,
            "summary": summary,
            "classification": _safe_classification(classification),
            "status": "new",
            "likes": 0,
            "created_at": now,
            "updated_at": now,
            "comments": [],
        }
        return self._backend.create_suggestion(item)

    def update_suggestion(
        self,
        suggestion_id: str,
        title: str | None = None,
        summary: str | None = None,
        classification: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        updates: dict[str, Any] = {}
        if title is not None:
            updates["title"] = title
        if summary is not None:
            updates["summary"] = summary
        if classification is not None:
            updates["classification"] = _safe_classification(classification)
        if status is not None:
            updates["status"] = _safe_status(status)
        return self._backend.update_suggestion(suggestion_id, updates)

    def like_suggestion(self, suggestion_id: str, delta: int = 1) -> dict[str, Any]:
        item = self._backend.get_suggestion(suggestion_id)
        if item is None:
            raise SuggestionNotFoundError(f"Suggestion not found: {suggestion_id}")

        current_likes = int(item.get("likes") or 0)
        new_likes = max(0, current_likes + delta)
        return self._backend.update_suggestion(suggestion_id, {"likes": new_likes})

    def add_comment(self, suggestion_id: str, text: str) -> tuple[dict[str, Any], dict[str, Any]]:
        item = self._backend.get_suggestion(suggestion_id)
        if item is None:
            raise SuggestionNotFoundError(f"Suggestion not found: {suggestion_id}")

        comments = item.get("comments") or []
        if not isinstance(comments, list):
            comments = []

        comment = {
            "id": uuid.uuid4().hex,
            "text": text,
            "created_at": _now_iso(),
        }
        comments.append(comment)
        updated = self._backend.update_suggestion(suggestion_id, {"comments": comments})
        return updated, comment

    def delete_comment(self, suggestion_id: str, comment_id: str) -> dict[str, Any]:
        item = self._backend.get_suggestion(suggestion_id)
        if item is None:
            raise SuggestionNotFoundError(f"Suggestion not found: {suggestion_id}")

        comments = item.get("comments") or []
        if not isinstance(comments, list):
            comments = []

        new_comments = [c for c in comments if str(c.get("id")) != comment_id]
        if len(new_comments) == len(comments):
            raise SuggestionNotFoundError(f"Comment not found: {comment_id}")

        return self._backend.update_suggestion(suggestion_id, {"comments": new_comments})

    def delete_suggestion(self, suggestion_id: str) -> bool:
        return self._backend.delete_suggestion(suggestion_id)

    def get_meta(self) -> dict[str, Any]:
        """Return classifications and statuses metadata."""
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


def get_suggestion_backend_type() -> str:
    """Determine which backend type to use based on configuration."""
    backend = os.getenv("SUGGESTIONS_BACKEND", "").strip().lower()
    if backend == "airtable":
        return "airtable"
    if backend == "csv":
        return "csv"

    # Auto-detect: use Airtable if configured
    if get_airtable_config_from_env() is not None:
        return "airtable"
    return "csv"


def create_suggestion_service(data_dir: Path | None = None) -> SuggestionService:
    """Create a suggestion service with the appropriate backend."""
    backend_type = get_suggestion_backend_type()

    if backend_type == "airtable":
        try:
            client = create_airtable_client()
            backend = AirtableSuggestionBackend(client)
            return SuggestionService(backend)
        except AirtableConfigError:
            # Fall back to CSV if Airtable is not properly configured
            pass

    # CSV backend
    if data_dir is None:
        data_dir = Path(os.getenv("NETBOX_DATA_DIR", "data"))
    csv_path = data_dir / "suggestions.csv"
    backend = CSVSuggestionBackend(csv_path)
    return SuggestionService(backend)


def migrate_csv_to_airtable(
    csv_path: Path,
    airtable_config: AirtableClientConfig | None = None,
) -> dict[str, Any]:
    """Migrate suggestions from CSV to Airtable."""
    csv_backend = CSVSuggestionBackend(csv_path)
    suggestions = csv_backend.list_suggestions()

    if not suggestions:
        return {"status": "empty", "count": 0, "message": "No suggestions to migrate"}

    client = create_airtable_client(airtable_config)
    airtable_backend = AirtableSuggestionBackend(client)

    # Prepare items for bulk create (strip decoration fields and convert timestamps to strings)
    items_to_create = []
    for item in suggestions:
        created_at = item.get("created_at")
        updated_at = item.get("updated_at")
        # Convert timestamps/dates to ISO strings
        if hasattr(created_at, "isoformat"):
            created_at = created_at.isoformat()
        elif created_at:
            created_at = str(created_at)
        if hasattr(updated_at, "isoformat"):
            updated_at = updated_at.isoformat()
        elif updated_at:
            updated_at = str(updated_at)

        clean_item = {
            "id": item.get("id"),
            "title": item.get("title"),
            "summary": item.get("summary", ""),
            "classification": item.get("classification"),
            "status": item.get("status"),
            "likes": int(item.get("likes") or 0),
            "created_at": created_at,
            "updated_at": updated_at,
            "comments": item.get("comments") or [],
        }
        items_to_create.append(clean_item)

    created = airtable_backend.bulk_create(items_to_create)
    return {
        "status": "success",
        "count": len(created),
        "message": f"Migrated {len(created)} suggestions to Airtable",
    }


__all__ = [
    "AirtableSuggestionBackend",
    "CSVSuggestionBackend",
    "SUGGESTION_CLASSIFICATIONS",
    "SUGGESTION_FIELDS",
    "SUGGESTION_STATUSES",
    "SuggestionNotFoundError",
    "SuggestionService",
    "SuggestionServiceError",
    "create_suggestion_service",
    "get_suggestion_backend_type",
    "migrate_csv_to_airtable",
]

