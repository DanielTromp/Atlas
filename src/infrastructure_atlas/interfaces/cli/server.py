"""API server CLI commands."""

from __future__ import annotations

import os

import typer
from rich import print

app = typer.Typer(help="API server", context_settings={"help_option_names": ["-h", "--help"]})


@app.command("serve")
def api_serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host"),
    port: int = typer.Option(8000, "--port", help="Bind port"),
    reload: bool = typer.Option(True, "--reload/--no-reload", help="Auto-reload on changes"),
    log_level: str = typer.Option("", "--log-level", help="Uvicorn log level (overrides LOG_LEVEL env)"),
    workers: int = typer.Option(1, "--workers", "-w", help="Number of worker processes (production)"),
    ssl_certfile: str | None = typer.Option(
        None,
        "--ssl-certfile",
        help="Path to SSL certificate (PEM). If omitted, uses ATLAS_SSL_CERTFILE when set.",
    ),
    ssl_keyfile: str | None = typer.Option(
        None,
        "--ssl-keyfile",
        help="Path to SSL private key (PEM). If omitted, uses ATLAS_SSL_KEYFILE when set.",
    ),
    ssl_keyfile_password: str | None = typer.Option(
        None,
        "--ssl-keyfile-password",
        help="Password for encrypted SSL keyfile (optional). If omitted, uses ATLAS_SSL_KEY_PASSWORD when set.",
        show_default=False,
    ),
    skip_health_check: bool = typer.Option(
        False,
        "--skip-health-check",
        help="Skip MongoDB health check at startup for faster boot (set ATLAS_SKIP_DB_HEALTH_CHECK=1)",
    ),
):
    """Run the FastAPI server (HTTP or HTTPS).

    Provide --ssl-certfile/--ssl-keyfile (or ATLAS_SSL_CERTFILE/ATLAS_SSL_KEYFILE)
    to enable HTTPS. When not provided, server runs over HTTP.

    For production, use: --no-reload --workers 4 --skip-health-check
    """
    import uvicorn

    # Set skip health check env var if requested
    if skip_health_check:
        os.environ["ATLAS_SKIP_DB_HEALTH_CHECK"] = "1"

    # Resolve SSL params from env when not explicitly provided
    ssl_certfile = ssl_certfile or os.getenv("ATLAS_SSL_CERTFILE") or None
    ssl_keyfile = ssl_keyfile or os.getenv("ATLAS_SSL_KEYFILE") or None
    ssl_keyfile_password = ssl_keyfile_password or os.getenv("ATLAS_SSL_KEY_PASSWORD") or None

    resolved_log_level = (log_level or os.getenv("LOG_LEVEL") or "warning").lower()

    # Can't use workers with reload
    if workers > 1 and reload:
        print("[yellow]Warning: --workers > 1 requires --no-reload, disabling reload[/yellow]")
        reload = False

    kwargs: dict = {"host": host, "port": port, "reload": reload, "log_level": resolved_log_level}

    if workers > 1:
        kwargs["workers"] = workers

    if ssl_certfile and ssl_keyfile:
        kwargs.update(
            {
                "ssl_certfile": ssl_certfile,
                "ssl_keyfile": ssl_keyfile,
            }
        )
        if ssl_keyfile_password:
            kwargs["ssl_keyfile_password"] = ssl_keyfile_password

    # ASGI app path: src/infrastructure_atlas/api/app.py -> app
    uvicorn.run("infrastructure_atlas.api.app:app", **kwargs)


@app.command("prod")
def api_prod(
    host: str = typer.Option("0.0.0.0", "--host", help="Bind host"),
    port: int = typer.Option(8000, "--port", help="Bind port"),
    workers: int = typer.Option(4, "--workers", "-w", help="Number of worker processes"),
    log_level: str = typer.Option("info", "--log-level", help="Log level"),
    ssl_certfile: str | None = typer.Option(None, "--ssl-certfile", help="Path to SSL certificate"),
    ssl_keyfile: str | None = typer.Option(None, "--ssl-keyfile", help="Path to SSL private key"),
):
    """Run the FastAPI server in production mode (optimized).

    This is a shortcut for:
        atlas api serve --no-reload --workers 4 --skip-health-check --host 0.0.0.0

    For Docker, use:
        uvicorn infrastructure_atlas.api.app:app --host 0.0.0.0 --port 8000 --workers 4
    """
    import uvicorn

    # Production optimizations
    os.environ["ATLAS_SKIP_DB_HEALTH_CHECK"] = "1"

    ssl_certfile = ssl_certfile or os.getenv("ATLAS_SSL_CERTFILE") or None
    ssl_keyfile = ssl_keyfile or os.getenv("ATLAS_SSL_KEYFILE") or None

    kwargs: dict = {
        "host": host,
        "port": port,
        "workers": workers,
        "log_level": log_level,
        "reload": False,
        "access_log": True,
    }

    if ssl_certfile and ssl_keyfile:
        kwargs["ssl_certfile"] = ssl_certfile
        kwargs["ssl_keyfile"] = ssl_keyfile

    print(f"[green]Starting production server on {host}:{port} with {workers} workers[/green]")
    uvicorn.run("infrastructure_atlas.api.app:app", **kwargs)
