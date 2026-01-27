"""Airtable API client for suggestions management."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from pyairtable import Api, Table
from pyairtable.formulas import match

from infrastructure_atlas.infrastructure.caching import TTLCache


def _read_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


# Cache TTL for suggestions (default 5 minutes)
_SUGGESTIONS_CACHE_TTL = max(0.0, _read_float_env("AIRTABLE_CACHE_TTL", 300.0))

if _SUGGESTIONS_CACHE_TTL > 0:
    _SUGGESTIONS_CACHE: TTLCache[str, list[dict[str, Any]]] | None = TTLCache(
        ttl_seconds=_SUGGESTIONS_CACHE_TTL,
        name="airtable.suggestions",
    )
else:
    _SUGGESTIONS_CACHE = None


class AirtableError(Exception):
    """Generic Airtable integration error."""


class AirtableConfigError(AirtableError):
    """Raised when configuration is incomplete or invalid."""


class AirtableAuthError(AirtableError):
    """Raised when authentication with the Airtable API fails."""


class AirtableResponseError(AirtableError):
    """Raised when Airtable returns an unexpected response."""


@dataclass(slots=True)
class AirtableClientConfig:
    """Runtime configuration for the Airtable client."""

    pat: str
    base_id: str
    table_name: str = "Suggestions"


SUGGESTION_FIELD_MAP = {
    "id": "id",
    "title": "title",
    "summary": "summary",
    "classification": "classification",
    "status": "status",
    "likes": "likes",
    "created_at": "created_at",
    "updated_at": "updated_at",
    "comments": "comments",
}


@dataclass
class AirtableClient:
    """Client for interacting with Airtable API."""

    config: AirtableClientConfig
    _api: Api = field(init=False, repr=False)
    _table: Table = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.config.pat:
            raise AirtableConfigError("Airtable PAT is required")
        if not self.config.base_id:
            raise AirtableConfigError("Airtable base_id is required")

        self._api = Api(self.config.pat)
        self._table = self._api.table(self.config.base_id, self.config.table_name)

    def _record_to_suggestion(self, record: dict[str, Any]) -> dict[str, Any]:
        """Convert an Airtable record to a suggestion dict."""
        fields = record.get("fields", {})
        return {
            "id": fields.get("id"),
            "title": fields.get("title", ""),
            "summary": fields.get("summary", ""),
            "classification": fields.get("classification", "Could have"),
            "status": fields.get("status", "new"),
            "likes": int(fields.get("likes") or 0),
            "created_at": fields.get("created_at"),
            "updated_at": fields.get("updated_at"),
            "comments": self._parse_comments(fields.get("comments")),
            "_airtable_record_id": record.get("id"),
        }

    def _parse_comments(self, raw: Any) -> list[dict[str, Any]]:
        """Parse comments from Airtable field."""
        if not raw:
            return []
        if isinstance(raw, list):
            return [c for c in raw if isinstance(c, dict)]
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                return [c for c in parsed if isinstance(c, dict)] if isinstance(parsed, list) else []
            except json.JSONDecodeError:
                return []
        return []

    def _suggestion_to_fields(self, suggestion: dict[str, Any]) -> dict[str, Any]:
        """Convert a suggestion dict to Airtable fields."""
        fields: dict[str, Any] = {}
        if "id" in suggestion:
            fields["id"] = suggestion["id"]
        if "title" in suggestion:
            fields["title"] = suggestion["title"]
        if "summary" in suggestion:
            fields["summary"] = suggestion.get("summary") or ""
        if "classification" in suggestion:
            fields["classification"] = suggestion["classification"]
        if "status" in suggestion:
            fields["status"] = suggestion["status"]
        if "likes" in suggestion:
            fields["likes"] = int(suggestion.get("likes") or 0)
        if "created_at" in suggestion:
            fields["created_at"] = suggestion["created_at"]
        if "updated_at" in suggestion:
            fields["updated_at"] = suggestion["updated_at"]
        if "comments" in suggestion:
            comments = suggestion.get("comments") or []
            fields["comments"] = json.dumps(comments, ensure_ascii=False) if comments else ""
        return fields

    def list_suggestions(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        """List all suggestions from Airtable."""
        cache_key = f"suggestions:{self.config.base_id}:{self.config.table_name}"

        if not force_refresh and _SUGGESTIONS_CACHE is not None:
            try:
                return _SUGGESTIONS_CACHE.get(cache_key, lambda: self._fetch_suggestions())
            except Exception:
                pass

        return self._fetch_suggestions()

    def _fetch_suggestions(self) -> list[dict[str, Any]]:
        """Fetch all suggestions from Airtable."""
        try:
            records = self._table.all()
            return [self._record_to_suggestion(r) for r in records]
        except Exception as e:
            if "AUTHENTICATION_REQUIRED" in str(e) or "401" in str(e):
                raise AirtableAuthError(f"Authentication failed: {e}") from e
            raise AirtableResponseError(f"Failed to fetch suggestions: {e}") from e

    def get_suggestion(self, suggestion_id: str) -> dict[str, Any] | None:
        """Get a single suggestion by ID."""
        try:
            records = self._table.all(formula=match({"id": suggestion_id}))
            if records:
                return self._record_to_suggestion(records[0])
            return None
        except Exception as e:
            raise AirtableResponseError(f"Failed to get suggestion: {e}") from e

    def create_suggestion(self, suggestion: dict[str, Any]) -> dict[str, Any]:
        """Create a new suggestion in Airtable."""
        fields = self._suggestion_to_fields(suggestion)
        try:
            record = self._table.create(fields)
            self._invalidate_cache()
            return self._record_to_suggestion(record)
        except Exception as e:
            raise AirtableResponseError(f"Failed to create suggestion: {e}") from e

    def update_suggestion(self, suggestion_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        """Update an existing suggestion by ID."""
        try:
            records = self._table.all(formula=match({"id": suggestion_id}))
            if not records:
                return None

            record_id = records[0]["id"]
            fields = self._suggestion_to_fields(updates)
            updated = self._table.update(record_id, fields)
            self._invalidate_cache()
            return self._record_to_suggestion(updated)
        except Exception as e:
            raise AirtableResponseError(f"Failed to update suggestion: {e}") from e

    def delete_suggestion(self, suggestion_id: str) -> bool:
        """Delete a suggestion by ID."""
        try:
            records = self._table.all(formula=match({"id": suggestion_id}))
            if not records:
                return False

            record_id = records[0]["id"]
            self._table.delete(record_id)
            self._invalidate_cache()
            return True
        except Exception as e:
            raise AirtableResponseError(f"Failed to delete suggestion: {e}") from e

    def bulk_create(self, suggestions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Bulk create suggestions in Airtable."""
        if not suggestions:
            return []

        try:
            fields_list = [self._suggestion_to_fields(s) for s in suggestions]
            records = self._table.batch_create(fields_list)
            self._invalidate_cache()
            return [self._record_to_suggestion(r) for r in records]
        except Exception as e:
            raise AirtableResponseError(f"Failed to bulk create suggestions: {e}") from e

    def _invalidate_cache(self) -> None:
        """Invalidate the suggestions cache."""
        if _SUGGESTIONS_CACHE is not None:
            cache_key = f"suggestions:{self.config.base_id}:{self.config.table_name}"
            _SUGGESTIONS_CACHE.invalidate(cache_key)


def get_airtable_config_from_env() -> AirtableClientConfig | None:
    """Get Airtable configuration from environment variables."""
    pat = os.getenv("AIRTABLE_PAT", "").strip()
    base_id = os.getenv("AIRTABLE_BASE_ID", "").strip()
    table_name = os.getenv("AIRTABLE_TABLE_NAME", "Suggestions").strip()

    if not pat or not base_id:
        return None

    return AirtableClientConfig(
        pat=pat,
        base_id=base_id,
        table_name=table_name,
    )


def create_airtable_client(config: AirtableClientConfig | None = None) -> AirtableClient:
    """Create an Airtable client with the given or default configuration."""
    if config is None:
        config = get_airtable_config_from_env()
    if config is None:
        raise AirtableConfigError("Airtable configuration is not set")
    return AirtableClient(config)


__all__ = [
    "AirtableAuthError",
    "AirtableClient",
    "AirtableClientConfig",
    "AirtableConfigError",
    "AirtableError",
    "AirtableResponseError",
    "create_airtable_client",
    "get_airtable_config_from_env",
]

