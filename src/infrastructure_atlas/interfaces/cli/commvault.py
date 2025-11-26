"""Commvault-related CLI commands for the Infrastructure Atlas toolbox."""
from __future__ import annotations

import json
import os
import warnings
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import typer
from rich import print
from rich.console import Console
from rich.table import Table

from infrastructure_atlas.api.app import (
    _collect_commvault_jobs_for_ui,
    _commvault_client_from_env,
    _load_commvault_backups,
    _parse_job_datetime,
    _serialise_commvault_job,
)
from infrastructure_atlas.domain.integrations.commvault import (
    CommvaultClientJobMetrics,
    CommvaultClientReference,
    CommvaultClientSummary,
    CommvaultJob,
    CommvaultStoragePool,
)
from infrastructure_atlas.infrastructure.external.commvault_client import (
    CommvaultClient,
    CommvaultError,
    CommvaultJobQuery,
)

try:  # optional dependency; only present when urllib3 installed
    from urllib3 import disable_warnings
    from urllib3.exceptions import InsecureRequestWarning
except Exception:  # pragma: no cover - urllib3 may not be present
    disable_warnings = None  # type: ignore[assignment]
    InsecureRequestWarning = None  # type: ignore[assignment]

HELP_CTX = {"help_option_names": ["-h", "--help"]}

console = Console()
app = typer.Typer(help="Commvault backup helpers", context_settings=HELP_CTX)
servers_app = typer.Typer(help="Commvault server/client helpers", context_settings=HELP_CTX)
storage_app = typer.Typer(help="Commvault storage helpers", context_settings=HELP_CTX)
app.add_typer(storage_app, name="storage")


def _maybe_disable_tls_warnings() -> None:
    """Mute urllib3 TLS warnings when TLS verification is intentionally disabled."""

    verify = os.getenv("COMMVAULT_VERIFY_TLS")
    if verify is None:
        return
    if verify.strip().lower() in {"0", "false", "no", "off"}:
        if disable_warnings and InsecureRequestWarning:
            disable_warnings(InsecureRequestWarning)
        else:
            warnings.filterwarnings("ignore", category=Warning, module="urllib3")


def _commvault_client_or_exit() -> CommvaultClient:
    _maybe_disable_tls_warnings()
    try:
        return _commvault_client_from_env()
    except RuntimeError as exc:
        print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc


def _now_utc() -> datetime:
    return datetime.now(tz=UTC)


def _parse_since(hours: int) -> datetime | None:
    if hours <= 0:
        return None
    return _now_utc() - timedelta(hours=hours)


