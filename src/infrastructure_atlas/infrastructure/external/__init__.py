"""External service adapters (NetBox, Confluence, backups, Zabbix)."""

from .backup_provider import BackupProvider
from .commvault_client import (
    CommvaultAuthError,
    CommvaultClient,
    CommvaultClientConfig,
    CommvaultConfigError,
    CommvaultError,
    CommvaultJobQuery,
    CommvaultResponseError,
)
from .confluence_client import ConfluenceClient, ConfluenceClientConfig
from .foreman_client import (
    ForemanAPIError,
    ForemanAuthError,
    ForemanClient,
    ForemanClientConfig,
    ForemanClientError,
)
from .netbox_client import NetboxClient, NetboxClientConfig
from .vcenter_client import (
    VCenterAPIError,
    VCenterAuthError,
    VCenterClient,
    VCenterClientConfig,
    VCenterClientError,
)
from .zabbix_client import (
    ZabbixAuthError,
    ZabbixClient,
    ZabbixClientConfig,
    ZabbixConfigError,
    ZabbixError,
)

__all__ = [
    "BackupProvider",
    "CommvaultAuthError",
    "CommvaultClient",
    "CommvaultClientConfig",
    "CommvaultConfigError",
    "CommvaultError",
    "CommvaultJobQuery",
    "CommvaultResponseError",
    "ConfluenceClient",
    "ConfluenceClientConfig",
    "ForemanAPIError",
    "ForemanAuthError",
    "ForemanClient",
    "ForemanClientConfig",
    "ForemanClientError",
    "NetboxClient",
    "NetboxClientConfig",
    "VCenterAPIError",
    "VCenterAuthError",
    "VCenterClient",
    "VCenterClientConfig",
    "VCenterClientError",
    "ZabbixAuthError",
    "ZabbixClient",
    "ZabbixClientConfig",
    "ZabbixConfigError",
    "ZabbixError",
]
