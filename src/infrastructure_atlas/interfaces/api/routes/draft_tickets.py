"""API endpoints for draft ticket management.

Draft tickets are AI-proposed tickets that can be reviewed, approved, and pushed to Jira.
They serve as a staging area for ticket proposals before they become official Jira issues.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from infrastructure_atlas.application.dto.draft_tickets import (
    DraftTicketCountsDTO,
    DraftTicketCreateDTO,
    DraftTicketDTO,
    DraftTicketLinkDTO,
    DraftTicketPushDTO,
    DraftTicketStatusUpdateDTO,
    DraftTicketUpdateDTO,
    counts_to_dto,
    draft_ticket_to_dto,
    draft_tickets_to_dto,
)
from infrastructure_atlas.application.services import (
    DraftTicketNotFoundError,
    DraftTicketService,
    DraftTicketValidationError,
    create_draft_ticket_service,
)
from infrastructure_atlas.interfaces.api.dependencies import OptionalUserDep

router = APIRouter(prefix="/draft-tickets", tags=["draft-tickets"])


def get_draft_ticket_service() -> DraftTicketService:
    """Dependency to get the draft ticket service."""
    return create_draft_ticket_service()


DraftTicketServiceDep = Annotated[DraftTicketService, Depends(get_draft_ticket_service)]
CreateBody = Annotated[DraftTicketCreateDTO, Body(...)]
UpdateBody = Annotated[DraftTicketUpdateDTO, Body(...)]
StatusBody = Annotated[DraftTicketStatusUpdateDTO, Body(...)]
LinkBody = Annotated[DraftTicketLinkDTO, Body(...)]
PushBody = Annotated[DraftTicketPushDTO, Body(...)]


@router.get("/counts", response_model=DraftTicketCountsDTO)
def get_ticket_counts(
    user: OptionalUserDep,
    service: DraftTicketServiceDep,
) -> dict:
    """Get ticket counts grouped by status.

    Returns counts for proposed, approved, pushed, rejected, and total.
    """
    counts = service.get_counts_by_status()
    return counts_to_dto(counts).dict_clean()


@router.get("", response_model=list[DraftTicketDTO])
def list_tickets(
    user: OptionalUserDep,
    service: DraftTicketServiceDep,
    status: str | None = Query(
        default=None,
        description="Filter by status (proposed, approved, pushed, rejected)",
    ),
    q: str | None = Query(
        default=None,
        description="Search query (searches title and description)",
    ),
) -> list[dict]:
    """List all draft tickets.

    Optionally filter by status or search by keyword.
    """
    if q:
        tickets = service.search(q)
        # Also apply status filter if provided
        if status:
            tickets = [t for t in tickets if t.status.value == status.lower()]
    else:
        tickets = service.list_all(status_filter=status)

    return [dto.dict_clean() for dto in draft_tickets_to_dto(tickets)]


@router.post("", response_model=DraftTicketDTO, status_code=201)
def create_ticket(
    user: OptionalUserDep,
    payload: CreateBody,
    service: DraftTicketServiceDep,
) -> dict:
    """Create a new draft ticket.

    Draft tickets start in 'proposed' status and can be reviewed, approved, or rejected.
    """
    try:
        entity = service.create(
            title=payload.suggested_title,
            description=payload.suggested_description,
            ai_proposal=payload.ai_proposal,
            priority=payload.suggested_priority.value,
            labels=payload.suggested_labels,
            linked_jira_key=payload.linked_jira_key,
            link_type=payload.link_type.value if payload.link_type else None,
            source_context=payload.source_context,
        )
    except DraftTicketValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return draft_ticket_to_dto(entity).dict_clean()


@router.get("/{ticket_id}", response_model=DraftTicketDTO)
def get_ticket(
    ticket_id: str,
    user: OptionalUserDep,
    service: DraftTicketServiceDep,
) -> dict:
    """Get a single draft ticket by ID."""
    entity = service.get_by_id(ticket_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Draft ticket not found")

    return draft_ticket_to_dto(entity).dict_clean()


@router.patch("/{ticket_id}", response_model=DraftTicketDTO)
def update_ticket(
    ticket_id: str,
    payload: UpdateBody,
    user: OptionalUserDep,
    service: DraftTicketServiceDep,
) -> dict:
    """Update a draft ticket's details.

    Only the fields provided will be updated.
    """
    try:
        entity = service.update(
            ticket_id,
            title=payload.suggested_title,
            description=payload.suggested_description,
            priority=payload.suggested_priority.value if payload.suggested_priority else None,
            labels=payload.suggested_labels,
            ai_proposal=payload.ai_proposal,
            source_context=payload.source_context,
        )
    except DraftTicketNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DraftTicketValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return draft_ticket_to_dto(entity).dict_clean()


@router.patch("/{ticket_id}/status", response_model=DraftTicketDTO)
def update_ticket_status(
    ticket_id: str,
    payload: StatusBody,
    user: OptionalUserDep,
    service: DraftTicketServiceDep,
) -> dict:
    """Update a draft ticket's status.

    Use this to approve or reject a ticket.
    """
    try:
        entity = service.update_status(
            ticket_id,
            new_status=payload.status.value,
            reviewed_by=payload.reviewed_by or user.username,
        )
    except DraftTicketNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DraftTicketValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return draft_ticket_to_dto(entity).dict_clean()


@router.patch("/{ticket_id}/link", response_model=DraftTicketDTO)
def link_ticket_to_jira(
    ticket_id: str,
    payload: LinkBody,
    user: OptionalUserDep,
    service: DraftTicketServiceDep,
) -> dict:
    """Link a draft ticket to an existing Jira issue.

    This creates a relationship between the draft ticket and a Jira issue.
    """
    try:
        entity = service.link_to_jira(
            ticket_id,
            jira_key=payload.jira_key,
            link_type=payload.link_type.value,
        )
    except DraftTicketNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DraftTicketValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return draft_ticket_to_dto(entity).dict_clean()


@router.post("/{ticket_id}/push", response_model=DraftTicketDTO)
def push_ticket_to_jira(
    ticket_id: str,
    payload: PushBody,
    user: OptionalUserDep,
    service: DraftTicketServiceDep,
) -> dict:
    """Mark a draft ticket as pushed to Jira.

    This records that the ticket has been created in Jira and stores the created issue key.
    Note: This is a placeholder - actual Jira integration would push the ticket content.
    """
    try:
        entity = service.mark_as_pushed(
            ticket_id,
            created_jira_key=payload.created_jira_key,
        )
    except DraftTicketNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DraftTicketValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return draft_ticket_to_dto(entity).dict_clean()


@router.delete("/{ticket_id}")
def delete_ticket(
    ticket_id: str,
    user: OptionalUserDep,
    service: DraftTicketServiceDep,
) -> dict:
    """Delete a draft ticket."""
    removed = service.delete(ticket_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Draft ticket not found")

    return {"status": "deleted", "id": ticket_id}


__all__ = ["router"]
