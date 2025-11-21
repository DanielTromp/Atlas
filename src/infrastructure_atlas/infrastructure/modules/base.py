"""Base module protocol and abstract classes for Atlas integrations.

This module defines the interface that all Atlas integration modules must implement,
providing lifecycle hooks, dependency management, and health checking capabilities.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol


class ModuleHealth(str, Enum):
    """Health status of a module."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ModuleHealthStatus:
    """Health status information for a module."""

    status: ModuleHealth
    message: str | None = None
    details: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class ModuleMetadata:
    """Metadata describing a module."""

    name: str
    display_name: str
    description: str
    version: str = "1.0.0"
    dependencies: frozenset[str] = field(default_factory=frozenset)
    required_env_vars: frozenset[str] = field(default_factory=frozenset)
    optional_env_vars: frozenset[str] = field(default_factory=frozenset)
    category: str = "integration"  # integration, utility, core

    # Documentation fields
    author: str = "Atlas Team"
    changelog_url: str | None = None
    documentation_url: str | None = None
    release_notes: str | None = None


class Module(Protocol):
    """Protocol defining the interface for Atlas modules.

    All integration modules must implement this protocol to be registered
    and managed by the module registry.
    """

    @property
    def metadata(self) -> ModuleMetadata:
        """Return module metadata."""
        ...

    def validate_config(self) -> tuple[bool, str | None]:
        """Validate module configuration.

        Returns:
            Tuple of (is_valid, error_message). error_message is None if valid.
        """
        ...

    def on_enable(self) -> None:
        """Hook called when module is enabled.

        Use this to initialize resources, register handlers, etc.
        Should be idempotent.
        """
        ...

    def on_disable(self) -> None:
        """Hook called when module is disabled.

        Use this to clean up resources, unregister handlers, etc.
        Should be idempotent.
        """
        ...

    def health_check(self) -> ModuleHealthStatus:
        """Check the health of the module.

        Returns:
            ModuleHealthStatus indicating current health state.
        """
        ...


class BaseModule(ABC):
    """Abstract base class for Atlas modules providing default implementations."""

    def __init__(self) -> None:
        """Initialize the base module."""
        self._enabled = False

    @property
    @abstractmethod
    def metadata(self) -> ModuleMetadata:
        """Return module metadata. Must be implemented by subclasses."""
        ...

    def validate_config(self) -> tuple[bool, str | None]:
        """Default validation checks for required environment variables.

        Subclasses can override to add custom validation logic.
        """
        import os

        missing_vars = [var for var in self.metadata.required_env_vars if not os.getenv(var)]

        if missing_vars:
            return False, f"Missing required environment variables: {', '.join(missing_vars)}"

        return True, None

    def on_enable(self) -> None:
        """Default enable hook. Subclasses can override for custom behavior."""
        self._enabled = True

    def on_disable(self) -> None:
        """Default disable hook. Subclasses can override for custom behavior."""
        self._enabled = False

    def health_check(self) -> ModuleHealthStatus:
        """Default health check. Subclasses should override for meaningful checks."""
        if not self._enabled:
            return ModuleHealthStatus(
                status=ModuleHealth.UNKNOWN, message="Module is not enabled"
            )

        is_valid, error_msg = self.validate_config()
        if not is_valid:
            return ModuleHealthStatus(
                status=ModuleHealth.UNHEALTHY,
                message=f"Configuration validation failed: {error_msg}",
            )

        return ModuleHealthStatus(status=ModuleHealth.HEALTHY, message="Module is operational")


class ModuleError(Exception):
    """Base exception for module-related errors."""

    pass


class ModuleNotFoundError(ModuleError):
    """Raised when a requested module is not found in the registry."""

    pass


class ModuleDisabledError(ModuleError):
    """Raised when attempting to use a disabled module."""

    pass


class ModuleDependencyError(ModuleError):
    """Raised when module dependencies are not satisfied."""

    pass


class ModuleConfigurationError(ModuleError):
    """Raised when module configuration is invalid."""

    pass
