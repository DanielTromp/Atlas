"""Module system for managing Atlas integrations."""

from .base import (
    BaseModule,
    Module,
    ModuleConfigurationError,
    ModuleDependencyError,
    ModuleDisabledError,
    ModuleError,
    ModuleHealth,
    ModuleHealthStatus,
    ModuleMetadata,
    ModuleNotFoundError,
)
from .commvault import CommvaultModule
from .confluence import ConfluenceModule
from .jira import JiraModule
from .loader import initialize_modules, register_all_modules
from .netbox import NetBoxModule
from .puppet import PuppetModule
from .registry import ModuleRegistry, get_module_registry, reset_module_registry
from .vcenter import VCenterModule
from .zabbix import ZabbixModule

__all__ = [
    # Base
    "Module",
    "BaseModule",
    "ModuleMetadata",
    "ModuleHealth",
    "ModuleHealthStatus",
    # Exceptions
    "ModuleError",
    "ModuleNotFoundError",
    "ModuleDisabledError",
    "ModuleDependencyError",
    "ModuleConfigurationError",
    # Registry
    "ModuleRegistry",
    "get_module_registry",
    "reset_module_registry",
    # Loader
    "initialize_modules",
    "register_all_modules",
    # Module implementations
    "NetBoxModule",
    "VCenterModule",
    "CommvaultModule",
    "ZabbixModule",
    "JiraModule",
    "ConfluenceModule",
    "PuppetModule",
]
