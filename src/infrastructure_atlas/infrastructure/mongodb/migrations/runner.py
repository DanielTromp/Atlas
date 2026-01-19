"""MongoDB migration runner for Infrastructure Atlas.

Provides a simple migration framework for managing MongoDB schema changes
and data migrations.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from pymongo.collection import Collection
from pymongo.database import Database

from infrastructure_atlas.infrastructure.logging import get_logger

logger = get_logger(__name__)


class MigrationProtocol(Protocol):
    """Protocol for migration modules."""

    version: int
    description: str

    def upgrade(self, app_db: Database, cache_db: Database) -> dict[str, Any]:
        """Run the upgrade migration.

        Args:
            app_db: The main application database.
            cache_db: The cache database.

        Returns:
            Dict with migration results/stats.
        """
        ...

    def downgrade(self, app_db: Database, cache_db: Database) -> dict[str, Any]:
        """Run the downgrade migration (rollback).

        Args:
            app_db: The main application database.
            cache_db: The cache database.

        Returns:
            Dict with migration results/stats.
        """
        ...


@dataclass
class MigrationRecord:
    """Record of an applied migration."""

    version: int
    description: str
    applied_at: datetime
    status: str
    results: dict[str, Any]


class MigrationRunner:
    """Runs MongoDB migrations in order.

    Migrations are stored in the `versions` subdirectory as Python modules.
    Each module must define:
    - version: int (unique, sequential)
    - description: str
    - upgrade(app_db, cache_db) -> dict
    - downgrade(app_db, cache_db) -> dict
    """

    COLLECTION_NAME = "_migrations"

    def __init__(self, app_db: Database, cache_db: Database) -> None:
        """Initialize the migration runner.

        Args:
            app_db: The main application database.
            cache_db: The cache database.
        """
        self._app_db = app_db
        self._cache_db = cache_db
        self._migrations_collection: Collection = app_db[self.COLLECTION_NAME]
        self._migrations: dict[int, Any] = {}
        self._load_migrations()

    def _load_migrations(self) -> None:
        """Load all migration modules from the versions package."""
        versions_path = Path(__file__).parent / "versions"
        if not versions_path.exists():
            logger.warning("Migrations versions directory not found: %s", versions_path)
            return

        package_name = "infrastructure_atlas.infrastructure.mongodb.migrations.versions"

        try:
            versions_package = importlib.import_module(package_name)
        except ImportError:
            logger.warning("Could not import migrations versions package: %s", package_name)
            return

        for finder, name, ispkg in pkgutil.iter_modules(versions_package.__path__):  # type: ignore[attr-defined]
            if name.startswith("_"):
                continue
            try:
                module = importlib.import_module(f"{package_name}.{name}")
                if hasattr(module, "version") and hasattr(module, "upgrade"):
                    version = getattr(module, "version")
                    if isinstance(version, int):
                        self._migrations[version] = module
                        logger.debug("Loaded migration v%d: %s", version, getattr(module, "description", name))
            except Exception:
                logger.exception("Failed to load migration module: %s", name)

    def get_applied_versions(self) -> set[int]:
        """Get the set of already-applied migration versions."""
        cursor = self._migrations_collection.find({"status": "applied"}, {"version": 1})
        return {doc["version"] for doc in cursor}

    def get_pending_migrations(self) -> list[int]:
        """Get list of pending migration versions in order."""
        applied = self.get_applied_versions()
        pending = [v for v in sorted(self._migrations.keys()) if v not in applied]
        return pending

    def get_migration_history(self) -> list[MigrationRecord]:
        """Get the full migration history."""
        cursor = self._migrations_collection.find().sort("version", 1)
        records = []
        for doc in cursor:
            records.append(
                MigrationRecord(
                    version=doc["version"],
                    description=doc.get("description", ""),
                    applied_at=doc.get("applied_at", datetime.now(UTC)),
                    status=doc.get("status", "unknown"),
                    results=doc.get("results", {}),
                )
            )
        return records

    def run_migration(self, version: int) -> MigrationRecord:
        """Run a specific migration version.

        Args:
            version: The migration version to run.

        Returns:
            The migration record.

        Raises:
            ValueError: If the migration version is not found.
            RuntimeError: If the migration fails.
        """
        if version not in self._migrations:
            raise ValueError(f"Migration version {version} not found")

        module = self._migrations[version]
        description = getattr(module, "description", f"Migration v{version}")

        logger.info("Running migration v%d: %s", version, description)

        try:
            results = module.upgrade(self._app_db, self._cache_db)
            status = "applied"
        except Exception as e:
            logger.exception("Migration v%d failed", version)
            results = {"error": str(e)}
            status = "failed"
            raise RuntimeError(f"Migration v{version} failed: {e}") from e

        applied_at = datetime.now(UTC)
        self._migrations_collection.update_one(
            {"version": version},
            {
                "$set": {
                    "description": description,
                    "applied_at": applied_at,
                    "status": status,
                    "results": results,
                }
            },
            upsert=True,
        )

        record = MigrationRecord(
            version=version,
            description=description,
            applied_at=applied_at,
            status=status,
            results=results,
        )

        logger.info("Migration v%d completed with status: %s", version, status)
        return record

    def run_pending(self) -> list[MigrationRecord]:
        """Run all pending migrations in order.

        Returns:
            List of migration records for each applied migration.
        """
        pending = self.get_pending_migrations()
        if not pending:
            logger.info("No pending migrations to run")
            return []

        logger.info("Found %d pending migrations: %s", len(pending), pending)

        records = []
        for version in pending:
            record = self.run_migration(version)
            records.append(record)

        logger.info("Completed %d migrations", len(records))
        return records

    def rollback(self, version: int) -> MigrationRecord:
        """Rollback a specific migration.

        Args:
            version: The migration version to rollback.

        Returns:
            The migration record.

        Raises:
            ValueError: If the migration version is not found or not applied.
            RuntimeError: If the rollback fails.
        """
        if version not in self._migrations:
            raise ValueError(f"Migration version {version} not found")

        applied = self.get_applied_versions()
        if version not in applied:
            raise ValueError(f"Migration version {version} is not applied")

        module = self._migrations[version]
        description = getattr(module, "description", f"Migration v{version}")

        if not hasattr(module, "downgrade"):
            raise ValueError(f"Migration v{version} does not support rollback")

        logger.info("Rolling back migration v%d: %s", version, description)

        try:
            results = module.downgrade(self._app_db, self._cache_db)
            status = "rolled_back"
        except Exception as e:
            logger.exception("Rollback of migration v%d failed", version)
            results = {"error": str(e)}
            status = "rollback_failed"
            raise RuntimeError(f"Rollback of migration v{version} failed: {e}") from e

        applied_at = datetime.now(UTC)
        self._migrations_collection.update_one(
            {"version": version},
            {
                "$set": {
                    "status": status,
                    "rolled_back_at": applied_at,
                    "rollback_results": results,
                }
            },
        )

        record = MigrationRecord(
            version=version,
            description=description,
            applied_at=applied_at,
            status=status,
            results=results,
        )

        logger.info("Rollback of migration v%d completed with status: %s", version, status)
        return record


def run_migrations(app_db: Database, cache_db: Database) -> list[MigrationRecord]:
    """Convenience function to run all pending migrations.

    Args:
        app_db: The main application database.
        cache_db: The cache database.

    Returns:
        List of migration records for each applied migration.
    """
    runner = MigrationRunner(app_db, cache_db)
    return runner.run_pending()


__all__ = [
    "MigrationProtocol",
    "MigrationRecord",
    "MigrationRunner",
    "run_migrations",
]
