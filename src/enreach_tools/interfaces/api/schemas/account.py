"""Pydantic models shared across profile and admin routes."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


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
    role: Literal["admin", "member"] = "member"

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class AdminUpdateUser(BaseModel):
    display_name: str | None = None
    email: str | None = None
    role: Literal["admin", "member"] | None = None
    is_active: bool | None = None

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class AdminSetPassword(BaseModel):
    new_password: str

    model_config = ConfigDict(extra="forbid")


__all__ = [
    "APIKeyPayload",
    "AdminCreateUser",
    "AdminSetPassword",
    "AdminUpdateUser",
    "PasswordChange",
    "ProfileUpdate",
]
