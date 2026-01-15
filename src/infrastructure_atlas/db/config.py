from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from ..env import project_root

DEFAULT_SQLITE_FILENAME = "atlas.sqlite3"


def get_database_url() -> str:
    url = os.getenv("ATLAS_DB_URL", "").strip()
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
        # Allow multi-threaded access and set a busy timeout
        connect_args = {"check_same_thread": False, "timeout": 30}

    # Use NullPool for SQLite to avoid connection pooling issues
    # Each request gets a fresh connection, avoiding stale connection problems
    pool_class = None
    if url.startswith("sqlite"):
        from sqlalchemy.pool import StaticPool
        pool_class = StaticPool

    engine = create_engine(
        url,
        echo=echo,
        future=True,
        connect_args=connect_args,
        poolclass=pool_class,
    )

    # Configure SQLite for better concurrent access
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            # WAL mode for better concurrent read/write
            cursor.execute("PRAGMA journal_mode=WAL")
            # Normal sync is faster and still safe with WAL
            cursor.execute("PRAGMA synchronous=NORMAL")
            # Increase cache size (negative = KB, so -64000 = 64MB)
            cursor.execute("PRAGMA cache_size=-64000")
            # Enable foreign keys
            cursor.execute("PRAGMA foreign_keys=ON")
            # Set busy timeout (30 seconds) to wait for locks instead of failing
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

    return engine


def get_sessionmaker(*, engine: Engine | None = None) -> sessionmaker:
    engine = engine or get_engine()
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def ensure_sqlite_parent(path: Path) -> None:
    if path.suffix and path.parent:
        path.parent.mkdir(parents=True, exist_ok=True)
