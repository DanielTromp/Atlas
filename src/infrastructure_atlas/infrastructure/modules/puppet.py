"""Puppet integration module."""
from __future__ import annotations

from .base import BaseModule, ModuleHealthStatus, ModuleMetadata


class PuppetModule(BaseModule):
    """Puppet Git repository integration module for user management visualization."""

    @property
    def metadata(self) -> ModuleMetadata:
        return ModuleMetadata(
            name="puppet",
            display_name="Puppet",
            description="Puppet Git repository integration for Linux user and group management visualization",
            version="1.0.0",
            dependencies=frozenset(),
            required_env_vars=frozenset([]),  # Credentials stored in DB via PuppetConfig
            optional_env_vars=frozenset(["PUPPET_CACHE_DIR"]),
            category="integration",
            author="Atlas Team",
            documentation_url="https://puppet.com/docs/puppet/latest/",
            release_notes="Initial release with user, group, and access rights visualization",
        )

    def health_check(self) -> ModuleHealthStatus:
        """Check Puppet configuration and Git availability."""
        from .base import ModuleHealth

        # First check base validation
        status = super().health_check()
        if status.status != ModuleHealth.HEALTHY:
            return status

        # Check if Git is available
        import shutil

        if not shutil.which("git"):
            return ModuleHealthStatus(
                status=ModuleHealth.UNHEALTHY,
                message="Git is not installed or not in PATH",
            )

        # Check if any Puppet configs exist in the database
        try:
            from infrastructure_atlas.db import get_sessionmaker
            from infrastructure_atlas.db.models import PuppetConfig

            Session = get_sessionmaker()
            with Session() as session:
                config_count = session.query(PuppetConfig).count()

                if config_count == 0:
                    return ModuleHealthStatus(
                        status=ModuleHealth.DEGRADED,
                        message="No Puppet configurations found",
                    )

                return ModuleHealthStatus(
                    status=ModuleHealth.HEALTHY,
                    message=f"{config_count} Puppet configuration(s) available",
                    details={"config_count": config_count},
                )

        except Exception as e:
            return ModuleHealthStatus(
                status=ModuleHealth.UNHEALTHY,
                message=f"Failed to check Puppet configurations: {e}",
            )


