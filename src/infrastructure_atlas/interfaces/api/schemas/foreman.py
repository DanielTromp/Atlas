"""Pydantic request models for Foreman endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ForemanConfigCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    base_url: str = Field(..., min_length=1)
    username: str = Field(..., min_length=1)
    token: str = Field(..., min_length=1)
    verify_ssl: bool = True


class ForemanConfigUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    base_url: str | None = Field(default=None, min_length=1)
    username: str | None = Field(default=None, min_length=1)
    token: str | None = Field(default=None, min_length=1)
    verify_ssl: bool | None = None


__all__ = ["ForemanConfigCreate", "ForemanConfigUpdate"]
