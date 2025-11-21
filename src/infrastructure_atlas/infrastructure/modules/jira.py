"""Jira integration module."""

from __future__ import annotations

from .base import BaseModule, ModuleHealthStatus, ModuleMetadata


class JiraModule(BaseModule):
    """Atlassian Jira issue tracking integration module."""

    @property
    def metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name="jira",
            display_name="Jira",
            description="Atlassian Jira integration for issue tracking and ticketing",
            version="1.0.0",
            dependencies=frozenset(),
            required_env_vars=frozenset([
                "ATLASSIAN_BASE_URL",
                "ATLASSIAN_EMAIL",
                "ATLASSIAN_API_TOKEN",
            ]),
            optional_env_vars=frozenset(),
            category="integration",
        )

    def health_check(self) -> ModuleHealthStatus:
        """Check Jira API connectivity."""
        from .base import ModuleHealth

        # First check base validation
        status = super().health_check()
        if status.status != ModuleHealth.HEALTHY:
            return status

        # Try to connect to Jira API
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
                    message="Jira credentials not configured",
                )

            response = requests.get(
                f"{url.rstrip('/')}/rest/api/3/myself",
                auth=HTTPBasicAuth(email, token),
                timeout=5,
            )

            if response.status_code == 200:
                data = response.json()
                display_name = data.get("displayName", "unknown")
                return ModuleHealthStatus(
                    status=ModuleHealth.HEALTHY,
                    message=f"Jira API is accessible (user: {display_name})",
                )
            else:
                return ModuleHealthStatus(
                    status=ModuleHealth.DEGRADED,
                    message=f"Jira API returned status {response.status_code}",
                )

        except Exception as e:
            return ModuleHealthStatus(
                status=ModuleHealth.UNHEALTHY,
                message=f"Failed to connect to Jira API: {e}",
            )
