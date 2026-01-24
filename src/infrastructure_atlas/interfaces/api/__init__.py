"""API routers entry points for FastAPI integration."""

from fastapi import APIRouter

from infrastructure_atlas.infrastructure.logging import get_logger, setup_logging
from infrastructure_atlas.infrastructure.modules import get_module_registry, initialize_modules

from .routes import (
    admin,
    auth,
    claude_cli,
    core,
    draft_tickets,
    foreman,
    netbox,
    profile,
    puppet,
    search,
    tasks,
    tools,
    vcenter,
    zabbix,
)

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
    router.include_router(draft_tickets.router)
    router.include_router(claude_cli.router)

    # Chat routes (imported lazily to avoid circular import)
    from .routes import chat, export

    router.include_router(chat.router)
    router.include_router(export.router)

    # AI Chat routes (new multi-provider chat system)
    try:
        from .routes import ai_chat

        router.include_router(ai_chat.router)
        logger.info("Enabled AI Chat API routes")
    except ImportError as e:
        logger.warning(f"AI Chat routes not available: {e}")

    # AI Usage tracking routes
    try:
        from .routes import ai_usage

        router.include_router(ai_usage.router)
        logger.info("Enabled AI Usage API routes")
    except ImportError as e:
        logger.warning(f"AI Usage routes not available: {e}")

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

    if registry.is_enabled("foreman"):
        router.include_router(foreman.router)
        logger.info("Enabled Foreman API routes")
    else:
        logger.info("Foreman module is disabled, skipping routes")

    if registry.is_enabled("puppet"):
        router.include_router(puppet.router)
        logger.info("Enabled Puppet API routes")
    else:
        logger.info("Puppet module is disabled, skipping routes")

    # Confluence RAG routes (Qdrant-based semantic search)
    # Routes use lazy imports internally for heavy dependencies (qdrant-client, transformers)
    import os
    try:
        from infrastructure_atlas.confluence_rag.api import router as rag_router
        from infrastructure_atlas.confluence_rag.api import warmup_search_engine

        router.include_router(rag_router)
        logger.info("Enabled Confluence RAG API routes")

        # Warmup the embedding model at startup (skip if lazy imports enabled or warmup disabled)
        if (
            os.getenv("ATLAS_LAZY_AI_IMPORTS", "").lower() not in ("1", "true", "yes")
            and os.getenv("ATLAS_RAG_WARMUP", "0").lower() in ("1", "true", "yes")
        ):
            warmup_search_engine()
    except Exception as e:
        logger.warning(f"Confluence RAG routes not available: {e}")

    # Atlas Agents Platform - Workflow routes
    try:
        from .routes import executions, workflows
        from .websocket import router as ws_router

        router.include_router(workflows.router)
        router.include_router(executions.router)
        router.include_router(ws_router)
        logger.info("Enabled Atlas Agents Platform routes (workflows, executions, websocket)")
    except Exception as e:
        logger.warning(f"Atlas Agents routes not available: {e}")

    # Agent Playground routes (uses lazy imports internally for heavy AI modules)
    try:
        from .routes import playground

        router.include_router(playground.router)
        logger.info("Enabled Agent Playground API routes")
    except Exception as e:
        logger.warning(f"Agent Playground routes not available: {e}")

    # Bot platform routes (conditional on bots module)
    if registry.is_enabled("bots"):
        try:
            from .routes import bot_admin, bot_webhooks

            router.include_router(bot_webhooks.router)
            router.include_router(bot_admin.router)
            logger.info("Enabled Bot Platform API routes")
        except Exception as e:
            logger.warning(f"Bot Platform routes not available: {e}")
    else:
        logger.info("Bots module is disabled, skipping routes")

    return router


__all__ = ["bootstrap_api"]
