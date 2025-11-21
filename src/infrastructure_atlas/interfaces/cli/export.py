"""NetBox export CLI commands."""

from __future__ import annotations

import asyncio
import inspect
import os
from pathlib import Path
from time import monotonic

import typer
from rich import print

from infrastructure_atlas.application.orchestration import AsyncJobRunner
from infrastructure_atlas.application.services import NetboxExportService
from infrastructure_atlas.domain.tasks import JobStatus
from infrastructure_atlas.env import project_root, require_env
from infrastructure_atlas.infrastructure.logging import get_logger, logging_context
from infrastructure_atlas.infrastructure.metrics import record_netbox_export
from infrastructure_atlas.infrastructure.modules import get_module_registry
from infrastructure_atlas.infrastructure.queues import InMemoryJobQueue
from infrastructure_atlas.infrastructure.tracing import init_tracing, span, tracing_enabled

app = typer.Typer(help="NetBox export helpers", context_settings={"help_option_names": ["-h", "--help"]})
logger = get_logger(__name__)


@app.callback(invoke_without_command=True)
def check_module_enabled(ctx: typer.Context):
    """Ensure NetBox module is enabled before running commands."""
    if ctx.invoked_subcommand:
        registry = get_module_registry()
        try:
            registry.require_enabled("netbox")
        except Exception as e:
            print(f"[red]NetBox module is disabled:[/red] {e}")
            raise typer.Exit(code=1)


def _run_script(relpath: str, *args: str) -> int:
    """Run a Python script at repo-relative path with inherited env."""
    root = project_root()
    script = root / relpath
    if not script.exists():
        print(f"[red]Script not found:[/red] {script}")
        return 1
    import subprocess

    cmd = ["python3", str(script), *args]
    try:
        result = subprocess.run(cmd, cwd=str(root), check=False)
        return result.returncode
    except Exception as e:
        print(f"[red]Script execution failed:[/red] {e}")
        return 1


def _auto_publish_after_export() -> None:
    """Publish NetBox exports to Confluence when env vars are configured."""
    logger.info("Checking Confluence auto-publish configuration")
    try:
        base = os.getenv("ATLASSIAN_BASE_URL", "").strip()
        email = os.getenv("ATLASSIAN_EMAIL", "").strip()
        token = os.getenv("ATLASSIAN_API_TOKEN", "").strip()
        page_id = os.getenv("CONFLUENCE_CMDB_PAGE_ID", "").strip() or os.getenv("CONFLUENCE_PAGE_ID", "").strip()
        devices_page_id = os.getenv("CONFLUENCE_DEVICES_PAGE_ID", "").strip() or page_id
        vms_page_id = os.getenv("CONFLUENCE_VMS_PAGE_ID", "").strip() or os.getenv("CONFLUENCE_PAGE_ID", "").strip()
        if base and email and token and page_id:
            logger.info("Publishing CMDB export to Confluence", extra={"page_id": page_id})
            _ = _run_script("netbox-export/bin/confluence_publish_cmdb.py", "--page-id", page_id)
            table_args: list[str] = []
            if devices_page_id:
                table_args += ["--page-id", devices_page_id]
            _ = _run_script("netbox-export/bin/confluence_publish_devices_table.py", *table_args)
            vms_args: list[str] = []
            if vms_page_id:
                vms_args += ["--page-id", vms_page_id]
            _ = _run_script("netbox-export/bin/confluence_publish_vms_table.py", *vms_args)
        else:
            print("[dim]Confluence not configured; skipping auto publish[/dim]")
            logger.debug("Confluence auto-publish skipped", extra={"base": base, "page_id": page_id})
    except Exception as exc:  # pragma: no cover - CLI helper
        print(f"[red]Confluence publish failed:[/red] {exc}")
        logger.exception("Confluence auto-publish failed")


@app.command("cache")
def netbox_cache(
    force: bool = typer.Option(False, "--force", help="Force refresh from NetBox and bypass in-memory cache"),
    verbose: bool = typer.Option(False, "--verbose/--no-verbose", help="Log detailed cache diff results"),
):
    """Refresh the NetBox JSON cache without rewriting CSV or Excel exports."""
    require_env(["NETBOX_URL", "NETBOX_TOKEN"])
    if tracing_enabled():
        init_tracing("infrastructure-atlas-cli")
    with logging_context(command="export.cache", force=force, verbose=verbose), span(
        "cli.export.cache", force=force, verbose=verbose
    ):
        service = NetboxExportService.from_env()
        result = service.refresh_cache(force=force, verbose=verbose)
        print(f"[green]Cache updated[/green] {result.path.as_posix()}")
        timestamp = result.generated_at.astimezone().isoformat(timespec="seconds")
        print(f"[dim]Generated at:[/dim] {timestamp}")
        summaries = result.summaries
        if not summaries:
            print("[yellow]No cacheable resources were returned[/yellow]")
            return
        for name, summary in summaries.items():
            diffs: list[str] = []
            if summary.added:
                diffs.append(f"{summary.added} new")
            if summary.updated:
                diffs.append(f"{summary.updated} updated")
            if summary.removed:
                diffs.append(f"{summary.removed} removed")
            diff_label = ", ".join(diffs) if diffs else "no changes"
            print(
                f"[cyan]{name}[/cyan]: {summary.total} total ({diff_label})",
            )


