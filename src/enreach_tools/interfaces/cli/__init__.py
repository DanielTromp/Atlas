from __future__ import annotations

from typer import Typer

from enreach_tools.infrastructure.logging import setup_logging
from enreach_tools.infrastructure.tracing import init_tracing, tracing_enabled

setup_logging()
if tracing_enabled():
    init_tracing("enreach-cli")

app = Typer()
__all__ = ["app"]
