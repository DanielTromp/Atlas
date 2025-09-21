"""External service adapters (NetBox, Confluence, backups)."""

from .netbox_client import NetboxClient, NetboxClientConfig
from .confluence_client import ConfluenceClient, ConfluenceClientConfig
from .backup_provider import BackupProvider, BackupJobResult

__all__ = [
    "NetboxClient",
    "NetboxClientConfig",
    "ConfluenceClient",
    "ConfluenceClientConfig",
    "BackupProvider",
    "BackupJobResult",
]