@app.command("devices")
def netbox_devices(
    force: bool = typer.Option(False, "--force", help="Re-fetch all devices and rewrite CSV"),
):
    """Export devices to CSV (incremental)."""
    require_env(["NETBOX_URL", "NETBOX_TOKEN"])
    args = ["--force"] if force else []
    raise_code = _run_script("netbox-export/bin/get_netbox_devices.py", *args)
    raise SystemExit(raise_code)


@app.command("vms")
def netbox_vms(
    force: bool = typer.Option(False, "--force", help="Re-fetch all VMs and rewrite CSV"),
):
    """Export VMs to CSV (incremental)."""
    require_env(["NETBOX_URL", "NETBOX_TOKEN"])
    args = ["--force"] if force else []
    raise_code = _run_script("netbox-export/bin/get_netbox_vms.py", *args)
    raise SystemExit(raise_code)


@app.command("merge")
def netbox_merge():
    """Merge devices+vms CSV into a single CSV and Excel."""
    raise_code = _run_script("netbox-export/bin/merge_netbox_csvs.py")
    raise SystemExit(raise_code)


@app.command("status")
def netbox_status():
    """Check NetBox API status and token access (200/403 details)."""
    code = _run_script("netbox-export/bin/netbox_status.py")
    raise SystemExit(code)


@app.command("update")
def netbox_update(
    force: bool = typer.Option(False, "--force", help="Re-fetch all devices and VMs before merge"),
    use_queue: bool = typer.Option(False, "--queue/--no-queue", help="Schedule export via the in-memory job queue"),
    legacy: bool = typer.Option(False, "--legacy/--no-legacy", help="Use legacy exporter scripts"),
    verbose: bool = typer.Option(False, "--verbose/--no-verbose", help="Log verbose exporter progress"),
    refresh_cache: bool = typer.Option(
        True,
        "--refresh-cache/--no-refresh-cache",
        help="Refresh the NetBox JSON cache before exporting (disable to reuse the existing snapshot)",
    ),
):
    """Run devices, vms, then merge exports in sequence."""
    require_env(["NETBOX_URL", "NETBOX_TOKEN"])  # token needed for export endpoints
    mode = "queue" if use_queue else "legacy"
    if tracing_enabled():
        init_tracing("infrastructure-atlas-cli")
    previous_legacy = os.environ.get("ATLAS_LEGACY_EXPORTER")
    if legacy:
        os.environ["ATLAS_LEGACY_EXPORTER"] = "1"
    with logging_context(command="export.update", mode=mode, force=force, verbose=verbose), span(
        "cli.export.update", mode=mode, force=force, verbose=verbose
    ):
        logger.info("NetBox export command invoked")
        if verbose:
            logger.info("Verbose exporter output enabled")
        if use_queue:
            service = NetboxExportService.from_env()
            queue = InMemoryJobQueue()
            runner = AsyncJobRunner(queue)
            runner.register_handler(service.JOB_NAME, service.job_handler())

            async def _run_job() -> JobStatus:
                await runner.start()
                try:
                    build_kwargs = {"force": force, "verbose": verbose}
                    try:
                        spec_signature = inspect.signature(service.build_job_spec)
                    except (TypeError, ValueError):
                        spec_signature = None
                    if spec_signature and "refresh_cache" in spec_signature.parameters:
                        build_kwargs["refresh_cache"] = refresh_cache
                    record = await queue.enqueue(service.build_job_spec(**build_kwargs))
                    while True:
                        job = await queue.get_job(record.job_id)
                        if job and job.status in {JobStatus.COMPLETED, JobStatus.FAILED}:
                            return job.status
                        await asyncio.sleep(0.2)
                finally:
                    await runner.stop()

            status = asyncio.run(_run_job())
            logger.info("Queued NetBox export finished", extra={"status": status})
            if status != JobStatus.COMPLETED:
                print("[red]Queued NetBox export failed[/red]")
                raise typer.Exit(code=1)
        else:
            start = monotonic()
            status = "success"
            args = ["--force"] if force else []
            if verbose:
                args.append("--verbose")
            if not refresh_cache:
                args.append("--no-refresh-cache")
            try:
                code = _run_script("netbox-export/bin/netbox_update.py", *args)
                if code != 0:
                    status = "failure"
                    raise SystemExit(code)
            except Exception:
                status = "failure"
                duration = monotonic() - start
                record_netbox_export(duration_seconds=duration, mode="legacy", force=force, status=status)
                logger.exception("Legacy NetBox export failed", extra={"duration_ms": int(duration * 1000)})
                raise
            else:
                duration = monotonic() - start
                record_netbox_export(duration_seconds=duration, mode="legacy", force=force, status=status)
                logger.info("Legacy NetBox export completed", extra={"duration_ms": int(duration * 1000)})

        _auto_publish_after_export()
    if legacy:
        if previous_legacy is None:
            os.environ.pop("ATLAS_LEGACY_EXPORTER", None)
        else:
            os.environ["ATLAS_LEGACY_EXPORTER"] = previous_legacy
