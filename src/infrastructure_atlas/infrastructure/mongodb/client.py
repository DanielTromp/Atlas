"""MongoDB connection manager with singleton pattern and connection pooling.

Provides both synchronous (pymongo) and asynchronous (motor) clients for MongoDB.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from infrastructure_atlas.infrastructure.logging import get_logger

logger = get_logger(__name__)

# Default configuration
DEFAULT_MONGODB_URI = "mongodb://localhost:27017"
DEFAULT_DATABASE = "atlas"
DEFAULT_CACHE_DATABASE = "atlas_cache"
DEFAULT_MAX_POOL_SIZE = 50
DEFAULT_MIN_POOL_SIZE = 10
# Reduced from 5000ms to 2000ms for faster startup; adjust via MONGODB_SERVER_SELECTION_TIMEOUT_MS
DEFAULT_SERVER_SELECTION_TIMEOUT_MS = 2000


@dataclass(frozen=True)
class MongoDBConfig:
    """Configuration for MongoDB connection."""

    uri: str
    database: str
    cache_database: str
    max_pool_size: int
    min_pool_size: int
    server_selection_timeout_ms: int

    @classmethod
    def from_env(cls) -> MongoDBConfig:
        """Create configuration from environment variables."""
        return cls(
            uri=os.getenv("MONGODB_URI", DEFAULT_MONGODB_URI),
            database=os.getenv("MONGODB_DATABASE", DEFAULT_DATABASE),
            cache_database=os.getenv("MONGODB_CACHE_DATABASE", DEFAULT_CACHE_DATABASE),
            max_pool_size=int(os.getenv("MONGODB_MAX_POOL_SIZE", str(DEFAULT_MAX_POOL_SIZE))),
            min_pool_size=int(os.getenv("MONGODB_MIN_POOL_SIZE", str(DEFAULT_MIN_POOL_SIZE))),
            server_selection_timeout_ms=int(
                os.getenv("MONGODB_SERVER_SELECTION_TIMEOUT_MS", str(DEFAULT_SERVER_SELECTION_TIMEOUT_MS))
            ),
        )


class MongoDBClient:
    """Singleton MongoDB client manager with lazy initialization.

    Supports both synchronous (pymongo) and asynchronous (motor) clients.
    Connection pooling is enabled with configurable pool sizes.
    """

    _instance: MongoDBClient | None = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self, config: MongoDBConfig | None = None) -> None:
        """Initialize the MongoDB client manager.

        Args:
            config: Optional configuration. If not provided, loads from environment.
        """
        self._config = config or MongoDBConfig.from_env()
        self._sync_client: MongoClient | None = None
        self._async_client: AsyncIOMotorClient | None = None
        self._sync_lock = threading.Lock()
        self._async_lock = threading.Lock()

    @classmethod
    def get_instance(cls, config: MongoDBConfig | None = None) -> MongoDBClient:
        """Get the singleton instance of MongoDBClient.

        Args:
            config: Optional configuration for first initialization.

        Returns:
            The singleton MongoDBClient instance.
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(config)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance. Useful for testing."""
        with cls._lock:
            if cls._instance is not None:
                cls._instance.close()
                cls._instance = None

    @property
    def config(self) -> MongoDBConfig:
        """Get the current configuration."""
        return self._config

    def _create_sync_client(self) -> MongoClient:
        """Create a synchronous MongoDB client."""
        return MongoClient(
            self._config.uri,
            maxPoolSize=self._config.max_pool_size,
            minPoolSize=self._config.min_pool_size,
            serverSelectionTimeoutMS=self._config.server_selection_timeout_ms,
        )

    def _create_async_client(self) -> AsyncIOMotorClient:
        """Create an asynchronous MongoDB client."""
        from motor.motor_asyncio import AsyncIOMotorClient

        return AsyncIOMotorClient(
            self._config.uri,
            maxPoolSize=self._config.max_pool_size,
            minPoolSize=self._config.min_pool_size,
            serverSelectionTimeoutMS=self._config.server_selection_timeout_ms,
        )

    @property
    def sync_client(self) -> MongoClient:
        """Get the synchronous MongoDB client (lazy initialization)."""
        if self._sync_client is None:
            with self._sync_lock:
                if self._sync_client is None:
                    self._sync_client = self._create_sync_client()
        return self._sync_client

    @property
    def async_client(self) -> AsyncIOMotorClient:
        """Get the asynchronous MongoDB client (lazy initialization)."""
        if self._async_client is None:
            with self._async_lock:
                if self._async_client is None:
                    self._async_client = self._create_async_client()
        return self._async_client

    @property
    def atlas(self) -> Database:
        """Get the main application database (synchronous)."""
        return self.sync_client[self._config.database]

    @property
    def atlas_cache(self) -> Database:
        """Get the cache database (synchronous)."""
        return self.sync_client[self._config.cache_database]

    @property
    def atlas_async(self) -> AsyncIOMotorDatabase:
        """Get the main application database (asynchronous)."""
        return self.async_client[self._config.database]

    @property
    def atlas_cache_async(self) -> AsyncIOMotorDatabase:
        """Get the cache database (asynchronous)."""
        return self.async_client[self._config.cache_database]

    def health_check(self) -> dict[str, bool | str]:
        """Perform a health check on the MongoDB connection.

        Returns:
            Dict with 'healthy' bool and optional 'error' message.
        """
        try:
            self.sync_client.admin.command("ping")
            return {"healthy": True}
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            logger.warning("MongoDB health check failed: %s", e)
            return {"healthy": False, "error": str(e)}
        except Exception as e:
            logger.exception("Unexpected error during MongoDB health check")
            return {"healthy": False, "error": str(e)}

    async def health_check_async(self) -> dict[str, bool | str]:
        """Perform an async health check on the MongoDB connection.

        Returns:
            Dict with 'healthy' bool and optional 'error' message.
        """
        try:
            await self.async_client.admin.command("ping")
            return {"healthy": True}
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            logger.warning("MongoDB async health check failed: %s", e)
            return {"healthy": False, "error": str(e)}
        except Exception as e:
            logger.exception("Unexpected error during MongoDB async health check")
            return {"healthy": False, "error": str(e)}

    def close(self) -> None:
        """Close all MongoDB connections."""
        with self._sync_lock:
            if self._sync_client is not None:
                self._sync_client.close()
                self._sync_client = None
        with self._async_lock:
            if self._async_client is not None:
                self._async_client.close()
                self._async_client = None

    def __enter__(self) -> MongoDBClient:
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - closes connections."""
        self.close()


def get_mongodb_client(config: MongoDBConfig | None = None) -> MongoDBClient:
    """Get the singleton MongoDB client instance.

    This is the recommended way to get a MongoDB client in the application.

    Args:
        config: Optional configuration for first initialization.

    Returns:
        The singleton MongoDBClient instance.
    """
    return MongoDBClient.get_instance(config)


def get_async_mongodb_client(config: MongoDBConfig | None = None) -> MongoDBClient:
    """Get the singleton MongoDB client instance for async operations.

    Same as get_mongodb_client but semantically named for async contexts.

    Args:
        config: Optional configuration for first initialization.

    Returns:
        The singleton MongoDBClient instance.
    """
    return MongoDBClient.get_instance(config)


__all__ = [
    "MongoDBClient",
    "MongoDBConfig",
    "get_mongodb_client",
    "get_async_mongodb_client",
]
