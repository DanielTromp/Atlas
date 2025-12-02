"""Foreman integration module."""
from __future__ import annotations

from .base import BaseModule, ModuleHealthStatus, ModuleMetadata


class ForemanModule(BaseModule):
    """Foreman infrastructure management platform integration module."""

    @property
    def metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name="foreman",
            display_name="Foreman",
            description="Foreman integration for host and hypervisor inventory management",
            version="1.0.0",
            dependencies=frozenset(),
            required_env_vars=frozenset([]),  # Credentials stored in DB via ForemanConfig
            optional_env_vars=frozenset(),
            category="integration",
            author="Atlas Team",
            documentation_url="https://theforeman.org/documentation.html",
            release_notes="Initial release with configuration management and host listing",
        )

    def health_check(self) -> ModuleHealthStatus:
        """Check Foreman configuration and connectivity."""
        from .base import ModuleHealth

        # First check base validation
        status = super().health_check()
        if status.status != ModuleHealth.HEALTHY:
            return status

        # Check if any Foreman configs exist in the database
        try:
            from infrastructure_atlas.db import get_sessionmaker
            from infrastructure_atlas.db.models import ForemanConfig

            Session = get_sessionmaker()
            with Session() as session:
                config_count = session.query(ForemanConfig).count()

                if config_count == 0:
                    return ModuleHealthStatus(
                        status=ModuleHealth.DEGRADED,
                        message="No Foreman configurations found",
                    )

                return ModuleHealthStatus(
                    status=ModuleHealth.HEALTHY,
                    message=f"{config_count} Foreman configuration(s) available",
                    details={"config_count": config_count},
                )

        except Exception as e:
            return ModuleHealthStatus(
                status=ModuleHealth.UNHEALTHY,
                message=f"Failed to check Foreman configurations: {e}",
            )

