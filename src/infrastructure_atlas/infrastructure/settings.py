"""Centralised settings loader bridging environment variables and runtime config."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from infrastructure_atlas.env import load_env


@dataclass(slots=True)
class Settings:
    """Immutable configuration snapshot for the application runtime."""

    log_level: str
    structured_logging: bool
    database_url: str

    @classmethod
    def from_env(cls) -> Settings:
        load_env()
        return cls(
            log_level=os.getenv("ATLAS_LOG_LEVEL", "INFO"),
            structured_logging=os.getenv("ATLAS_LOG_STRUCTURED", "").strip().lower() in {"1", "true", "yes", "on"},
            database_url=os.getenv("ATLAS_DB_URL", ""),
        )


@lru_cache(maxsize=1)
def load_settings() -> Settings:
    """Return a cached settings instance, reusing environment-derived values."""
    return Settings.from_env()


def as_dict(settings: Settings) -> dict[str, Any]:
    """Expose settings for templating/logging while keeping dataclass usage."""
    return {
        "log_level": settings.log_level,
        "structured_logging": settings.structured_logging,
        "database_url": settings.database_url,
    }


__all__ = ["Settings", "as_dict", "load_settings"]
