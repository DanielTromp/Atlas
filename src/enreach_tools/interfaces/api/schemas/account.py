"""Pydantic models shared across profile and admin routes."""
from __future__ import annotations

from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProfileUpdate(BaseModel):
    display_name: str | None = None
    email: str | None = None

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class PasswordChange(BaseModel):
    current_password: str | None = None
    new_password: str

    model_config = ConfigDict(extra="forbid")


class APIKeyPayload(BaseModel):
    secret: str
    label: str | None = None

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class AdminCreateUser(BaseModel):
    username: str
    password: str
    display_name: str | None = None
    email: str | None = None
    role: str = Field("member", min_length=1, max_length=32)

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    @field_validator("role")
    @classmethod
    def _normalise_role(cls, value: str) -> str:
        role = (value or "").strip().lower()
        if not role:
            raise ValueError("Role is required")
        if len(role) > 32:
            raise ValueError("Role must be at most 32 characters")
        return role


class AdminUpdateUser(BaseModel):
    display_name: str | None = None
    email: str | None = None
    role: str | None = None
    is_active: bool | None = None

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    @field_validator("role")
    @classmethod
    def _normalise_role(cls, value: str | None) -> str | None:
        if value is None:
            return None
        role = value.strip().lower()
        if not role:
            raise ValueError("Role cannot be empty")
        if len(role) > 32:
            raise ValueError("Role must be at most 32 characters")
        return role


class AdminSetPassword(BaseModel):
    new_password: str

    model_config = ConfigDict(extra="forbid")


class AdminRoleUpdate(BaseModel):
    label: str | None = None
    description: str | None = None
    permissions: list[str] = Field(default_factory=list)

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    @field_validator("permissions", mode="before")
    @classmethod
    def _normalise_permissions(cls, value: Iterable[str] | None) -> list[str]:
        if value is None:
            return []
        cleaned: list[str] = []
        for item in value:
            if item is None:
                continue
            text = str(item).strip()
            if not text:
                continue
            if text not in cleaned:
                cleaned.append(text)
        return cleaned


__all__ = [
    "APIKeyPayload",
    "AdminCreateUser",
    "AdminRoleUpdate",
    "AdminSetPassword",
    "AdminUpdateUser",
    "PasswordChange",
    "ProfileUpdate",
]
