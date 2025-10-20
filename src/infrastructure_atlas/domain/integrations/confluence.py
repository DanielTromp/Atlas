"""Typed models representing Confluence REST payloads."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class ConfluenceAttachment:
    """Metadata about a Confluence attachment after upload or lookup."""

    id: str
    title: str
    version: int | None
    download_url: str | None
    web_url: str | None
    media_type: str | None
    created_at: datetime | None = None
    updated_at: datetime | None = None

