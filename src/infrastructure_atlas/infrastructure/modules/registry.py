"""Module registry for managing Atlas integration modules.

The registry maintains the catalog of available modules, tracks their enabled/disabled state,
and provides lifecycle management functionality.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from threading import RLock
from typing import TYPE_CHECKING

from infrastructure_atlas.infrastructure.logging import get_logger

from .base import (
    Module,
    ModuleDependencyError,
    ModuleDisabledError,
    ModuleHealthStatus,
    ModuleMetadata,
    ModuleNotFoundError,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = get_logger(__name__)


class ModuleRegistry:
    """Central registry for managing Atlas modules.

    The registry is responsible for:
    - Maintaining the catalog of available modules
    - Tracking enabled/disabled state
    - Validating module dependencies
    - Coordinating module lifecycle hooks
    - Providing module discovery and lookup
    """

    def __init__(self) -> None:
        """Initialize the module registry."""
        self._modules: dict[str, Module] = {}
        self._enabled_cache: dict[str, bool] = {}
        self._lock = RLock()
        self._db_session: Session | None = None

    def register(self, module: Module) -> None:
        """Register a module with the registry.

        Args:
            module: The module instance to register.

        Raises:
            ValueError: If a module with the same name is already registered.
        """
        with self._lock:
            name = module.metadata.name
            if name in self._modules:
                logger.warning("Module %s is already registered, replacing", name)

            self._modules[name] = module
            # Clear cache for this module
            self._enabled_cache.pop(name, None)
            logger.info("Registered module: %s", name)

    def unregister(self, module_name: str) -> None:
        """Unregister a module from the registry.

        Args:
            module_name: Name of the module to unregister.
        """
        with self._lock:
            if module_name in self._modules:
                # Disable before unregistering
                if self.is_enabled(module_name):
                    self.disable(module_name)

                del self._modules[module_name]
                self._enabled_cache.pop(module_name, None)
                logger.info("Unregistered module: %s", module_name)

    def get_module(self, module_name: str) -> Module:
        """Get a module by name.

        Args:
            module_name: Name of the module to retrieve.

        Returns:
            The requested module instance.

        Raises:
            ModuleNotFoundError: If the module is not registered.
        """
        with self._lock:
            if module_name not in self._modules:
                raise ModuleNotFoundError(f"Module '{module_name}' is not registered")
            return self._modules[module_name]

    def list_modules(self) -> list[ModuleMetadata]:
        """List all registered modules.

        Returns:
            List of module metadata for all registered modules.
        """
        with self._lock:
            return [module.metadata for module in self._modules.values()]

    def is_enabled(self, module_name: str) -> bool:
        """Check if a module is enabled.

        The enabled state is determined by (in priority order):
        1. Database configuration (if available)
        2. Environment variable ATLAS_MODULE_{NAME}_ENABLED
        3. Environment variable ATLAS_MODULES_ENABLED (comma-separated list)
        4. Default: True (all modules enabled by default)

        Args:
            module_name: Name of the module to check.

        Returns:
            True if the module is enabled, False otherwise.

        Raises:
            ModuleNotFoundError: If the module is not registered.
        """
        with self._lock:
            if module_name not in self._modules:
                raise ModuleNotFoundError(f"Module '{module_name}' is not registered")

            # Check cache first
            if module_name in self._enabled_cache:
                return self._enabled_cache[module_name]

            # 1. Check database (if available)
            if self._db_session:
                enabled = self._check_db_config(module_name)
                if enabled is not None:
                    self._enabled_cache[module_name] = enabled
                    return enabled

            # 2. Check per-module environment variable
            env_key = f"ATLAS_MODULE_{module_name.upper().replace('-', '_')}_ENABLED"
            env_value = os.getenv(env_key)
            if env_value is not None:
                enabled = env_value.strip().lower() in ("1", "true", "yes", "on")
                self._enabled_cache[module_name] = enabled
                return enabled

            # 3. Check global modules list
            modules_enabled = os.getenv("ATLAS_MODULES_ENABLED")
            if modules_enabled is not None:
                enabled_list = [m.strip() for m in modules_enabled.split(",") if m.strip()]
                enabled = module_name in enabled_list
                self._enabled_cache[module_name] = enabled
                return enabled

            # 4. Default: enabled
            self._enabled_cache[module_name] = True
            return True

    def enable(self, module_name: str, persist: bool = True) -> None:
        """Enable a module.

        Args:
            module_name: Name of the module to enable.
            persist: If True, persist the change to the database.

        Raises:
            ModuleNotFoundError: If the module is not registered.
            ModuleDependencyError: If module dependencies are not satisfied.
        """
        with self._lock:
            module = self.get_module(module_name)

            # Check dependencies
            for dep in module.metadata.dependencies:
                if not self.is_enabled(dep):
                    raise ModuleDependencyError(
                        f"Cannot enable '{module_name}': dependency '{dep}' is not enabled"
                    )

            # Validate configuration
            is_valid, error_msg = module.validate_config()
            if not is_valid:
                logger.warning(
                    "Module %s configuration validation failed: %s", module_name, error_msg
                )

            # Call lifecycle hook
            try:
                module.on_enable()
            except Exception as e:
                logger.error("Error enabling module %s: %s", module_name, e, exc_info=True)
                raise

            # Persist to database if requested
            if persist and self._db_session:
                self._update_db_config(module_name, enabled=True)

            # Update cache
            self._enabled_cache[module_name] = True
            logger.info("Enabled module: %s", module_name)

    def disable(self, module_name: str, persist: bool = True, force: bool = False) -> None:
        """Disable a module.

        Args:
            module_name: Name of the module to disable.
            persist: If True, persist the change to the database.
            force: If True, disable even if other modules depend on it.

        Raises:
            ModuleNotFoundError: If the module is not registered.
            ModuleDependencyError: If other enabled modules depend on this one (unless force=True).
        """
        with self._lock:
            module = self.get_module(module_name)

            # Check if other modules depend on this one
            if not force:
                dependent_modules = self._find_dependent_modules(module_name)
                if dependent_modules:
                    raise ModuleDependencyError(
                        f"Cannot disable '{module_name}': modules {dependent_modules} depend on it. "
                        f"Use force=True to override."
                    )

            # Call lifecycle hook
            try:
                module.on_disable()
            except Exception as e:
                logger.error("Error disabling module %s: %s", module_name, e, exc_info=True)
                raise

            # Persist to database if requested
            if persist and self._db_session:
                self._update_db_config(module_name, enabled=False)

            # Update cache
            self._enabled_cache[module_name] = False
            logger.info("Disabled module: %s", module_name)

    def require_enabled(self, module_name: str) -> None:
        """Ensure a module is enabled, raising an exception if not.

        Args:
            module_name: Name of the module to check.

        Raises:
            ModuleNotFoundError: If the module is not registered.
            ModuleDisabledError: If the module is disabled.
        """
        if not self.is_enabled(module_name):
            raise ModuleDisabledError(f"Module '{module_name}' is not enabled")

    def health_check(self, module_name: str) -> ModuleHealthStatus:
        """Check the health of a module.

        Args:
            module_name: Name of the module to check.

        Returns:
            ModuleHealthStatus indicating the health of the module.

        Raises:
            ModuleNotFoundError: If the module is not registered.
        """
        module = self.get_module(module_name)
        return module.health_check()

    def health_check_all(self) -> dict[str, ModuleHealthStatus]:
        """Check the health of all enabled modules.

        Returns:
            Dictionary mapping module names to their health status.
        """
        with self._lock:
            results = {}
            for name in self._modules:
                if self.is_enabled(name):
                    try:
                        results[name] = self.health_check(name)
                    except Exception as e:
                        from .base import ModuleHealth

                        results[name] = ModuleHealthStatus(
                            status=ModuleHealth.UNHEALTHY,
                            message=f"Health check failed: {e}",
                        )
            return results

    def clear_cache(self) -> None:
        """Clear the enabled state cache.

        This will force the next is_enabled() call to re-read from DB or env vars.
        """
        with self._lock:
            self._enabled_cache.clear()
            logger.debug("Cleared module enabled state cache")

    def set_db_session(self, session: Session | None) -> None:
        """Set the database session for persistence operations.

        Args:
            session: SQLAlchemy session to use for database operations.
        """
        with self._lock:
            self._db_session = session
            # Clear cache when session changes
            self.clear_cache()

    def _find_dependent_modules(self, module_name: str) -> list[str]:
        """Find all enabled modules that depend on the given module."""
        dependent = []
        for name, module in self._modules.items():
            if module_name in module.metadata.dependencies and self.is_enabled(name):
                dependent.append(name)
        return dependent

    def _check_db_config(self, module_name: str) -> bool | None:
        """Check module enabled state from database.

        Returns None if no database config exists for this module.
        """
        if not self._db_session:
            return None

        try:
            from infrastructure_atlas.db.models import ModuleConfig

            config = (
                self._db_session.query(ModuleConfig)
                .filter(ModuleConfig.module_name == module_name)
                .first()
            )

            if config:
                return config.enabled

        except Exception as e:
            logger.warning("Error reading module config from database: %s", e)

        return None

    def _update_db_config(self, module_name: str, enabled: bool) -> None:
        """Update module enabled state in database."""
        if not self._db_session:
            return

        try:
            from infrastructure_atlas.db.models import ModuleConfig

            config = (
                self._db_session.query(ModuleConfig)
                .filter(ModuleConfig.module_name == module_name)
                .first()
            )

            if config:
                config.enabled = enabled
            else:
                config = ModuleConfig(module_name=module_name, enabled=enabled)
                self._db_session.add(config)

            self._db_session.commit()

        except Exception as e:
            logger.error("Error updating module config in database: %s", e, exc_info=True)
            self._db_session.rollback()


# Global registry instance
_registry: ModuleRegistry | None = None
_registry_lock = RLock()


def get_module_registry() -> ModuleRegistry:
    """Get the global module registry instance.

    Returns:
        The global ModuleRegistry instance.
    """
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = ModuleRegistry()
        return _registry


def reset_module_registry() -> None:
    """Reset the global module registry.

    This is primarily useful for testing.
    """
    global _registry
    with _registry_lock:
        _registry = None
