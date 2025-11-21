"""API server CLI commands."""

from __future__ import annotations

import os

import typer

app = typer.Typer(help="API server", context_settings={"help_option_names": ["-h", "--help"]})


@app.command("serve")
def api_serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host"),
    port: int = typer.Option(8000, "--port", help="Bind port"),
    reload: bool = typer.Option(True, "--reload/--no-reload", help="Auto-reload on changes"),
    log_level: str = typer.Option("", "--log-level", help="Uvicorn log level (overrides LOG_LEVEL env)"),
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
):
    """Run the FastAPI server (HTTP or HTTPS).

    Provide --ssl-certfile/--ssl-keyfile (or ATLAS_SSL_CERTFILE/ATLAS_SSL_KEYFILE)
    to enable HTTPS. When not provided, server runs over HTTP.
    """
    import uvicorn

    # Resolve SSL params from env when not explicitly provided
    ssl_certfile = ssl_certfile or os.getenv("ATLAS_SSL_CERTFILE") or None
    ssl_keyfile = ssl_keyfile or os.getenv("ATLAS_SSL_KEYFILE") or None
    ssl_keyfile_password = ssl_keyfile_password or os.getenv("ATLAS_SSL_KEY_PASSWORD") or None

    resolved_log_level = (log_level or os.getenv("LOG_LEVEL") or "warning").lower()

    kwargs: dict = {"host": host, "port": port, "reload": reload, "log_level": resolved_log_level}
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
