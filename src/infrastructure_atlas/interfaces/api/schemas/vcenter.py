"""Pydantic request models for vCenter endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class VCenterConfigCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    base_url: str = Field(..., min_length=1)
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    verify_ssl: bool = True
    is_esxi: bool = False


class VCenterConfigUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    base_url: str | None = Field(default=None, min_length=1)
    username: str | None = Field(default=None, min_length=1)
    password: str | None = Field(default=None, min_length=1)
    verify_ssl: bool | None = None
    is_esxi: bool | None = None


__all__ = ["VCenterConfigCreate", "VCenterConfigUpdate"]
