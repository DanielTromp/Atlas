"""Database management CLI commands."""

from __future__ import annotations

import os

import typer
from rich import print

from infrastructure_atlas.db.setup import init_database

app = typer.Typer(help="Database utilities", context_settings={"help_option_names": ["-h", "--help"]})


@app.command("init")
def db_init(echo: bool = typer.Option(False, "--echo", help="Echo SQL while running migrations")):
    """Initialise or upgrade the application database using Alembic."""
    if echo:
        os.environ["SQLALCHEMY_ECHO"] = "1"
    init_database()
    print("[green]Database initialised[/green]")
