"""Service layer for managing draft tickets with JSON file storage.

This service provides CRUD operations for draft tickets, which are AI-proposed
tickets staged for review before being pushed to Jira.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

from infrastructure_atlas.domain.draft_tickets import (
    DraftTicketEntity,
    DraftTicketLinkType,
    DraftTicketPriority,
    DraftTicketStatus,
)
from infrastructure_atlas.env import project_root
from infrastructure_atlas.infrastructure.logging import get_logger

logger = get_logger(__name__)

DATA_DIR_ENV = "ATLAS_DATA_DIR"
DRAFT_TICKETS_FILE = "draft_tickets.json"
_FILE_LOCK = Lock()


def _now_utc() -> datetime:
    """Return current UTC time."""
    return datetime.now(UTC)


def _isoformat(dt: datetime | None) -> str | None:
    """Convert datetime to ISO format string."""
    if dt is None:
        return None
    value = dt.astimezone(UTC).isoformat()
    return value.replace("+00:00", "Z")


def _parse_iso_datetime(value: Any) -> datetime | None:
    """Parse ISO format string to datetime."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        normalized = text.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).astimezone(UTC)
    except ValueError:
        return None


def _resolve_data_dir() -> Path:
    """Resolve the data directory for storing draft tickets."""
    raw = (os.getenv(DATA_DIR_ENV) or "").strip()
    if raw:
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = project_root() / candidate
    else:
        candidate = project_root() / "data"
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


def _normalize_text(value: Any) -> str | None:
    """Normalize a text value to stripped string or None."""
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned:
            return cleaned
    return None


def _serialize_ticket(ticket: DraftTicketEntity) -> dict[str, Any]:
    """Serialize a draft ticket entity to a dictionary for JSON storage."""
    return {
        "id": ticket.id,
        "suggested_title": ticket.suggested_title,
        "suggested_description": ticket.suggested_description,
        "suggested_priority": ticket.suggested_priority.value,
        "suggested_labels": list(ticket.suggested_labels),
        "ai_proposal": ticket.ai_proposal,
        "status": ticket.status.value,
        "linked_jira_key": ticket.linked_jira_key,
        "link_type": ticket.link_type.value if ticket.link_type else None,
        "reviewed_by": ticket.reviewed_by,
        "reviewed_at": _isoformat(ticket.reviewed_at),
        "pushed_to_jira_at": _isoformat(ticket.pushed_to_jira_at),
        "created_jira_key": ticket.created_jira_key,
        "source_context": ticket.source_context,
        "created_at": _isoformat(ticket.created_at),
        "updated_at": _isoformat(ticket.updated_at),
    }


def _deserialize_ticket(data: Mapping[str, Any]) -> DraftTicketEntity:
    """Deserialize a dictionary from JSON storage to a draft ticket entity."""
    raw_labels = data.get("suggested_labels")
    labels: tuple[str, ...] = ()
    if isinstance(raw_labels, list | tuple):
        labels = tuple(str(label).strip() for label in raw_labels if label)

    raw_priority = data.get("suggested_priority", "medium")
    try:
        priority = DraftTicketPriority(raw_priority)
    except ValueError:
        priority = DraftTicketPriority.MEDIUM

    raw_status = data.get("status", "proposed")
    try:
        status = DraftTicketStatus(raw_status)
    except ValueError:
        status = DraftTicketStatus.PROPOSED

    raw_link_type = data.get("link_type")
    link_type: DraftTicketLinkType | None = None
    if raw_link_type:
        try:
            link_type = DraftTicketLinkType(raw_link_type)
        except ValueError:
            link_type = None

    raw_ai_proposal = data.get("ai_proposal")
    ai_proposal: dict[str, Any] = {}
    if isinstance(raw_ai_proposal, dict):
        ai_proposal = dict(raw_ai_proposal)

    raw_source_context = data.get("source_context")
    source_context: dict[str, Any] = {}
    if isinstance(raw_source_context, dict):
        source_context = dict(raw_source_context)

    return DraftTicketEntity(
        id=str(data.get("id") or ""),
        suggested_title=str(data.get("suggested_title") or ""),
        suggested_description=_normalize_text(data.get("suggested_description")),
        suggested_priority=priority,
        suggested_labels=labels,
        ai_proposal=ai_proposal,
        status=status,
        linked_jira_key=_normalize_text(data.get("linked_jira_key")),
        link_type=link_type,
        reviewed_by=_normalize_text(data.get("reviewed_by")),
        reviewed_at=_parse_iso_datetime(data.get("reviewed_at")),
        pushed_to_jira_at=_parse_iso_datetime(data.get("pushed_to_jira_at")),
        created_jira_key=_normalize_text(data.get("created_jira_key")),
        source_context=source_context,
        created_at=_parse_iso_datetime(data.get("created_at")) or _now_utc(),
        updated_at=_parse_iso_datetime(data.get("updated_at")) or _now_utc(),
    )


