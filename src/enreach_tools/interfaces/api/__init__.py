"""API routers entry points for FastAPI integration."""

from fastapi import APIRouter

from enreach_tools.infrastructure.logging import setup_logging

from .routes import admin, auth, profile

router = APIRouter()
router.include_router(auth.router)
router.include_router(profile.router)
router.include_router(admin.router)


def bootstrap_api() -> APIRouter:
    """Return a configured APIRouter instance with feature routers included."""

    setup_logging()
    return router


__all__ = ["bootstrap_api", "router"]
