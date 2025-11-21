"""Confluence integration module."""

from __future__ import annotations

from .base import BaseModule, ModuleHealthStatus, ModuleMetadata


class ConfluenceModule(BaseModule):
    """Atlassian Confluence wiki integration module."""

    @property
    def metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name="confluence",
            display_name="Confluence",
            description="Atlassian Confluence integration for documentation and CMDB publishing",
            version="1.0.0",
            dependencies=frozenset(),  # Can optionally use NetBox data, but not required
            required_env_vars=frozenset([
                "ATLASSIAN_BASE_URL",
                "ATLASSIAN_EMAIL",
                "ATLASSIAN_API_TOKEN",
            ]),
            optional_env_vars=frozenset([
                "CONFLUENCE_CMDB_PAGE_ID",
                "CONFLUENCE_DEVICES_PAGE_ID",
                "CONFLUENCE_VMS_PAGE_ID",
                "CONFLUENCE_ENABLE_TABLE_FILTER",
                "CONFLUENCE_ENABLE_TABLE_SORT",
            ]),
            category="integration",
        )

    def health_check(self) -> ModuleHealthStatus:
        """Check Confluence API connectivity."""
        from .base import ModuleHealth

        # First check base validation
        status = super().health_check()
        if status.status != ModuleHealth.HEALTHY:
            return status

        # Try to connect to Confluence API
        try:
            import os
            import requests
            from requests.auth import HTTPBasicAuth

            url = os.getenv("ATLASSIAN_BASE_URL")
            email = os.getenv("ATLASSIAN_EMAIL")
            token = os.getenv("ATLASSIAN_API_TOKEN")

            if not url or not email or not token:
                return ModuleHealthStatus(
                    status=ModuleHealth.UNHEALTHY,
                    message="Confluence credentials not configured",
                )

            response = requests.get(
                f"{url.rstrip('/')}/wiki/rest/api/user/current",
                auth=HTTPBasicAuth(email, token),
                timeout=5,
            )

            if response.status_code == 200:
                data = response.json()
                display_name = data.get("displayName", "unknown")
                return ModuleHealthStatus(
                    status=ModuleHealth.HEALTHY,
                    message=f"Confluence API is accessible (user: {display_name})",
                )
            else:
                return ModuleHealthStatus(
                    status=ModuleHealth.DEGRADED,
                    message=f"Confluence API returned status {response.status_code}",
                )

        except Exception as e:
            return ModuleHealthStatus(
                status=ModuleHealth.UNHEALTHY,
                message=f"Failed to connect to Confluence API: {e}",
            )
