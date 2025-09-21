"""CLI entry points bridging Typer commands and application services."""

import typer

from enreach_tools.infrastructure.logging import setup_logging

app = typer.Typer()


def bootstrap_cli() -> typer.Typer:
    """Return the shared Typer application instance.

    Existing CLI modules can incrementally migrate their command registration to
    this entry point without changing current behaviour. Logging is initialised
    lazily to keep side effects predictable.
    """

    setup_logging()
    return app


__all__ = ["app", "bootstrap_cli"]
