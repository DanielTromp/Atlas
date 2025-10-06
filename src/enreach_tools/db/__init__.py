"""Database helpers for Enreach Tools.

This module exposes the SQLAlchemy engine/session factory and core models so
the rest of the application can query user data. The initial scope is focused
on authentication and API key storage; additional tables can be layered in the
future.
"""

from __future__ import annotations

from .config import get_database_url, get_engine, get_sessionmaker
from .models import Base, GlobalAPIKey, SecureSetting, User, UserAPIKey
from .setup import init_database

__all__ = [
    "Base",
    "GlobalAPIKey",
    "SecureSetting",
    "User",
    "UserAPIKey",
    "get_database_url",
    "get_engine",
    "get_sessionmaker",
    "init_database",
]
