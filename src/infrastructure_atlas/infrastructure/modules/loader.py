"""Module loader for registering all Atlas integration modules."""

from __future__ import annotations

from threading import Lock

from infrastructure_atlas.infrastructure.logging import get_logger

from .bots import BotsModule
from .commvault import CommvaultModule
from .confluence import ConfluenceModule
from .foreman import ForemanModule
from .jira import JiraModule
from .netbox import NetBoxModule
from .puppet import PuppetModule
from .registry import ModuleRegistry, get_module_registry
from .vcenter import VCenterModule
from .zabbix import ZabbixModule

logger = get_logger(__name__)

# Track initialization state to prevent duplicate registration
_initialized = False
_init_lock = Lock()


def register_all_modules(registry: ModuleRegistry | None = None) -> ModuleRegistry:
    """Register all Atlas integration modules with the registry.

    Args:
        registry: Optional registry instance. If None, uses the global registry.

    Returns:
        The registry with all modules registered.
    """
    if registry is None:
        registry = get_module_registry()

    modules = [
        NetBoxModule(),
        VCenterModule(),
        CommvaultModule(),
        ZabbixModule(),
        JiraModule(),
        ConfluenceModule(),
        ForemanModule(),
        PuppetModule(),
        BotsModule(),
    ]

    for module in modules:
        try:
            registry.register(module)
        except Exception as e:
            logger.error(
                "Failed to register module %s: %s",
                module.metadata.name,
                e,
                exc_info=True,
            )

    logger.info("Registered %d modules", len(modules))
    return registry


def initialize_modules() -> ModuleRegistry:
    """Initialize the module system.

    This function is safe to call multiple times; only the first call will
    actually register modules.

    Returns:
        The initialized module registry.
    """
    global _initialized
    with _init_lock:
        if _initialized:
            logger.debug("Module system already initialized, skipping")
            return get_module_registry()
        registry = register_all_modules()
        _initialized = True
        logger.info("Module system initialized")
        return registry


def reset_module_initialization() -> None:
    """Reset the initialization flag. Primarily for testing."""
    global _initialized
    with _init_lock:
        _initialized = False
