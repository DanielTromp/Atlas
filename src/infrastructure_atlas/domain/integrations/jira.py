"""Typed models representing Jira REST payloads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class JiraAttachment:
    """Metadata about a Jira attachment after upload or lookup."""

    id: str
    filename: str
    size: int
    mime_type: str | None
    content_url: str | None
    self_url: str | None
    author_display_name: str | None = None
    created_at: datetime | None = None
