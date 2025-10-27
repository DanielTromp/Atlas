from __future__ import annotations

from typer import Typer

from infrastructure_atlas.infrastructure.logging import setup_logging
from infrastructure_atlas.infrastructure.tracing import init_tracing, tracing_enabled

setup_logging()
if tracing_enabled():
    init_tracing("infrastructure-atlas-cli")

app = Typer()
__all__ = ["app"]
