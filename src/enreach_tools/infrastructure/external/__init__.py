"""External service adapters (NetBox, Confluence, backups, Zabbix)."""

from .backup_provider import BackupProvider
from .confluence_client import ConfluenceClient, ConfluenceClientConfig
from .netbox_client import NetboxClient, NetboxClientConfig
from .zabbix_client import (
    ZabbixAuthError,
    ZabbixClient,
    ZabbixClientConfig,
    ZabbixConfigError,
    ZabbixError,
)

__all__ = [
    "BackupProvider",
    "ConfluenceClient",
    "ConfluenceClientConfig",
    "NetboxClient",
    "NetboxClientConfig",
    "ZabbixAuthError",
    "ZabbixClient",
    "ZabbixClientConfig",
    "ZabbixConfigError",
    "ZabbixError",
]
