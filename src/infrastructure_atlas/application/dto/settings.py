"""DTOs for environment settings payloads."""
from __future__ import annotations

from .base import DomainModel


class EnvSettingDTO(DomainModel):
    key: str
    label: str
    secret: bool
    value: str | None = None
    has_value: bool
    placeholder: str | None = None
    placeholder_effective: str | None = None
    source: str
    default: str | None = None
    category: str


class BackupInfoDTO(DomainModel):
    enabled: bool
    configured: bool
    type: str
    target: str | None = None


class AdminEnvResponseDTO(DomainModel):
    settings: list[EnvSettingDTO]
    backup: BackupInfoDTO


__all__ = ["AdminEnvResponseDTO", "BackupInfoDTO", "EnvSettingDTO"]