class DraftTicketNotFoundError(ValueError):
    """Raised when a draft ticket is not found."""


class DraftTicketValidationError(ValueError):
    """Raised when draft ticket validation fails."""


@dataclass(slots=True)
class DraftTicketService:
    """Application service for managing draft tickets with JSON file storage.

    This service provides CRUD operations for draft tickets, which serve as
    a staging area for AI-proposed tickets before they are pushed to Jira.
    """

    _data_dir: Path | None = field(init=False, repr=False, default=None)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_data_dir", _resolve_data_dir())

    def _data_dir_path(self) -> Path:
        """Get the data directory path."""
        data_dir = self._data_dir
        if data_dir is None:
            data_dir = _resolve_data_dir()
            object.__setattr__(self, "_data_dir", data_dir)
        return data_dir

    def _storage_path(self) -> Path:
        """Get the path to the draft tickets JSON file."""
        return self._data_dir_path() / DRAFT_TICKETS_FILE

    def _load_tickets(self) -> list[DraftTicketEntity]:
        """Load all tickets from the JSON file."""
        path = self._storage_path()
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Failed to read draft tickets file", exc_info=True)
            return []

        tickets_data = payload.get("tickets")
        if not isinstance(tickets_data, list):
            return []

        tickets: list[DraftTicketEntity] = []
        for item in tickets_data:
            if isinstance(item, Mapping):
                try:
                    tickets.append(_deserialize_ticket(item))
                except Exception:
                    logger.debug("Skipping malformed draft ticket entry", exc_info=True)
        return tickets

    def _save_tickets(self, tickets: list[DraftTicketEntity]) -> None:
        """Save all tickets to the JSON file."""
        path = self._storage_path()
        payload = {
            "version": 1,
            "generated_at": _isoformat(_now_utc()),
            "ticket_count": len(tickets),
            "tickets": [_serialize_ticket(ticket) for ticket in tickets],
        }
        try:
            path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        except Exception:
            logger.warning("Failed to write draft tickets file", exc_info=True)
            raise

    def create(
        self,
        title: str,
        description: str | None = None,
        ai_proposal: dict[str, Any] | None = None,
        *,
        priority: str | DraftTicketPriority = DraftTicketPriority.MEDIUM,
        labels: list[str] | None = None,
        linked_jira_key: str | None = None,
        link_type: str | DraftTicketLinkType | None = None,
        source_context: dict[str, Any] | None = None,
    ) -> DraftTicketEntity:
        """Create a new draft ticket.

        Args:
            title: The suggested ticket title (required)
            description: The suggested ticket description
            ai_proposal: The AI's rationale and reasoning for this ticket
            priority: Priority level (low, medium, high, critical)
            labels: List of suggested labels
            linked_jira_key: Optional existing Jira key to link to
            link_type: Type of link (relates_to, blocks, subtask_of, duplicates)
            source_context: Optional metadata (server name, incident, conversation reference)

        Returns:
            The created draft ticket entity

        Raises:
            DraftTicketValidationError: If validation fails
        """
        cleaned_title = (title or "").strip()
        if not cleaned_title:
            raise DraftTicketValidationError("Title is required")

        # Parse priority
        if isinstance(priority, str):
            try:
                priority_enum = DraftTicketPriority(priority.lower())
            except ValueError:
                raise DraftTicketValidationError(
                    f"Invalid priority: {priority}. Must be one of: low, medium, high, critical"
                )
        else:
            priority_enum = priority

        # Parse link type
        link_type_enum: DraftTicketLinkType | None = None
        if link_type:
            if isinstance(link_type, str):
                try:
                    link_type_enum = DraftTicketLinkType(link_type.lower())
                except ValueError:
                    raise DraftTicketValidationError(
                        f"Invalid link type: {link_type}. Must be one of: relates_to, blocks, subtask_of, duplicates"
                    )
            else:
                link_type_enum = link_type

        now = _now_utc()
        ticket = DraftTicketEntity(
            id=str(uuid.uuid4()),
            suggested_title=cleaned_title,
            suggested_description=_normalize_text(description),
            suggested_priority=priority_enum,
            suggested_labels=tuple(str(label).strip() for label in (labels or []) if label),
            ai_proposal=ai_proposal or {},
            status=DraftTicketStatus.PROPOSED,
            linked_jira_key=_normalize_text(linked_jira_key),
            link_type=link_type_enum,
            source_context=source_context or {},
            created_at=now,
            updated_at=now,
        )

        with _FILE_LOCK:
            tickets = self._load_tickets()
            tickets.append(ticket)
            self._save_tickets(tickets)

        logger.info("Created draft ticket: %s", ticket.id)
        return ticket

    def get_by_id(self, ticket_id: str) -> DraftTicketEntity | None:
        """Get a draft ticket by ID.

        Args:
            ticket_id: The ticket UUID

        Returns:
            The draft ticket entity or None if not found
        """
        identifier = (ticket_id or "").strip()
        if not identifier:
            return None

        with _FILE_LOCK:
            tickets = self._load_tickets()
            for ticket in tickets:
                if ticket.id == identifier:
                    return ticket
        return None

    def list_all(self, status_filter: str | DraftTicketStatus | None = None) -> list[DraftTicketEntity]:
        """List all draft tickets, optionally filtered by status.

        Args:
            status_filter: Optional status to filter by

        Returns:
            List of draft ticket entities
        """
        with _FILE_LOCK:
            tickets = self._load_tickets()

        if status_filter is None:
            return tickets

        # Parse status filter
        if isinstance(status_filter, str):
            try:
                status_enum = DraftTicketStatus(status_filter.lower())
            except ValueError:
                return tickets
        else:
            status_enum = status_filter

        return [ticket for ticket in tickets if ticket.status == status_enum]

    def update(
        self,
        ticket_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        priority: str | DraftTicketPriority | None = None,
        labels: list[str] | None = None,
        ai_proposal: dict[str, Any] | None = None,
        source_context: dict[str, Any] | None = None,
    ) -> DraftTicketEntity:
        """Update a draft ticket's details.

        Args:
            ticket_id: The ticket UUID
            title: New title (optional)
            description: New description (optional)
            priority: New priority (optional)
            labels: New labels (optional)
            ai_proposal: New AI proposal (optional)
            source_context: New source context (optional)

        Returns:
            The updated draft ticket entity

        Raises:
            DraftTicketNotFoundError: If ticket not found
            DraftTicketValidationError: If validation fails
        """
        identifier = (ticket_id or "").strip()
        if not identifier:
            raise DraftTicketNotFoundError("Ticket ID is required")

        with _FILE_LOCK:
            tickets = self._load_tickets()
            ticket_index = None
            for i, ticket in enumerate(tickets):
                if ticket.id == identifier:
                    ticket_index = i
                    break

            if ticket_index is None:
                raise DraftTicketNotFoundError(f"Draft ticket not found: {identifier}")

            ticket = tickets[ticket_index]

            # Build updated ticket (dataclass is immutable with slots=True)
            new_title = ticket.suggested_title
            if title is not None:
                cleaned_title = title.strip()
                if not cleaned_title:
                    raise DraftTicketValidationError("Title cannot be empty")
                new_title = cleaned_title

            new_description = ticket.suggested_description
            if description is not None:
                new_description = _normalize_text(description)

            new_priority = ticket.suggested_priority
            if priority is not None:
                if isinstance(priority, str):
                    try:
                        new_priority = DraftTicketPriority(priority.lower())
                    except ValueError:
                        raise DraftTicketValidationError(
                            f"Invalid priority: {priority}. Must be one of: low, medium, high, critical"
                        )
                else:
                    new_priority = priority

            new_labels = ticket.suggested_labels
            if labels is not None:
                new_labels = tuple(str(label).strip() for label in labels if label)

            new_ai_proposal = ticket.ai_proposal
            if ai_proposal is not None:
                new_ai_proposal = ai_proposal

            new_source_context = ticket.source_context
            if source_context is not None:
                new_source_context = source_context

            updated_ticket = DraftTicketEntity(
                id=ticket.id,
                suggested_title=new_title,
                suggested_description=new_description,
                suggested_priority=new_priority,
                suggested_labels=new_labels,
                ai_proposal=new_ai_proposal,
                status=ticket.status,
                linked_jira_key=ticket.linked_jira_key,
                link_type=ticket.link_type,
                reviewed_by=ticket.reviewed_by,
                reviewed_at=ticket.reviewed_at,
                pushed_to_jira_at=ticket.pushed_to_jira_at,
                created_jira_key=ticket.created_jira_key,
                source_context=new_source_context,
                created_at=ticket.created_at,
                updated_at=_now_utc(),
            )

            tickets[ticket_index] = updated_ticket
            self._save_tickets(tickets)

        logger.info("Updated draft ticket: %s", updated_ticket.id)
        return updated_ticket

    def update_status(
        self,
        ticket_id: str,
        new_status: str | DraftTicketStatus,
        reviewed_by: str | None = None,
    ) -> DraftTicketEntity:
        """Update a draft ticket's status.

        Args:
            ticket_id: The ticket UUID
            new_status: The new status
            reviewed_by: Who reviewed the ticket (optional)

        Returns:
            The updated draft ticket entity

        Raises:
            DraftTicketNotFoundError: If ticket not found
            DraftTicketValidationError: If validation fails
        """
        identifier = (ticket_id or "").strip()
        if not identifier:
            raise DraftTicketNotFoundError("Ticket ID is required")

        # Parse status
        if isinstance(new_status, str):
            try:
                status_enum = DraftTicketStatus(new_status.lower())
            except ValueError:
                raise DraftTicketValidationError(
                    f"Invalid status: {new_status}. Must be one of: proposed, approved, pushed, rejected"
                )
        else:
            status_enum = new_status

        with _FILE_LOCK:
            tickets = self._load_tickets()
            ticket_index = None
            for i, ticket in enumerate(tickets):
                if ticket.id == identifier:
                    ticket_index = i
                    break

            if ticket_index is None:
                raise DraftTicketNotFoundError(f"Draft ticket not found: {identifier}")

            ticket = tickets[ticket_index]
            now = _now_utc()

            updated_ticket = DraftTicketEntity(
                id=ticket.id,
                suggested_title=ticket.suggested_title,
                suggested_description=ticket.suggested_description,
                suggested_priority=ticket.suggested_priority,
                suggested_labels=ticket.suggested_labels,
                ai_proposal=ticket.ai_proposal,
                status=status_enum,
                linked_jira_key=ticket.linked_jira_key,
                link_type=ticket.link_type,
                reviewed_by=_normalize_text(reviewed_by) or ticket.reviewed_by,
                reviewed_at=now if status_enum in (DraftTicketStatus.APPROVED, DraftTicketStatus.REJECTED) else ticket.reviewed_at,
                pushed_to_jira_at=ticket.pushed_to_jira_at,
                created_jira_key=ticket.created_jira_key,
                source_context=ticket.source_context,
                created_at=ticket.created_at,
                updated_at=now,
            )

            tickets[ticket_index] = updated_ticket
            self._save_tickets(tickets)

        logger.info("Updated draft ticket status: %s -> %s", updated_ticket.id, status_enum.value)
        return updated_ticket

    def link_to_jira(
        self,
        ticket_id: str,
        jira_key: str,
        link_type: str | DraftTicketLinkType = DraftTicketLinkType.RELATES_TO,
    ) -> DraftTicketEntity:
        """Link a draft ticket to an existing Jira issue.

        Args:
            ticket_id: The ticket UUID
            jira_key: The Jira issue key (e.g., "INFRA-1234")
            link_type: Type of link (relates_to, blocks, subtask_of, duplicates)

        Returns:
            The updated draft ticket entity

        Raises:
            DraftTicketNotFoundError: If ticket not found
            DraftTicketValidationError: If validation fails
        """
        identifier = (ticket_id or "").strip()
        if not identifier:
            raise DraftTicketNotFoundError("Ticket ID is required")

        cleaned_jira_key = (jira_key or "").strip().upper()
        if not cleaned_jira_key:
            raise DraftTicketValidationError("Jira key is required")

        # Parse link type
        if isinstance(link_type, str):
            try:
                link_type_enum = DraftTicketLinkType(link_type.lower())
            except ValueError:
                raise DraftTicketValidationError(
                    f"Invalid link type: {link_type}. Must be one of: relates_to, blocks, subtask_of, duplicates"
                )
        else:
            link_type_enum = link_type

        with _FILE_LOCK:
            tickets = self._load_tickets()
            ticket_index = None
            for i, ticket in enumerate(tickets):
                if ticket.id == identifier:
                    ticket_index = i
                    break

            if ticket_index is None:
                raise DraftTicketNotFoundError(f"Draft ticket not found: {identifier}")

            ticket = tickets[ticket_index]

            updated_ticket = DraftTicketEntity(
                id=ticket.id,
                suggested_title=ticket.suggested_title,
                suggested_description=ticket.suggested_description,
                suggested_priority=ticket.suggested_priority,
                suggested_labels=ticket.suggested_labels,
                ai_proposal=ticket.ai_proposal,
                status=ticket.status,
                linked_jira_key=cleaned_jira_key,
                link_type=link_type_enum,
                reviewed_by=ticket.reviewed_by,
                reviewed_at=ticket.reviewed_at,
                pushed_to_jira_at=ticket.pushed_to_jira_at,
                created_jira_key=ticket.created_jira_key,
                source_context=ticket.source_context,
                created_at=ticket.created_at,
                updated_at=_now_utc(),
            )

            tickets[ticket_index] = updated_ticket
            self._save_tickets(tickets)

        logger.info("Linked draft ticket %s to Jira %s", updated_ticket.id, cleaned_jira_key)
        return updated_ticket

    def mark_as_pushed(
        self,
        ticket_id: str,
        created_jira_key: str,
    ) -> DraftTicketEntity:
        """Mark a draft ticket as pushed to Jira.

        Args:
            ticket_id: The ticket UUID
            created_jira_key: The Jira issue key that was created

        Returns:
            The updated draft ticket entity

        Raises:
            DraftTicketNotFoundError: If ticket not found
            DraftTicketValidationError: If validation fails
        """
        identifier = (ticket_id or "").strip()
        if not identifier:
            raise DraftTicketNotFoundError("Ticket ID is required")

        cleaned_jira_key = (created_jira_key or "").strip().upper()
        if not cleaned_jira_key:
            raise DraftTicketValidationError("Created Jira key is required")

        with _FILE_LOCK:
            tickets = self._load_tickets()
            ticket_index = None
            for i, ticket in enumerate(tickets):
                if ticket.id == identifier:
                    ticket_index = i
                    break

            if ticket_index is None:
                raise DraftTicketNotFoundError(f"Draft ticket not found: {identifier}")

            ticket = tickets[ticket_index]
            now = _now_utc()

            updated_ticket = DraftTicketEntity(
                id=ticket.id,
                suggested_title=ticket.suggested_title,
                suggested_description=ticket.suggested_description,
                suggested_priority=ticket.suggested_priority,
                suggested_labels=ticket.suggested_labels,
                ai_proposal=ticket.ai_proposal,
                status=DraftTicketStatus.PUSHED,
                linked_jira_key=ticket.linked_jira_key,
                link_type=ticket.link_type,
                reviewed_by=ticket.reviewed_by,
                reviewed_at=ticket.reviewed_at,
                pushed_to_jira_at=now,
                created_jira_key=cleaned_jira_key,
                source_context=ticket.source_context,
                created_at=ticket.created_at,
                updated_at=now,
            )

            tickets[ticket_index] = updated_ticket
            self._save_tickets(tickets)

        logger.info("Marked draft ticket %s as pushed to Jira %s", updated_ticket.id, cleaned_jira_key)
        return updated_ticket

    def delete(self, ticket_id: str) -> bool:
        """Delete a draft ticket.

        Args:
            ticket_id: The ticket UUID

        Returns:
            True if deleted, False if not found
        """
        identifier = (ticket_id or "").strip()
        if not identifier:
            return False

        with _FILE_LOCK:
            tickets = self._load_tickets()
            original_count = len(tickets)
            tickets = [ticket for ticket in tickets if ticket.id != identifier]

            if len(tickets) == original_count:
                return False

            self._save_tickets(tickets)

        logger.info("Deleted draft ticket: %s", identifier)
        return True

    def search(self, query: str) -> list[DraftTicketEntity]:
        """Search draft tickets by keyword in title and description.

        Args:
            query: Search query string

        Returns:
            List of matching draft ticket entities
        """
        cleaned_query = (query or "").strip().lower()
        if not cleaned_query:
            return self.list_all()

        with _FILE_LOCK:
            tickets = self._load_tickets()

        results: list[DraftTicketEntity] = []
        for ticket in tickets:
            title_match = cleaned_query in ticket.suggested_title.lower()
            description_match = (
                ticket.suggested_description
                and cleaned_query in ticket.suggested_description.lower()
            )
            if title_match or description_match:
                results.append(ticket)

        return results

    def get_counts_by_status(self) -> dict[str, int]:
        """Get ticket counts grouped by status.

        Returns:
            Dictionary mapping status to count
        """
        with _FILE_LOCK:
            tickets = self._load_tickets()

        counts: dict[str, int] = {status.value: 0 for status in DraftTicketStatus}
        for ticket in tickets:
            counts[ticket.status.value] = counts.get(ticket.status.value, 0) + 1

        return counts


def create_draft_ticket_service() -> DraftTicketService:
    """Factory function to create a DraftTicketService instance."""
    return DraftTicketService()


__all__ = [
    "DraftTicketNotFoundError",
    "DraftTicketService",
    "DraftTicketValidationError",
    "create_draft_ticket_service",
]
