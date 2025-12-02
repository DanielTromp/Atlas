"""Module loader for registering all Atlas integration modules."""

from __future__ import annotations

from infrastructure_atlas.infrastructure.logging import get_logger

from .commvault import CommvaultModule
from .confluence import ConfluenceModule
from .foreman import ForemanModule
from .jira import JiraModule
from .netbox import NetBoxModule
from .registry import ModuleRegistry, get_module_registry
from .vcenter import VCenterModule
from .zabbix import ZabbixModule

logger = get_logger(__name__)


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

    This function should be called once at application startup.

    Returns:
        The initialized module registry.
    """
    registry = register_all_modules()
    logger.info("Module system initialized")
    return registry
