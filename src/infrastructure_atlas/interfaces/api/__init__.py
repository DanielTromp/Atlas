"""API routers entry points for FastAPI integration."""

from fastapi import APIRouter

from infrastructure_atlas.infrastructure.logging import get_logger, setup_logging
from infrastructure_atlas.infrastructure.modules import get_module_registry, initialize_modules

from .routes import admin, auth, core, netbox, profile, search, tasks, tools, vcenter, zabbix

logger = get_logger(__name__)


def bootstrap_api() -> APIRouter:
    """Return a configured APIRouter instance with feature routers included.

    Routes are conditionally included based on the module registry's enabled state.
    """
    setup_logging()

    # Initialize the module system
    initialize_modules()
    registry = get_module_registry()

    router = APIRouter()

    # Core routes (always enabled)
    router.include_router(core.router)
    router.include_router(auth.router)
    router.include_router(profile.router)
    router.include_router(admin.router)
    router.include_router(tools.router)
    router.include_router(search.router)
    router.include_router(tasks.router)

    # Chat routes (imported lazily to avoid circular import)
    from .routes import chat, export
    router.include_router(chat.router)
    router.include_router(export.router)

    # Conditional module routes
    if registry.is_enabled("vcenter"):
        router.include_router(vcenter.router)
        logger.info("Enabled vCenter API routes")
    else:
        logger.info("vCenter module is disabled, skipping routes")

    if registry.is_enabled("netbox"):
        router.include_router(netbox.router)
        logger.info("Enabled NetBox API routes")
    else:
        logger.info("NetBox module is disabled, skipping routes")

    if registry.is_enabled("zabbix"):
        router.include_router(zabbix.router)
        logger.info("Enabled Zabbix API routes")
    else:
        logger.info("Zabbix module is disabled, skipping routes")

    if registry.is_enabled("commvault"):
        from .routes import commvault
        router.include_router(commvault.router)
        logger.info("Enabled Commvault API routes")
    else:
        logger.info("Commvault module is disabled, skipping routes")

    if registry.is_enabled("jira"):
        from .routes import jira
        router.include_router(jira.router)
        logger.info("Enabled Jira API routes")
    else:
        logger.info("Jira module is disabled, skipping routes")

    if registry.is_enabled("confluence"):
        from .routes import confluence
        router.include_router(confluence.router)
        logger.info("Enabled Confluence API routes")
    else:
        logger.info("Confluence module is disabled, skipping routes")

    return router


__all__ = ["bootstrap_api"]
