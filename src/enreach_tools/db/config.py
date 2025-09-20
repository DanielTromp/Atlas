from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from ..env import project_root

DEFAULT_SQLITE_FILENAME = "enreach.sqlite3"


def get_database_url() -> str:
    url = os.getenv("ENREACH_DB_URL", "").strip()
    if url:
        return url
    data_dir = project_root() / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / DEFAULT_SQLITE_FILENAME
    return f"sqlite:///{path.as_posix()}"


def get_engine(echo: bool | None = None) -> Engine:
    url = get_database_url()
    if echo is None:
        echo = os.getenv("SQLALCHEMY_ECHO", "").strip().lower() in {"1", "true", "yes", "on"}
    connect_args: dict[str, object] = {}
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    return create_engine(url, echo=echo, future=True, connect_args=connect_args)


def get_sessionmaker(*, engine: Engine | None = None) -> sessionmaker:
    engine = engine or get_engine()
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def ensure_sqlite_parent(path: Path) -> None:
    if path.suffix and path.parent:
        path.parent.mkdir(parents=True, exist_ok=True)
