"""API package for infrastructure_atlas."""

from .app import app  # re-export for uvicorn path

__all__ = ["app"]

