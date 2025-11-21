"""Zabbix integration module."""

from __future__ import annotations

from .base import BaseModule, ModuleHealthStatus, ModuleMetadata


class ZabbixModule(BaseModule):
    """Zabbix monitoring platform integration module."""

    @property
    def metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name="zabbix",
            display_name="Zabbix",
            description="Zabbix monitoring integration for infrastructure alerts and metrics",
            version="1.0.0",
            dependencies=frozenset(),
            required_env_vars=frozenset(["ZABBIX_API_URL", "ZABBIX_API_TOKEN"]),
            optional_env_vars=frozenset([
                "ZABBIX_HOST",
                "ZABBIX_WEB_URL",
                "ZABBIX_SEVERITIES",
                "ZABBIX_GROUP_ID",
                "ZABBIX_EXCLUDE_GROUP_PATTERNS",
            ]),
            category="integration",
        )

    def health_check(self) -> ModuleHealthStatus:
        """Check Zabbix API connectivity."""
        from .base import ModuleHealth

        # First check base validation
        status = super().health_check()
        if status.status != ModuleHealth.HEALTHY:
            return status

        # Try to connect to Zabbix API
        try:
            import os
            import requests

            url = os.getenv("ZABBIX_API_URL")
            token = os.getenv("ZABBIX_API_TOKEN")

            if not url or not token:
                return ModuleHealthStatus(
                    status=ModuleHealth.UNHEALTHY,
                    message="Zabbix API URL or token not configured",
                )

            response = requests.post(
                url,
                json={
                    "jsonrpc": "2.0",
                    "method": "apiinfo.version",
                    "params": {},
                    "id": 1,
                },
                headers={"Authorization": f"Bearer {token}"},
                timeout=5,
            )

            if response.status_code == 200:
                data = response.json()
                version = data.get("result", "unknown")
                return ModuleHealthStatus(
                    status=ModuleHealth.HEALTHY,
                    message=f"Zabbix API is accessible (version {version})",
                    details={"version": version},
                )
            else:
                return ModuleHealthStatus(
                    status=ModuleHealth.DEGRADED,
                    message=f"Zabbix API returned status {response.status_code}",
                )

        except Exception as e:
            return ModuleHealthStatus(
                status=ModuleHealth.UNHEALTHY,
                message=f"Failed to connect to Zabbix API: {e}",
            )
