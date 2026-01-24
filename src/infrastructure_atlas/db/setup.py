from __future__ import annotations

import os

from alembic import command
from alembic.config import Config

from ..env import project_root
from ..infrastructure.logging import get_logger
from .config import get_database_url

logger = get_logger(__name__)


def _alembic_config() -> Config:
    root = project_root()
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", get_database_url())
    return cfg


def init_database() -> None:
    """Initialize the database (both SQLite and MongoDB if configured)."""
    backend = os.getenv("ATLAS_STORAGE_BACKEND", "mongodb").lower()

    if backend == "sqlite":
        # Run SQLite/Alembic migrations
        cfg = _alembic_config()
        command.upgrade(cfg, "head")
    else:
        # Initialize MongoDB
        init_mongodb()


def init_mongodb(skip_health_check: bool | None = None) -> None:
    """Initialize MongoDB: create indexes and run migrations.

    Args:
        skip_health_check: If True, skip the blocking health check at startup.
            Defaults to ATLAS_SKIP_DB_HEALTH_CHECK env var or False.
            Set to True for faster startup in production when MongoDB is known to be available.
    """
    if skip_health_check is None:
        skip_health_check = os.getenv("ATLAS_SKIP_DB_HEALTH_CHECK", "").lower() in ("1", "true", "yes")

    try:
        from infrastructure_atlas.infrastructure.mongodb import get_mongodb_client
        from infrastructure_atlas.infrastructure.mongodb.migrations import run_migrations

        logger.info("Initializing MongoDB%s...", " (skipping health check)" if skip_health_check else "")

        # Get client (lazy initialization)
        client = get_mongodb_client()

        if not skip_health_check:
            # Verify connection with health check
            health = client.health_check()
            if not health.get("healthy"):
                logger.warning("MongoDB is not available: %s", health.get("error"))
                logger.warning("Falling back to SQLite backend")
                os.environ["ATLAS_STORAGE_BACKEND"] = "sqlite"
                cfg = _alembic_config()
                command.upgrade(cfg, "head")
                return

        # Run MongoDB migrations
        records = run_migrations(client.atlas, client.atlas_cache)
        if records:
            logger.info("Applied %d MongoDB migrations", len(records))
        else:
            logger.debug("No pending MongoDB migrations")

    except ImportError as e:
        logger.warning("MongoDB dependencies not available: %s", e)
        logger.warning("Falling back to SQLite backend")
        os.environ["ATLAS_STORAGE_BACKEND"] = "sqlite"
        cfg = _alembic_config()
        command.upgrade(cfg, "head")
    except Exception as e:
        logger.exception("Failed to initialize MongoDB: %s", e)
        logger.warning("Falling back to SQLite backend")
        os.environ["ATLAS_STORAGE_BACKEND"] = "sqlite"
        cfg = _alembic_config()
        command.upgrade(cfg, "head")


def alembic_revision(message: str) -> None:
    cfg = _alembic_config()
    command.revision(cfg, message=message, autogenerate=True)


def alembic_downgrade(target: str) -> None:
    cfg = _alembic_config()
    command.downgrade(cfg, target)
