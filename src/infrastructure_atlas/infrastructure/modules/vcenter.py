"""vCenter integration module."""

from __future__ import annotations

from .base import BaseModule, ModuleHealthStatus, ModuleMetadata


class VCenterModule(BaseModule):
    """VMware vCenter virtualization platform integration module."""

    @property
    def metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name="vcenter",
            display_name="vCenter",
            description="VMware vCenter integration for VM inventory and management",
            version="1.0.0",
            dependencies=frozenset(),
            required_env_vars=frozenset([]),  # Credentials stored in DB via VCenterConfig
            optional_env_vars=frozenset(),
            category="integration",
        )

    def health_check(self) -> ModuleHealthStatus:
        """Check vCenter configuration and connectivity."""
        from .base import ModuleHealth

        # First check base validation
        status = super().health_check()
        if status.status != ModuleHealth.HEALTHY:
            return status

        # Check if any vCenter configs exist in the database
        try:
            from infrastructure_atlas.db import get_sessionmaker
            from infrastructure_atlas.db.models import VCenterConfig

            Session = get_sessionmaker()
            with Session() as session:
                config_count = session.query(VCenterConfig).count()

                if config_count == 0:
                    return ModuleHealthStatus(
                        status=ModuleHealth.DEGRADED,
                        message="No vCenter configurations found",
                    )

                return ModuleHealthStatus(
                    status=ModuleHealth.HEALTHY,
                    message=f"{config_count} vCenter configuration(s) available",
                    details={"config_count": config_count},
                )

        except Exception as e:
            return ModuleHealthStatus(
                status=ModuleHealth.UNHEALTHY,
                message=f"Failed to check vCenter configurations: {e}",
            )
