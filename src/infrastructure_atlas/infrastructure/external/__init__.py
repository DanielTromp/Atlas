"""External service adapters (NetBox, Confluence, backups, Zabbix, Git, Puppet)."""

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
from .esxi_client import ESXiClient
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
from .git_client import (
    GitAuthError,
    GitClient,
    GitClientConfig,
    GitClientError,
    GitCloneError,
    GitPullError,
    GitRepoInfo,
)
from .puppet_parser import (
    PuppetGroup,
    PuppetInventory,
    PuppetParser,
    PuppetUser,
    PuppetUserAccess,
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
    "ESXiClient",
    "ForemanAPIError",
    "ForemanAuthError",
    "ForemanClient",
    "ForemanClientConfig",
    "ForemanClientError",
    "GitAuthError",
    "GitClient",
    "GitClientConfig",
    "GitClientError",
    "GitCloneError",
    "GitPullError",
    "GitRepoInfo",
    "NetboxClient",
    "NetboxClientConfig",
    "PuppetGroup",
    "PuppetInventory",
    "PuppetParser",
    "PuppetUser",
    "PuppetUserAccess",
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
