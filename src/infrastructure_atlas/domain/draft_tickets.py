"""Domain entities for the draft ticket shadow ticketing system.

Draft tickets are AI-proposed tickets that can be reviewed, approved, and pushed to Jira.
They serve as a staging area for ticket proposals before they become official Jira issues.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class DraftTicketStatus(str, Enum):
    """Status lifecycle for draft tickets."""

    PROPOSED = "proposed"
    APPROVED = "approved"
    PUSHED = "pushed"
    REJECTED = "rejected"


class DraftTicketPriority(str, Enum):
    """Priority levels for draft tickets."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DraftTicketLinkType(str, Enum):
    """Types of links between draft tickets and Jira issues."""

    RELATES_TO = "relates_to"
    BLOCKS = "blocks"
    SUBTASK_OF = "subtask_of"
    DUPLICATES = "duplicates"


@dataclass(slots=True)
class DraftTicketEntity:
    """Domain representation of a draft ticket proposal.

    A draft ticket captures an AI-proposed issue that can be reviewed,
    linked to existing Jira issues, and eventually pushed to Jira.
    """

    id: str
    suggested_title: str
    suggested_description: str | None
    suggested_priority: DraftTicketPriority
    suggested_labels: tuple[str, ...]
    ai_proposal: dict[str, Any]
    status: DraftTicketStatus
    created_at: datetime
    updated_at: datetime
    linked_jira_key: str | None = None
    link_type: DraftTicketLinkType | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    pushed_to_jira_at: datetime | None = None
    created_jira_key: str | None = None
    source_context: dict[str, Any] = field(default_factory=dict)

    @property
    def linked_jira_url(self) -> str | None:
        """Generate Jira URL from linked key."""
        if not self.linked_jira_key:
            return None
        return f"https://enreach.atlassian.net/browse/{self.linked_jira_key}"

    @property
    def created_jira_url(self) -> str | None:
        """Generate Jira URL from created key after push."""
        if not self.created_jira_key:
            return None
        return f"https://enreach.atlassian.net/browse/{self.created_jira_key}"


__all__ = [
    "DraftTicketEntity",
    "DraftTicketLinkType",
    "DraftTicketPriority",
    "DraftTicketStatus",
]
