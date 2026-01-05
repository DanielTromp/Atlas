"""DTO helpers for draft ticket operations."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import Field

from infrastructure_atlas.application.dto.base import DomainModel
from infrastructure_atlas.domain.draft_tickets import (
    DraftTicketEntity,
    DraftTicketLinkType,
    DraftTicketPriority,
    DraftTicketStatus,
)


class DraftTicketStatusDTO(str, Enum):
    """Status lifecycle for draft tickets."""

    PROPOSED = "proposed"
    APPROVED = "approved"
    PUSHED = "pushed"
    REJECTED = "rejected"


class DraftTicketPriorityDTO(str, Enum):
    """Priority levels for draft tickets."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DraftTicketLinkTypeDTO(str, Enum):
    """Types of links between draft tickets and Jira issues."""

    RELATES_TO = "relates_to"
    BLOCKS = "blocks"
    SUBTASK_OF = "subtask_of"
    DUPLICATES = "duplicates"


class DraftTicketDTO(DomainModel):
    """Data transfer object for draft ticket responses."""

    id: str
    suggested_title: str
    suggested_description: str | None = None
    suggested_priority: DraftTicketPriorityDTO
    suggested_labels: list[str] = Field(default_factory=list)
    ai_proposal: dict[str, Any] = Field(default_factory=dict)
    status: DraftTicketStatusDTO
    linked_jira_key: str | None = None
    linked_jira_url: str | None = None
    link_type: DraftTicketLinkTypeDTO | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    pushed_to_jira_at: datetime | None = None
    created_jira_key: str | None = None
    created_jira_url: str | None = None
    source_context: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class DraftTicketCreateDTO(DomainModel):
    """Request body for creating a draft ticket."""

    suggested_title: str = Field(..., min_length=1, max_length=500, description="The suggested ticket title")
    suggested_description: str | None = Field(default=None, description="The suggested ticket description")
    suggested_priority: DraftTicketPriorityDTO = Field(
        default=DraftTicketPriorityDTO.MEDIUM, description="Priority level"
    )
    suggested_labels: list[str] = Field(default_factory=list, description="List of suggested labels")
    ai_proposal: dict[str, Any] = Field(
        default_factory=dict, description="The AI's rationale and reasoning for this ticket"
    )
    linked_jira_key: str | None = Field(default=None, description="Optional existing Jira key to link to")
    link_type: DraftTicketLinkTypeDTO | None = Field(default=None, description="Type of link to existing Jira issue")
    source_context: dict[str, Any] = Field(
        default_factory=dict, description="Optional metadata (server name, incident, conversation reference)"
    )


class DraftTicketUpdateDTO(DomainModel):
    """Request body for updating a draft ticket."""

    suggested_title: str | None = Field(default=None, min_length=1, max_length=500, description="New title")
    suggested_description: str | None = Field(default=None, description="New description")
    suggested_priority: DraftTicketPriorityDTO | None = Field(default=None, description="New priority")
    suggested_labels: list[str] | None = Field(default=None, description="New labels")
    ai_proposal: dict[str, Any] | None = Field(default=None, description="New AI proposal")
    source_context: dict[str, Any] | None = Field(default=None, description="New source context")


class DraftTicketStatusUpdateDTO(DomainModel):
    """Request body for updating draft ticket status."""

    status: DraftTicketStatusDTO = Field(..., description="New status (proposed, approved, pushed, rejected)")
    reviewed_by: str | None = Field(default=None, description="Name of the reviewer")


class DraftTicketLinkDTO(DomainModel):
    """Request body for linking a draft ticket to Jira."""

    jira_key: str = Field(..., min_length=1, description="Jira issue key (e.g., INFRA-1234)")
    link_type: DraftTicketLinkTypeDTO = Field(
        default=DraftTicketLinkTypeDTO.RELATES_TO,
        description="Type of link (relates_to, blocks, subtask_of, duplicates)",
    )


class DraftTicketPushDTO(DomainModel):
    """Request body for marking a draft ticket as pushed."""

    created_jira_key: str = Field(..., min_length=1, description="The Jira issue key that was created")


class DraftTicketCountsDTO(DomainModel):
    """Response body for ticket counts by status."""

    proposed: int = 0
    approved: int = 0
    pushed: int = 0
    rejected: int = 0
    total: int = 0


def draft_ticket_to_dto(entity: DraftTicketEntity) -> DraftTicketDTO:
    """Convert a draft ticket entity to a DTO."""
    return DraftTicketDTO(
        id=entity.id,
        suggested_title=entity.suggested_title,
        suggested_description=entity.suggested_description,
        suggested_priority=DraftTicketPriorityDTO(entity.suggested_priority.value),
        suggested_labels=list(entity.suggested_labels),
        ai_proposal=entity.ai_proposal,
        status=DraftTicketStatusDTO(entity.status.value),
        linked_jira_key=entity.linked_jira_key,
        linked_jira_url=entity.linked_jira_url,
        link_type=DraftTicketLinkTypeDTO(entity.link_type.value) if entity.link_type else None,
        reviewed_by=entity.reviewed_by,
        reviewed_at=entity.reviewed_at,
        pushed_to_jira_at=entity.pushed_to_jira_at,
        created_jira_key=entity.created_jira_key,
        created_jira_url=entity.created_jira_url,
        source_context=entity.source_context,
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


def draft_tickets_to_dto(entities: Iterable[DraftTicketEntity]) -> list[DraftTicketDTO]:
    """Convert a list of draft ticket entities to DTOs."""
    return [draft_ticket_to_dto(entity) for entity in entities]


def counts_to_dto(counts: dict[str, int]) -> DraftTicketCountsDTO:
    """Convert status counts to a DTO."""
    return DraftTicketCountsDTO(
        proposed=counts.get("proposed", 0),
        approved=counts.get("approved", 0),
        pushed=counts.get("pushed", 0),
        rejected=counts.get("rejected", 0),
        total=sum(counts.values()),
    )


__all__ = [
    "DraftTicketCountsDTO",
    "DraftTicketCreateDTO",
    "DraftTicketDTO",
    "DraftTicketLinkDTO",
    "DraftTicketLinkTypeDTO",
    "DraftTicketPriorityDTO",
    "DraftTicketPushDTO",
    "DraftTicketStatusDTO",
    "DraftTicketStatusUpdateDTO",
    "DraftTicketUpdateDTO",
    "counts_to_dto",
    "draft_ticket_to_dto",
    "draft_tickets_to_dto",
]
