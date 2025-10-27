"""Pydantic schemas for the tool catalogue API."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ToolParameter(BaseModel):
    """Describe a parameter supported by a tool."""

    model_config = ConfigDict(extra="forbid")

    name: str
    location: Literal["query", "path", "header", "body"] = "query"
    required: bool = False
    type: str | None = None
    description: str | None = None
    default: Any | None = None
    example: Any | None = None


class ToolLink(BaseModel):
    """Represent a related documentation link."""

    model_config = ConfigDict(extra="forbid")

    label: str
    url: str


class ToolDefinition(BaseModel):
    """Describe an AI tool that can be invoked through the API."""

    model_config = ConfigDict(extra="forbid")

    key: str
    name: str
    agent: str
    summary: str
    description: str
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET"
    path: str = Field(..., description="API path that should be called")
    tags: tuple[str, ...] = ()
    parameters: tuple[ToolParameter, ...] = ()
    ai_usage: str | None = Field(None, description="Short instruction aimed at AI agents")
    sample: dict[str, Any] | None = Field(None, description="Sample query or body payload")
    response_fields: tuple[str, ...] = Field(
        tuple(),
        description="Important fields in the response to highlight",
    )
    links: tuple[ToolLink, ...] = ()
    examples: tuple[str, ...] = Field(
        tuple(),
        description="Example natural-language prompts that use the tool",
    )


class ToolCatalog(BaseModel):
    """Response model that wraps the tool catalogue."""

    model_config = ConfigDict(extra="forbid")

    tools: tuple[ToolDefinition, ...]