def _parse_retain_after(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter("Expected ISO8601 timestamp, e.g. 2024-01-01T00:00:00") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _format_bytes(value: int | None) -> str:
    if not value:
        return "0 B"
    size = float(value)
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024
        idx += 1
    precision = 0 if size >= 100 else 1 if size >= 10 else 2
    return f"{size:.{precision}f} {units[idx]}"


def _format_when(value: datetime | None) -> str:
    if value is None:
        return "-"
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%SZ")


def _metrics_summary(metrics: CommvaultClientJobMetrics | None) -> str:
    if metrics is None:
        return "no job metrics"
    last = _format_when(metrics.last_job_start)
    return (
        f"{metrics.job_count} job(s) in {metrics.window_hours}h window;"
        f" last job {last}; app { _format_bytes(metrics.total_application_bytes)}"
    )


def _summary_to_dict(summary: CommvaultClientSummary, include_jobs: bool) -> dict[str, Any]:
    out: dict[str, Any] = {
        "client_id": summary.reference.client_id,
        "name": summary.reference.name,
        "display_name": summary.reference.display_name,
        "host_name": summary.host_name,
        "os_name": summary.os_name,
        "os_type": summary.os_type,
        "os_subtype": summary.os_subtype,
        "processor_type": summary.processor_type,
        "cpu_count": summary.cpu_count,
        "is_media_agent": summary.is_media_agent,
        "is_virtual": summary.is_virtual,
        "is_infrastructure": summary.is_infrastructure,
        "is_commserve": summary.is_commserve,
        "readiness_status": summary.readiness_status,
        "last_ready_time": summary.last_ready_time.isoformat() if summary.last_ready_time else None,
        "sla_status_code": summary.sla_status_code,
        "sla_description": summary.sla_description,
        "agent_applications": list(summary.agent_applications),
        "client_groups": list(summary.client_groups),
    }
    metrics = summary.job_metrics
    if metrics:
        out["job_metrics"] = {
            "window_hours": metrics.window_hours,
            "job_count": metrics.job_count,
            "total_application_bytes": metrics.total_application_bytes,
            "total_media_bytes": metrics.total_media_bytes,
            "last_job_start": metrics.last_job_start.isoformat() if metrics.last_job_start else None,
            "within_window": metrics.within_window,
            "descending": metrics.descending,
            "retain_cutoff": metrics.retain_cutoff.isoformat() if metrics.retain_cutoff else None,
            "retain_required": metrics.retain_required,
            "fetched_at": metrics.fetched_at.isoformat(),
        }
        if include_jobs:
            out["jobs"] = [_serialise_commvault_job(job) for job in metrics.jobs]
    elif include_jobs:
        out["jobs"] = []
    return out


def _serialise_jobs(metrics: CommvaultClientJobMetrics | None) -> list[dict[str, Any]]:
    if not metrics:
        return []
    return [_serialise_commvault_job(job) for job in metrics.jobs]


def _load_cached_jobs_for_export(
    reference: CommvaultClientReference,
    *,
    hours: int,
    job_limit: int,
    retained_only: bool,
    retain_after: datetime | None,
) -> tuple[list[dict[str, Any]], str | None] | None:
    cache = _load_commvault_backups()
    jobs_payload = cache.get("jobs") if isinstance(cache, Mapping) else None
    if not jobs_payload:
        return None

    cutoff = _parse_since(hours)
    retain_cutoff = retain_after
    if retained_only and retain_cutoff is None:
        retain_cutoff = _now_utc()

    target_id = reference.client_id
    candidate_names = {
        value.casefold()
        for value in (reference.name, reference.display_name)
        if value
    }

    selected: list[dict[str, Any]] = []
    for raw in jobs_payload:
        if not isinstance(raw, Mapping):
            continue

        job_client_id = raw.get("client_id")
        try:
            job_client_id = int(job_client_id) if job_client_id is not None else None
        except (TypeError, ValueError):
            job_client_id = None

        if job_client_id is not None:
            if job_client_id != target_id:
                continue
        elif candidate_names:
            job_name = str(
                raw.get("client_name")
                or raw.get("destination_client_name")
                or ""
            ).casefold()
            if job_name not in candidate_names:
                continue

        start = _parse_job_datetime(raw.get("start_time"))
        if cutoff and (start is None or start < cutoff):
            continue

        retain_until = _parse_job_datetime(raw.get("retain_until"))
        if retain_cutoff and (retain_until is None or retain_until < retain_cutoff):
            continue
        if retained_only and retain_until is None:
            continue

        selected.append(dict(raw))
        if job_limit > 0 and len(selected) >= job_limit:
            break

    if not selected and job_limit > 0:
        # If the cache has data but nothing matched, allow callers to fall back to the API.
        total_cached = cache.get("total_cached") if isinstance(cache, Mapping) else None
        try:
            total_cached = int(total_cached) if total_cached is not None else None
        except (TypeError, ValueError):
            total_cached = None
        if not total_cached:
            return None

    return selected, cache.get("generated_at")


def _job_dict_to_model(payload: Mapping[str, Any]) -> CommvaultJob:
    """Convert a cached job payload back into a ``CommvaultJob`` model."""

    def _optional_str(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _optional_int(value: Any) -> int | None:
        if value in {None, ""}:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _optional_float(value: Any) -> float | None:
        if value in {None, ""}:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _group_values(groups: Any) -> tuple[str, ...]:
        if isinstance(groups, Sequence) and not isinstance(groups, str | bytes):
            return tuple(str(item) for item in groups)
        return ()

    return CommvaultJob(
        job_id=_optional_int(payload.get("job_id")) or 0,
        job_type=_optional_str(payload.get("job_type")) or "",
        status=_optional_str(payload.get("status")) or "",
        localized_status=_optional_str(payload.get("localized_status")),
        localized_operation=_optional_str(payload.get("localized_operation")),
        client_name=_optional_str(payload.get("client_name")),
        client_id=_optional_int(payload.get("client_id")),
        destination_client_name=_optional_str(payload.get("destination_client_name")),
        subclient_name=_optional_str(payload.get("subclient_name")),
        backup_set_name=_optional_str(payload.get("backup_set_name")),
        application_name=_optional_str(payload.get("application_name")),
        backup_level_name=_optional_str(payload.get("backup_level_name")),
        plan_name=_optional_str(payload.get("plan_name")),
        client_groups=_group_values(payload.get("client_groups")),
        storage_policy_name=_optional_str(payload.get("storage_policy_name")),
        start_time=_parse_job_datetime(payload.get("start_time")),
        end_time=_parse_job_datetime(payload.get("end_time")),
        elapsed_seconds=_optional_int(payload.get("elapsed_seconds")),
        size_of_application_bytes=_optional_int(payload.get("size_of_application_bytes")),
        size_on_media_bytes=_optional_int(payload.get("size_on_media_bytes")),
        total_num_files=_optional_int(payload.get("total_num_files")),
        percent_complete=_optional_float(payload.get("percent_complete")),
        percent_savings=_optional_float(payload.get("percent_savings")),
        average_throughput=_optional_float(payload.get("average_throughput_gb_per_hr")),
        retain_until=_parse_job_datetime(payload.get("retain_until")),
    )


def _build_cached_metrics(  # noqa: PLR0913
    jobs: Sequence[CommvaultJob],
    *,
    hours: int,
    oldest_first: bool,
    retain_after: datetime | None,
    retained_only: bool,
    cache_generated_at: str | None,
) -> CommvaultClientJobMetrics:
    window_hours = max(0, hours)
    def _start_key(job: CommvaultJob) -> datetime:
        return job.start_time or datetime.min.replace(tzinfo=UTC)

    sorted_jobs = sorted(jobs, key=_start_key, reverse=not oldest_first)

    total_app = sum(job.size_of_application_bytes or 0 for job in sorted_jobs)
    total_media = sum(job.size_on_media_bytes or 0 for job in sorted_jobs)
    last_job_start = None
    for job in sorted_jobs:
        if job.start_time and (last_job_start is None or job.start_time > last_job_start):
            last_job_start = job.start_time

    cutoff = None
    if window_hours > 0:
        cutoff = _now_utc() - timedelta(hours=window_hours)
    within_window = False
    if cutoff is None:
        within_window = bool(sorted_jobs)
    else:
        within_window = any(job.start_time and job.start_time >= cutoff for job in sorted_jobs)

    fetched_at = _parse_job_datetime(cache_generated_at) if cache_generated_at else None
    if fetched_at is None:
        fetched_at = _now_utc()

    jobs_payload = tuple(sorted_jobs)
    return CommvaultClientJobMetrics(
        window_hours=window_hours,
        job_count=len(sorted_jobs),
        total_application_bytes=total_app,
        total_media_bytes=total_media,
        last_job_start=last_job_start,
        within_window=within_window,
        descending=not oldest_first,
        retain_cutoff=retain_after,
        retain_required=retained_only,
        fetched_at=fetched_at,
        jobs=jobs_payload,
    )


def _load_cached_jobs_for_backups(
    *,
    limit: int,
    since: datetime | None,
    client_filter: str,
) -> tuple[list[CommvaultJob], int, str | None] | None:
    cache = _load_commvault_backups()
    jobs_payload = cache.get("jobs") if isinstance(cache, Mapping) else None
    if not isinstance(jobs_payload, Sequence) or not jobs_payload:
        return None

    total_cached = len(jobs_payload)
    filter_text = client_filter.strip()
    target_id: int | None = None
    needle: str | None = None
    if filter_text:
        if filter_text.isdigit():
            target_id = int(filter_text)
        else:
            needle = filter_text.casefold()

    selected: list[CommvaultJob] = []
    for raw in jobs_payload:
        if not isinstance(raw, Mapping):
            continue

        start_dt = _parse_job_datetime(raw.get("start_time"))
        if since and (start_dt is None or start_dt < since):
            continue

        if target_id is not None:
            job_client_id = raw.get("client_id")
            try:
                job_client_id = int(job_client_id) if job_client_id not in {None, ""} else None
            except (TypeError, ValueError):
                job_client_id = None
            if job_client_id != target_id:
                continue
        elif needle:
            names = [
                str(raw.get("client_name") or ""),
                str(raw.get("destination_client_name") or ""),
            ]
            if not any(needle in name.casefold() for name in names if name):
                continue

        selected.append(_job_dict_to_model(raw))
        if limit > 0 and len(selected) >= limit:
            break

    return selected, total_cached, cache.get("generated_at")


def _default_backups_outfile(client_filter: str) -> Path:
    slug_source = client_filter.strip() or "commvault_backups"
    slug = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in slug_source)
    if not slug.strip("_"):
        slug = "commvault_backups"
    reports_dir = Path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    return reports_dir / f"{slug}.csv"


def _iter_clients(client: CommvaultClient, *, limit: int | None = None) -> list[CommvaultClientReference]:
    page_size = 200
    collected: list[CommvaultClientReference] = []
    offset = 0
    while True:
        page = client.list_clients(limit=page_size, offset=offset)
        if not page:
            break
        collected.extend(page)
        offset += len(page)
        if limit and limit > 0 and len(collected) >= limit:
            break
        if len(page) < page_size:
            break
    if limit and limit > 0:
        return collected[:limit]
    return collected


def _resolve_client(client: CommvaultClient, identifier: str) -> CommvaultClientReference:
    identifier = identifier.strip()
    if not identifier:
        raise typer.BadParameter("Client identifier required")
    if identifier.isdigit():
        client_id = int(identifier)
        try:
            summary = client.get_client_summary(client_id, job_query=CommvaultJobQuery(limit=0))
            return summary.reference
        except CommvaultError as exc:  # pragma: no cover - network dependent
            raise typer.BadParameter(f"Commvault lookup failed: {exc}") from exc
    matches: list[CommvaultClientReference] = []
    needle = identifier.casefold()
    for ref in _iter_clients(client, limit=None):
        candidates = [ref.name or ""]
        if ref.display_name:
            candidates.append(ref.display_name)
        if any(needle in cand.casefold() for cand in candidates):
            matches.append(ref)
    if not matches:
        raise typer.BadParameter(f"No client matching '{identifier}' found")
    if len(matches) > 1:
        names = ", ".join(sorted({ref.display_name or ref.name for ref in matches}))
        raise typer.BadParameter(f"Ambiguous client '{identifier}'. Matches: {names}")
    return matches[0]


def _job_query(  # noqa: PLR0913
    *,
    hours: int,
    job_limit: int,
    oldest_first: bool,
    retained_only: bool,
    retain_after: datetime | None,
    refresh_cache: bool,
) -> CommvaultJobQuery:
    return CommvaultJobQuery(
        limit=max(0, job_limit),
        since=_parse_since(hours),
        window_hours=max(0, hours),
        descending=not oldest_first,
        retain_cutoff=retain_after,
        require_retain=retained_only,
        refresh_cache=refresh_cache,
    )


@servers_app.command("list")
def servers_list(  # noqa: PLR0913
    limit: int = typer.Option(20, "--limit", min=0, help="Maximum number of clients to list (0 = all)."),
    hours: int = typer.Option(168, "--hours", min=0, help="Job metrics lookback window in hours."),
    job_limit: int = typer.Option(20, "--job-limit", min=0, help="Maximum number of jobs to retain per client (0 = skip metrics)."),
    no_jobs: bool = typer.Option(False, "--no-jobs", help="Skip fetching job metrics for faster listings."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    refresh_cache: bool = typer.Option(False, "--refresh-cache", help="Force cache refresh for retrieved metrics."),
) -> None:
    client = _commvault_client_or_exit()
    references = _iter_clients(client, limit=None if limit == 0 else limit)
    if not references:
        print("[yellow]No Commvault clients found.[/yellow]")
        return

    metrics_query = None if no_jobs or job_limit <= 0 else _job_query(
        hours=hours,
        job_limit=job_limit,
        oldest_first=False,
        retained_only=False,
        retain_after=None,
        refresh_cache=refresh_cache,
    )

    summaries: list[CommvaultClientSummary] = []
    for ref in references:
        try:
            summary = client.get_client_summary(ref.client_id, job_query=metrics_query)
        except CommvaultError as exc:  # pragma: no cover - network dependent
            print(f"[red]Failed to fetch summary for {ref.display_name or ref.name}:[/red] {exc}")
            continue
        summaries.append(summary)
        if limit and limit > 0 and len(summaries) >= limit:
            break

    if json_output:
        payload = [_summary_to_dict(summary, include_jobs=not no_jobs and job_limit > 0) for summary in summaries]
        typer.echo(json.dumps(payload, indent=2))
        return

    table = Table(show_header=True, header_style="bold", title="Commvault Clients")
    table.add_column("Client")
    table.add_column("ID", justify="right")
    table.add_column("Groups")
    table.add_column("Last Job")
    table.add_column("Jobs")
    table.add_column("App Size")
    for summary in summaries:
        name = summary.reference.display_name or summary.reference.name or f"#{summary.reference.client_id}"
        groups = ", ".join(summary.client_groups[:3]) if summary.client_groups else "-"
        if len(summary.client_groups) > 3:
            groups += ", …"
        metrics = summary.job_metrics
        last_job = _format_when(metrics.last_job_start) if metrics else "-"
        jobs_text = f"{metrics.job_count} / {metrics.window_hours}h" if metrics else "-"
        app_bytes = _format_bytes(metrics.total_application_bytes if metrics else None)
        table.add_row(name, str(summary.reference.client_id), groups, last_job, jobs_text, app_bytes)

    console.print(table)
    if metrics_query and summaries:
        timestamps = [
            _format_when(summary.job_metrics.fetched_at)
            for summary in summaries
            if summary.job_metrics
        ]
        if timestamps:
            print(f"[dim]Job cache fetched at {', '.join(sorted(set(timestamps)))}[/dim]")


@servers_app.command("search")
def servers_search(
    needle: str = typer.Argument(..., help="Name fragment or client ID to search for."),
    limit: int = typer.Option(20, "--limit", min=1, help="Maximum number of matches to display."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of a table."),
) -> None:
    client = _commvault_client_or_exit()
    matches: list[CommvaultClientReference] = []
    lower = needle.casefold()
    for ref in _iter_clients(client, limit=None):
        values = [ref.name or ""]
        if ref.display_name:
            values.append(ref.display_name)
        if any(lower in value.casefold() for value in values):
            matches.append(ref)
        if limit and len(matches) >= limit:
            break

    if json_output:
        payload = [
            {
                "client_id": ref.client_id,
                "name": ref.name,
                "display_name": ref.display_name,
            }
            for ref in matches
        ]
        typer.echo(json.dumps(payload, indent=2))
        return

    table = Table(show_header=True, header_style="bold", title=f"Matches for '{needle}'")
    table.add_column("Client ID", justify="right")
    table.add_column("Name")
    table.add_column("Display Name")
    for ref in matches:
        table.add_row(str(ref.client_id), ref.name or "-", ref.display_name or "-")
    console.print(table)
    if not matches:
        print("[yellow]No matches found.[/yellow]")


@servers_app.command("show")
def servers_show(  # noqa: PLR0913
    client_identifier: str = typer.Argument(..., help="Client name or numeric ID."),
    hours: int = typer.Option(168, "--hours", min=0, help="Job metrics lookback window in hours."),
    job_limit: int = typer.Option(50, "--job-limit", min=0, help="Maximum number of jobs to include."),
    oldest_first: bool = typer.Option(False, "--oldest-first", help="Sort jobs from oldest to newest."),
    retained_only: bool = typer.Option(False, "--retained-only", help="Only include jobs with retention metadata."),
    retain_after: str = typer.Option("", "--retain-after", help="Only include jobs retained after this ISO8601 timestamp."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of formatted table."),
    refresh_cache: bool = typer.Option(False, "--refresh-cache", help="Force cache refresh for this client."),
) -> None:
    client = _commvault_client_or_exit()
    reference = _resolve_client(client, client_identifier)
    retain_dt = _parse_retain_after(retain_after)
    cache_generated_at: str | None = None
    summary: CommvaultClientSummary | None = None

    if not refresh_cache:
        cached = _load_cached_jobs_for_export(
            reference,
            hours=hours,
            job_limit=job_limit,
            retained_only=retained_only,
            retain_after=retain_dt,
        )
        if cached is not None:
            job_dicts, cache_generated_at = cached
            cached_jobs = [_job_dict_to_model(row) for row in job_dicts]
            if cached_jobs:
                try:
                    base_summary = client.get_client_summary(
                        reference.client_id,
                        job_query=CommvaultJobQuery(limit=0),
                    )
                except CommvaultError as exc:  # pragma: no cover - network dependent
                    print(f"[red]Failed to load client summary:[/red] {exc}")
                    raise typer.Exit(code=1) from exc
                metrics = _build_cached_metrics(
                    cached_jobs,
                    hours=hours,
                    oldest_first=oldest_first,
                    retain_after=retain_dt,
                    retained_only=retained_only,
                    cache_generated_at=cache_generated_at,
                )
                summary = replace(base_summary, job_metrics=metrics)

    if summary is None:
        query = _job_query(
            hours=hours,
            job_limit=job_limit,
            oldest_first=oldest_first,
            retained_only=retained_only,
            retain_after=retain_dt,
            refresh_cache=refresh_cache,
        )
        try:
            summary = client.get_client_summary(reference.client_id, job_query=query)
        except CommvaultError as exc:  # pragma: no cover - network dependent
            print(f"[red]Failed to load client summary:[/red] {exc}")
            raise typer.Exit(code=1) from exc

    if json_output:
        payload = _summary_to_dict(summary, include_jobs=True)
        if cache_generated_at:
            payload["cache_generated_at"] = cache_generated_at
        payload["source"] = "cache" if cache_generated_at else "api"
        typer.echo(json.dumps(payload, indent=2))
        return

    display_name = summary.reference.display_name or summary.reference.name
    print(f"[bold]Commvault client:[/bold] {display_name} (ID {summary.reference.client_id})")
    print(
        f"[dim]Host:[/dim] {summary.host_name or '-'} | [dim]OS:[/dim] {summary.os_name or '-'}"
        f" | [dim]Groups:[/dim] {', '.join(summary.client_groups) or '-'}"
    )
    if summary.sla_description:
        print(f"[dim]SLA:[/dim] {summary.sla_description}")
    metrics = summary.job_metrics
    print(f"[green]{_metrics_summary(metrics)}[/green]")

    jobs = list(metrics.jobs) if metrics else []
    if not jobs:
        print("[yellow]No jobs within the selected window.[/yellow]")
        return

    table = Table(show_header=True, header_style="bold", title="Jobs")
    table.add_column("Job ID", justify="right")
    table.add_column("Status")
    table.add_column("Operation")
    table.add_column("Start")
    table.add_column("Duration")
    table.add_column("Retained Until")
    table.add_column("App Size")

    for job in jobs[: job_limit or len(jobs)]:
        elapsed = f"{job.elapsed_seconds // 60}m" if job.elapsed_seconds else "-"
        table.add_row(
            str(job.job_id),
            job.localized_status or job.status,
            job.localized_operation or job.job_type,
            _format_when(job.start_time),
            elapsed,
            _format_when(job.retain_until),
            _format_bytes(job.size_of_application_bytes),
        )

    console.print(table)
    if metrics:
        print(f"[dim]Cache fetched at {metrics.fetched_at.astimezone(UTC).isoformat()}[/dim]")
        if cache_generated_at:
            print(f"[dim]Data sourced from cache generated at {cache_generated_at}[/dim]")


@servers_app.command("export")
def servers_export(  # noqa: PLR0913
    client_identifier: str = typer.Argument(..., help="Client name or numeric ID."),
    hours: int = typer.Option(8760, "--hours", min=0, help="Job metrics lookback window in hours."),
    job_limit: int = typer.Option(500, "--job-limit", min=0, help="Maximum number of jobs to include."),
    retained_only: bool = typer.Option(False, "--retained-only", help="Only include jobs with retention metadata."),
    retain_after: str = typer.Option("", "--retain-after", help="Only include jobs retained after this ISO8601 timestamp."),
    outfile: str = typer.Option("", "--out", help="Output file path (defaults to reports/<client>.<format>)."),
    file_format: str = typer.Option("json", "--format", help="Export format: json or csv."),
    overwrite: bool = typer.Option(False, "--overwrite", help="Allow overwriting existing files."),
    refresh_cache: bool = typer.Option(False, "--refresh-cache", help="Force cache refresh for this client."),
) -> None:
    fmt = file_format.strip().lower()
    if fmt not in {"json", "csv"}:
        raise typer.BadParameter("--format must be 'json' or 'csv'")

    client = _commvault_client_or_exit()
    reference = _resolve_client(client, client_identifier)
    retain_dt = _parse_retain_after(retain_after)
    cache_generated_at: str | None = None
    jobs: list[dict[str, Any]] | None = None
    summary: CommvaultClientSummary | None = None

    if not refresh_cache:
        cached = _load_cached_jobs_for_export(
            reference,
            hours=hours,
            job_limit=job_limit,
            retained_only=retained_only,
            retain_after=retain_dt,
        )
        if cached is not None:
            jobs, cache_generated_at = cached
            try:
                summary = client.get_client_summary(
                    reference.client_id,
                    job_query=CommvaultJobQuery(limit=0),
                )
            except CommvaultError as exc:  # pragma: no cover - network dependent
                print(f"[red]Failed to load client summary:[/red] {exc}")
                raise typer.Exit(code=1) from exc

    if jobs is None or summary is None:
        query = _job_query(
            hours=hours,
            job_limit=job_limit,
            oldest_first=False,
            retained_only=retained_only,
            retain_after=retain_dt,
            refresh_cache=refresh_cache,
        )
        try:
            summary = client.get_client_summary(reference.client_id, job_query=query)
        except CommvaultError as exc:  # pragma: no cover - network dependent
            print(f"[red]Failed to load client summary:[/red] {exc}")
            raise typer.Exit(code=1) from exc
        jobs = _serialise_jobs(summary.job_metrics)

    if jobs is None:
        jobs = []

    if not outfile:
        slug = (reference.display_name or reference.name or f"client-{reference.client_id}").replace(" ", "_")
        default_dir = Path("reports")
        default_dir.mkdir(parents=True, exist_ok=True)
        outfile = str(default_dir / f"{slug}.{fmt}")
    out_path = Path(outfile)
    if out_path.exists() and not overwrite:
        raise typer.BadParameter(f"File {out_path} already exists. Use --overwrite to replace it.")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "json":
        payload = {
            "client": _summary_to_dict(summary, include_jobs=False),
            "jobs": jobs,
        }
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    else:
        import csv

        fieldnames = [
            "job_id",
            "job_type",
            "status",
            "localized_status",
            "localized_operation",
            "client_name",
            "client_id",
            "destination_client_name",
            "subclient_name",
            "backup_set_name",
            "application_name",
            "backup_level_name",
            "plan_name",
            "client_groups",
            "storage_policy_name",
            "start_time",
            "end_time",
            "elapsed_seconds",
            "size_of_application_bytes",
            "size_on_media_bytes",
            "total_num_files",
            "percent_complete",
            "percent_savings",
            "average_throughput_gb_per_hr",
            "retain_until",
        ]
        with out_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for job_row in jobs:
                row = dict(job_row)
                groups = row.get("client_groups")
                if isinstance(groups, list):
                    row["client_groups"] = ";".join(groups)
                writer.writerow({key: row.get(key, "") for key in fieldnames})

    print(f"[green]Export wrote {len(jobs)} job(s) to {out_path}[/green]")
    if cache_generated_at:
        print(f"[dim]Data sourced from cache generated at {cache_generated_at}[/dim]")


@app.command("backups")
def backups(  # noqa: PLR0913
    limit: int = typer.Option(100, "--limit", min=0, help="Maximum number of jobs to fetch (0 = all)."),
    since: str = typer.Option("24h", "--since", help="Lookback window (e.g. 24h, 7d, or ISO8601 timestamp)."),
    client_filter: str = typer.Option("", "--client", help="Filter by client name or ID."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of a table."),
    refresh_cache: bool = typer.Option(False, "--refresh-cache", help="Force a live API refresh before listing."),
    retained_only: bool = typer.Option(False, "--retained", help="Only include jobs that have a future retention date."),
    export_csv: bool = typer.Option(False, "--export-csv", help="Write the results to a CSV report."),
    export_xlsx: bool = typer.Option(False, "--export-xlsx", help="Write the results to an Excel report."),
    outfile: str = typer.Option("", "--out", help="Override the CSV output path."),
) -> None:
    since_dt = _parse_since_string(since)
    cache_generated_at: str | None = None
    total_available: int | None = None
    jobs: list[CommvaultJob] = []

    use_cache = not refresh_cache
    if use_cache:
        cached = _load_cached_jobs_for_backups(limit=limit, since=since_dt, client_filter=client_filter)
        if cached is not None:
            jobs, total_available, cache_generated_at = cached
        else:
            use_cache = False

    if not use_cache:
        client = _commvault_client_or_exit()
        job_list = _collect_commvault_jobs_for_ui(client, limit=limit, offset=0, since=since_dt)
        jobs = list(job_list.jobs)
        total_available = job_list.total_available or len(jobs)

        # Write to cache when --refresh-cache is used
        if refresh_cache and jobs:
            from datetime import UTC, datetime
            from infrastructure_atlas.env import project_root
            cache_payload = {
                "jobs": [_serialise_commvault_job(job) for job in jobs],
                "generated_at": datetime.now(tz=UTC).isoformat(),
                "total_cached": len(jobs),
                "version": 2,
            }
            root = project_root()
            data_dir = root / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            cache_path = data_dir / "commvault_backups.json"
            cache_tmp = cache_path.with_suffix(".json.tmp")
            with cache_tmp.open("w", encoding="utf-8") as f:
                json.dump(cache_payload, f, indent=2)
            cache_tmp.replace(cache_path)

        if client_filter:
            try:
                ref = _resolve_client(client, client_filter)
                target_id = ref.client_id
            except typer.BadParameter:
                target_id = None
                needle = client_filter.casefold()
            else:
                needle = None
            filtered: list[CommvaultJob] = []
            for job in jobs:
                if target_id is not None:
                    if job.client_id == target_id:
                        filtered.append(job)
                elif job.client_name and needle and needle in job.client_name.casefold():
                    filtered.append(job)
            jobs = filtered
        cache_generated_at = None

    if retained_only:
        now = _now_utc()
        jobs = [job for job in jobs if job.retain_until and job.retain_until > now]

    serialised = [_serialise_commvault_job(job) for job in jobs]

    export_paths: dict[str, Path] = {}
    export_labels = {"csv_path": "CSV report", "xlsx_path": "Excel report"}
    if export_csv or export_xlsx:
        base_target = Path(outfile) if outfile else _default_backups_outfile(client_filter)

    if export_csv:
        target = base_target.with_suffix(".csv") if base_target.suffix != ".csv" else base_target
        target.parent.mkdir(parents=True, exist_ok=True)
        import csv

        fieldnames = [
            "job_id",
            "job_type",
            "status",
            "localized_status",
            "localized_operation",
            "client_name",
            "client_id",
            "destination_client_name",
            "subclient_name",
            "backup_set_name",
            "application_name",
            "backup_level_name",
            "plan_name",
            "client_groups",
            "storage_policy_name",
            "start_time",
            "end_time",
            "elapsed_seconds",
            "size_of_application_bytes",
            "size_on_media_bytes",
            "total_num_files",
            "percent_complete",
            "percent_savings",
            "average_throughput_gb_per_hr",
            "retain_until",
        ]
        with target.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for job_row in serialised:
                row = dict(job_row)
                groups = row.get("client_groups")
                if isinstance(groups, list):
                    row["client_groups"] = ";".join(groups)
                writer.writerow({key: row.get(key, "") for key in fieldnames})
        export_paths["csv_path"] = target

    if export_xlsx:
        target = base_target.with_suffix(".xlsx") if base_target.suffix != ".xlsx" else base_target
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            from openpyxl import Workbook  # type: ignore
        except ImportError as exc:  # pragma: no cover - dependency issue
            print(f"[red]openpyxl is required for --export-xlsx: {exc}[/red]")
        else:
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Commvault Backups"

            headers = [
                "job_id",
                "job_type",
                "status",
                "localized_status",
                "localized_operation",
                "client_name",
                "client_id",
                "destination_client_name",
                "subclient_name",
                "backup_set_name",
                "application_name",
                "backup_level_name",
                "plan_name",
                "client_groups",
                "storage_policy_name",
                "start_time",
                "end_time",
                "elapsed_seconds",
                "size_of_application_bytes",
                "size_on_media_bytes",
                "total_num_files",
                "percent_complete",
                "percent_savings",
                "average_throughput_gb_per_hr",
                "retain_until",
            ]
            sheet.append(headers)

            for job_row in serialised:
                row = dict(job_row)
                groups = row.get("client_groups")
                if isinstance(groups, list):
                    row["client_groups"] = ";".join(groups)
                sheet.append([row.get(header, "") for header in headers])

            workbook.save(target)
            export_paths["xlsx_path"] = target

    if json_output:
        payload: dict[str, Any] = {
            "returned": len(serialised),
            "total_available": total_available,
            "jobs": serialised,
            "source": "cache" if cache_generated_at else "api",
            "retained_only": retained_only,
        }
        if cache_generated_at:
            payload["cache_generated_at"] = cache_generated_at
        for key, path in export_paths.items():
            payload[key] = str(path)
        typer.echo(json.dumps(payload, indent=2))
        return

    if not jobs:
        hint = " Run with --refresh-cache after warming the cache." if use_cache else ""
        print(f"[yellow]No jobs matched the selection.{hint}[/yellow]")
        if cache_generated_at:
            print(f"[dim]Cache generated at {cache_generated_at}[/dim]")
        for label, path in export_paths.items():
            name = export_labels.get(label, label)
            print(f"[dim]{name} written to {path}[/dim]")
        return

    table = Table(show_header=True, header_style="bold", title="Commvault Jobs")
    table.add_column("Job ID", justify="right")
    table.add_column("Client")
    table.add_column("Status")
    table.add_column("Start")
    table.add_column("Duration")
    table.add_column("Retained Until")
    table.add_column("Size")

    for job in jobs:
        elapsed = f"{job.elapsed_seconds // 60}m" if job.elapsed_seconds else "-"
        table.add_row(
            str(job.job_id),
            job.client_name or "-",
            job.localized_status or job.status,
            _format_when(job.start_time),
            elapsed,
            _format_when(job.retain_until),
            _format_bytes(job.size_of_application_bytes),
        )

    console.print(table)
    source_label = "cache" if cache_generated_at else "API"
    total_display = total_available if total_available is not None else len(jobs)
    print(f"[dim]{len(jobs)} job(s) shown ({source_label} total {total_display})[/dim]")
    if cache_generated_at:
        print(f"[dim]Cache generated at {cache_generated_at}[/dim]")
    for label, path in export_paths.items():
        name = export_labels.get(label, label)
        print(f"[green]{name} wrote {len(serialised)} job(s) to {path}[/green]")


def _parse_since_string(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    if value.endswith("h") and value[:-1].isdigit():
        hours = int(value[:-1])
        return _parse_since(hours)
    if value.endswith("d") and value[:-1].isdigit():
        days = int(value[:-1])
        return _now_utc() - timedelta(days=days)
    try:
        return _parse_retain_after(value)
    except typer.BadParameter as exc:
        raise typer.BadParameter("--since expects <hours>h, <days>d, or ISO8601 timestamp") from exc


@storage_app.command("list")
def storage_list(
    json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of table."),
    refresh: bool = typer.Option(False, "--refresh-cache", help="Force refresh before listing."),
) -> None:
    client = _commvault_client_or_exit()
    try:
        pools = list(client.list_storage_pools())
    except CommvaultError as exc:  # pragma: no cover - network dependent
        print(f"[red]Failed to list storage pools:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if refresh:
        refreshed: list[CommvaultStoragePool] = []
        for pool in pools:
            try:
                details = client.get_storage_pool_details(pool.pool_id, summary=pool)
            except CommvaultError:
                refreshed.append(pool)
            else:
                refreshed.append(details.pool)
        pools = refreshed

    rows = [_storage_pool_to_row(pool) for pool in pools]
    if json_output:
        typer.echo(json.dumps(rows, indent=2))
        return

    table = Table(show_header=True, header_style="bold", title="Commvault Storage Pools")
    table.add_column("Pool ID", justify="right")
    table.add_column("Name")
    table.add_column("Status")
    table.add_column("Used")
    table.add_column("Capacity")
    for row in rows:
        table.add_row(
            str(row["pool_id"]),
            row["name"],
            row["status"] or "-",
            _format_bytes(row["used_bytes"]),
            _format_bytes(row["total_capacity_bytes"]),
        )
    console.print(table)


@storage_app.command("show")
def storage_show(
    pool_id: int = typer.Argument(..., help="Storage pool ID."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON instead of table."),
    refresh: bool = typer.Option(True, "--refresh-cache/--no-refresh-cache", help="Refresh before showing details."),
) -> None:
    client = _commvault_client_or_exit()
    try:
        summary = next((pool for pool in client.list_storage_pools() if pool.pool_id == pool_id), None)
        if summary is None:
            raise typer.BadParameter(f"Storage pool {pool_id} not found")
        details = client.get_storage_pool_details(pool_id, summary=summary if not refresh else None)
    except CommvaultError as exc:  # pragma: no cover - network dependent
        print(f"[red]Failed to load storage pool:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    payload = _storage_pool_to_row(details.pool)
    payload["details"] = details.details

    if json_output:
        typer.echo(json.dumps(payload, indent=2))
        return

    table = Table(show_header=True, header_style="bold", title=f"Storage Pool {payload['name']} ({pool_id})")
    table.add_column("Key")
    table.add_column("Value")
    for key, value in payload.items():
        if key == "details":
            continue
        table.add_row(key, str(value))
    console.print(table)
    if details.details:
        print("[dim]Raw details:[/dim]")
        typer.echo(json.dumps(details.details, indent=2))


def _storage_pool_to_row(pool: CommvaultStoragePool) -> dict[str, Any]:
    total_capacity = (pool.total_capacity_mb or 0) * 1024 * 1024
    used = (pool.size_on_disk_mb or 0) * 1024 * 1024
    return {
        "pool_id": pool.pool_id,
        "name": pool.name,
        "status": pool.status,
        "storage_policy_name": pool.storage_policy_name,
        "region_display_name": pool.region_display_name,
        "total_capacity_bytes": total_capacity,
        "used_bytes": used,
        "free_bytes": max(total_capacity - used, 0),
        "cloud_storage_class_name": pool.cloud_storage_class_name,
        "library_ids": list(pool.library_ids),
        "is_archive_storage": pool.is_archive_storage,
    }


__all__ = ["app"]
