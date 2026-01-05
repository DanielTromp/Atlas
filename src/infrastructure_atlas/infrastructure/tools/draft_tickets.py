"""LangChain tool wrappers for draft ticket operations.

These tools allow AI assistants to create, list, search, and manage draft tickets
that serve as a staging area for Jira ticket proposals.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from pydantic.v1 import BaseModel, Field, validator

from infrastructure_atlas.application.services import (
    DraftTicketNotFoundError,
    DraftTicketValidationError,
    create_draft_ticket_service,
)
from infrastructure_atlas.application.dto.draft_tickets import draft_ticket_to_dto

from .base import AtlasTool, ToolExecutionError

__all__ = [
    "DraftTicketCreateTool",
    "DraftTicketGetTool",
    "DraftTicketLinkJiraTool",
    "DraftTicketListTool",
    "DraftTicketSearchTool",
]


class _DraftTicketCreateArgs(BaseModel):
    """Arguments for creating a draft ticket."""

    title: str = Field(..., description="The suggested ticket title")
    description: str | None = Field(default=None, description="The suggested ticket description")
    priority: str = Field(default="medium", description="Priority level: low, medium, high, critical")
    labels: list[str] | None = Field(default=None, description="List of suggested labels")
    rationale: str | None = Field(default=None, description="AI's rationale for proposing this ticket")
    reasoning: str | None = Field(default=None, description="Additional reasoning or context")
    linked_jira_key: str | None = Field(default=None, description="Existing Jira key to link to")
    link_type: str | None = Field(default=None, description="Link type: relates_to, blocks, subtask_of, duplicates")
    server_name: str | None = Field(default=None, description="Related server name for source context")
    incident: str | None = Field(default=None, description="Related incident reference for source context")

    @validator("title")
    def _validate_title(cls, value: str) -> str:
        stripped = (value or "").strip()
        if not stripped:
            raise ValueError("Title is required")
        return stripped

    @validator("priority")
    def _validate_priority(cls, value: str) -> str:
        allowed = {"low", "medium", "high", "critical"}
        if value.lower() not in allowed:
            raise ValueError(f"Priority must be one of: {', '.join(allowed)}")
        return value.lower()


class _DraftTicketListArgs(BaseModel):
    """Arguments for listing draft tickets."""

    status: str | None = Field(default=None, description="Filter by status: proposed, approved, pushed, rejected")

    @validator("status")
    def _validate_status(cls, value: str | None) -> str | None:
        if value is None:
            return None
        allowed = {"proposed", "approved", "pushed", "rejected"}
        if value.lower() not in allowed:
            raise ValueError(f"Status must be one of: {', '.join(allowed)}")
        return value.lower()


class _DraftTicketGetArgs(BaseModel):
    """Arguments for getting a draft ticket."""

    ticket_id: str = Field(..., description="The draft ticket UUID")

    @validator("ticket_id")
    def _validate_ticket_id(cls, value: str) -> str:
        stripped = (value or "").strip()
        if not stripped:
            raise ValueError("Ticket ID is required")
        return stripped


class _DraftTicketSearchArgs(BaseModel):
    """Arguments for searching draft tickets."""

    query: str = Field(..., description="Search query to match against title and description")

    @validator("query")
    def _validate_query(cls, value: str) -> str:
        stripped = (value or "").strip()
        if not stripped:
            raise ValueError("Query is required")
        return stripped


class _DraftTicketLinkJiraArgs(BaseModel):
    """Arguments for linking a draft ticket to Jira."""

    ticket_id: str = Field(..., description="The draft ticket UUID")
    jira_key: str = Field(..., description="The Jira issue key (e.g., INFRA-1234)")
    link_type: str = Field(default="relates_to", description="Link type: relates_to, blocks, subtask_of, duplicates")

    @validator("ticket_id")
    def _validate_ticket_id(cls, value: str) -> str:
        stripped = (value or "").strip()
        if not stripped:
            raise ValueError("Ticket ID is required")
        return stripped

    @validator("jira_key")
    def _validate_jira_key(cls, value: str) -> str:
        stripped = (value or "").strip()
        if not stripped:
            raise ValueError("Jira key is required")
        return stripped.upper()


class DraftTicketCreateTool(AtlasTool):
    """Create a new draft ticket proposal."""

    name: ClassVar[str] = "draft_ticket_create"
    description: ClassVar[str] = (
        "Create a new draft ticket with AI-proposed content. "
        "Use this to stage ticket proposals for human review before pushing to Jira. "
        "Include your rationale and reasoning for the proposal."
    )
    args_schema: ClassVar[type[_DraftTicketCreateArgs]] = _DraftTicketCreateArgs

    def _run(self, **kwargs: Any) -> str:
        args = self.args_schema(**kwargs)

        # Build AI proposal from rationale and reasoning
        ai_proposal: dict[str, Any] = {}
        if args.rationale:
            ai_proposal["rationale"] = args.rationale
        if args.reasoning:
            ai_proposal["reasoning"] = args.reasoning

        # Build source context
        source_context: dict[str, Any] = {}
        if args.server_name:
            source_context["server_name"] = args.server_name
        if args.incident:
            source_context["incident"] = args.incident

        try:
            service = create_draft_ticket_service()
            entity = service.create(
                title=args.title,
                description=args.description,
                ai_proposal=ai_proposal if ai_proposal else None,
                priority=args.priority,
                labels=args.labels,
                linked_jira_key=args.linked_jira_key,
                link_type=args.link_type,
                source_context=source_context if source_context else None,
            )
            dto = draft_ticket_to_dto(entity)
            return json.dumps({
                "status": "success",
                "message": f"Created draft ticket: {entity.id}",
                "ticket": dto.dict_clean(),
            })
        except DraftTicketValidationError as exc:
            raise ToolExecutionError(f"Validation error: {exc}")
        except Exception as exc:
            raise self._handle_exception(exc)


class DraftTicketListTool(AtlasTool):
    """List draft tickets, optionally filtered by status."""

    name: ClassVar[str] = "draft_ticket_list"
    description: ClassVar[str] = (
        "List all draft tickets in the staging area. "
        "Optionally filter by status (proposed, approved, pushed, rejected)."
    )
    args_schema: ClassVar[type[_DraftTicketListArgs]] = _DraftTicketListArgs

    def _run(self, **kwargs: Any) -> str:
        args = self.args_schema(**kwargs)

        try:
            service = create_draft_ticket_service()
            entities = service.list_all(status_filter=args.status)
            counts = service.get_counts_by_status()

            tickets = []
            for entity in entities:
                dto = draft_ticket_to_dto(entity)
                tickets.append(dto.dict_clean())

            return json.dumps({
                "status": "success",
                "counts": counts,
                "total": len(tickets),
                "tickets": tickets,
            })
        except Exception as exc:
            raise self._handle_exception(exc)


class DraftTicketGetTool(AtlasTool):
    """Get details of a specific draft ticket."""

    name: ClassVar[str] = "draft_ticket_get"
    description: ClassVar[str] = (
        "Get the full details of a draft ticket by its ID. "
        "Returns all ticket information including AI proposal and source context."
    )
    args_schema: ClassVar[type[_DraftTicketGetArgs]] = _DraftTicketGetArgs

    def _run(self, **kwargs: Any) -> str:
        args = self.args_schema(**kwargs)

        try:
            service = create_draft_ticket_service()
            entity = service.get_by_id(args.ticket_id)

            if entity is None:
                return json.dumps({
                    "status": "not_found",
                    "message": f"Draft ticket not found: {args.ticket_id}",
                })

            dto = draft_ticket_to_dto(entity)
            return json.dumps({
                "status": "success",
                "ticket": dto.dict_clean(),
            })
        except Exception as exc:
            raise self._handle_exception(exc)


class DraftTicketSearchTool(AtlasTool):
    """Search draft tickets by keyword."""

    name: ClassVar[str] = "draft_ticket_search"
    description: ClassVar[str] = (
        "Search draft tickets by keyword in title and description. "
        "Returns matching tickets sorted by relevance."
    )
    args_schema: ClassVar[type[_DraftTicketSearchArgs]] = _DraftTicketSearchArgs

    def _run(self, **kwargs: Any) -> str:
        args = self.args_schema(**kwargs)

        try:
            service = create_draft_ticket_service()
            entities = service.search(args.query)

            tickets = []
            for entity in entities:
                dto = draft_ticket_to_dto(entity)
                tickets.append(dto.dict_clean())

            return json.dumps({
                "status": "success",
                "query": args.query,
                "total": len(tickets),
                "tickets": tickets,
            })
        except Exception as exc:
            raise self._handle_exception(exc)


class DraftTicketLinkJiraTool(AtlasTool):
    """Link a draft ticket to an existing Jira issue."""

    name: ClassVar[str] = "draft_ticket_link_jira"
    description: ClassVar[str] = (
        "Link a draft ticket to an existing Jira issue. "
        "Use this to associate a draft with a related ticket in Jira."
    )
    args_schema: ClassVar[type[_DraftTicketLinkJiraArgs]] = _DraftTicketLinkJiraArgs

    def _run(self, **kwargs: Any) -> str:
        args = self.args_schema(**kwargs)

        try:
            service = create_draft_ticket_service()
            entity = service.link_to_jira(
                ticket_id=args.ticket_id,
                jira_key=args.jira_key,
                link_type=args.link_type,
            )

            dto = draft_ticket_to_dto(entity)
            return json.dumps({
                "status": "success",
                "message": f"Linked draft ticket {entity.id} to {entity.linked_jira_key}",
                "ticket": dto.dict_clean(),
            })
        except DraftTicketNotFoundError as exc:
            return json.dumps({
                "status": "not_found",
                "message": str(exc),
            })
        except DraftTicketValidationError as exc:
            raise ToolExecutionError(f"Validation error: {exc}")
        except Exception as exc:
            raise self._handle_exception(exc)
