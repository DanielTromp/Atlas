"""NetBox integration module."""

from __future__ import annotations

from .base import BaseModule, ModuleHealthStatus, ModuleMetadata


class NetBoxModule(BaseModule):
    """NetBox DCIM/IPAM integration module."""

    @property
    def metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name="netbox",
            display_name="NetBox",
            description="NetBox DCIM/IPAM integration for device and VM inventory",
            version="1.0.0",
            dependencies=frozenset(),
            required_env_vars=frozenset(["NETBOX_URL", "NETBOX_TOKEN"]),
            optional_env_vars=frozenset([
                "NETBOX_DATA_DIR",
                "NETBOX_DEBUG",
                "NETBOX_EXTRA_HEADERS",
                "NETBOX_XLSX_ORDER_FILE",
            ]),
            category="integration",
            author="Atlas Team",
            documentation_url="https://netbox.readthedocs.io/",
            release_notes="Initial release with device and VM export functionality",
        )

    def health_check(self) -> ModuleHealthStatus:
        """Check NetBox API connectivity."""
        from .base import ModuleHealth

        # First check base validation (config, enabled state)
        status = super().health_check()
        if status.status != ModuleHealth.HEALTHY:
            return status

        # Try to connect to NetBox API
        try:
            import os
            import requests

            url = os.getenv("NETBOX_URL")
            token = os.getenv("NETBOX_TOKEN")

            if not url or not token:
                return ModuleHealthStatus(
                    status=ModuleHealth.UNHEALTHY,
                    message="NetBox URL or token not configured",
                )

            response = requests.get(
                f"{url.rstrip('/')}/api/",
                headers={"Authorization": f"Token {token}"},
                timeout=5,
            )

            if response.status_code == 200:
                return ModuleHealthStatus(
                    status=ModuleHealth.HEALTHY,
                    message="NetBox API is accessible",
                )
            else:
                return ModuleHealthStatus(
                    status=ModuleHealth.DEGRADED,
                    message=f"NetBox API returned status {response.status_code}",
                )

        except Exception as e:
            return ModuleHealthStatus(
                status=ModuleHealth.UNHEALTHY,
                message=f"Failed to connect to NetBox API: {e}",
            )
