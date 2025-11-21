"""Commvault integration module."""

from __future__ import annotations

from .base import BaseModule, ModuleHealthStatus, ModuleMetadata


class CommvaultModule(BaseModule):
    """Commvault backup and data protection integration module."""

    @property
    def metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name="commvault",
            display_name="Commvault",
            description="Commvault backup system integration for VM protection status",
            version="1.0.0",
            dependencies=frozenset(),
            required_env_vars=frozenset(["COMMVAULT_BASE_URL", "COMMVAULT_API_TOKEN"]),
            optional_env_vars=frozenset(["COMMVAULT_JOB_CACHE_TTL"]),
            category="integration",
        )

    def health_check(self) -> ModuleHealthStatus:
        """Check Commvault API connectivity."""
        from .base import ModuleHealth

        # First check base validation
        status = super().health_check()
        if status.status != ModuleHealth.HEALTHY:
            return status

        # Try to connect to Commvault API
        try:
            import os
            import requests

            url = os.getenv("COMMVAULT_BASE_URL")
            token = os.getenv("COMMVAULT_API_TOKEN")

            if not url or not token:
                return ModuleHealthStatus(
                    status=ModuleHealth.UNHEALTHY,
                    message="Commvault URL or token not configured",
                )

            response = requests.get(
                f"{url.rstrip('/')}/webconsole/api/v2/CommServ",
                headers={"Authtoken": token},
                timeout=5,
            )

            if response.status_code == 200:
                return ModuleHealthStatus(
                    status=ModuleHealth.HEALTHY,
                    message="Commvault API is accessible",
                )
            else:
                return ModuleHealthStatus(
                    status=ModuleHealth.DEGRADED,
                    message=f"Commvault API returned status {response.status_code}",
                )

        except Exception as e:
            return ModuleHealthStatus(
                status=ModuleHealth.UNHEALTHY,
                message=f"Failed to connect to Commvault API: {e}",
            )
