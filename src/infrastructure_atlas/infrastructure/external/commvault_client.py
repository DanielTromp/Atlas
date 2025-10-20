"""Commvault Command Center API client."""
from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import requests

from infrastructure_atlas.domain.integrations.commvault import (
    CommvaultClientJobMetrics,
    CommvaultClientReference,
    CommvaultClientSummary,
    CommvaultJob,
    CommvaultJobList,
    CommvaultPlan,
    CommvaultStoragePool,
    CommvaultStoragePoolDetails,
)
from infrastructure_atlas.infrastructure.caching import TTLCache


def _read_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


_JOB_METRICS_CACHE_TTL = max(0.0, _read_float_env("COMMVAULT_JOB_CACHE_TTL", 600.0))
_JOB_METRICS_BUCKET_SECONDS = int(
    max(
        60.0,
        min(_read_float_env("COMMVAULT_JOB_CACHE_BUCKET_SECONDS", 300.0), max(_JOB_METRICS_CACHE_TTL, 60.0)),
    )
)

if _JOB_METRICS_CACHE_TTL > 0:
    _JOB_METRICS_CACHE: TTLCache[tuple[Any, ...], CommvaultClientJobMetrics] | None = TTLCache(
        ttl_seconds=_JOB_METRICS_CACHE_TTL,
        name="commvault.job_metrics",
    )
else:
    _JOB_METRICS_CACHE = None


def _datetime_bucket(value: datetime | None) -> int | None:
    if value is None:
        return None
    return int(value.timestamp() // _JOB_METRICS_BUCKET_SECONDS)


def _job_metrics_cache_key(
    client_id: int,
    query: CommvaultJobQuery,
    since_dt: datetime | None,
    retain_cutoff: datetime | None,
) -> tuple[Any, ...] | None:
    if _JOB_METRICS_CACHE is None:
        return None
    return (
        client_id,
        int(query.limit),
        int(query.window_hours),
        bool(query.descending),
        bool(query.require_retain),
        _datetime_bucket(since_dt),
        _datetime_bucket(retain_cutoff),
    )


class CommvaultError(Exception):
    """Generic Commvault integration error."""


class CommvaultConfigError(CommvaultError):
    """Raised when configuration is incomplete or invalid."""


class CommvaultAuthError(CommvaultError):
    """Raised when authentication with the Commvault API fails."""


class CommvaultResponseError(CommvaultError):
    """Raised when Commvault returns an unexpected response."""


@dataclass(slots=True)
class CommvaultClientConfig:
    """Runtime configuration for the Commvault client."""

    base_url: str
    authtoken: str | None = None
    username: str | None = None
    password: str | None = None
    verify_tls: bool | str = True
    timeout: float = 30.0


@dataclass(slots=True)
class CommvaultJobQuery:
    limit: int = 0
    since: datetime | None = None
    window_hours: int = 0
    descending: bool = True
    retain_cutoff: datetime | None = None
    require_retain: bool = False
    refresh_cache: bool = False


class CommvaultClient:
    """Thin wrapper around the Commvault Command Center REST API."""

    def __init__(self, config: CommvaultClientConfig) -> None:
        if not config.base_url:
            raise CommvaultConfigError("Commvault base URL is required")
        self._config = config
        self._api_root = _normalise_api_root(config.base_url)
        self._session = requests.Session()
        self._session.verify = config.verify_tls
        self._session.headers.update({"Accept": "application/json"})
        self._authtoken: str | None = config.authtoken

    def list_jobs(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        job_type: str | None = "Backup",
        sort_by: str | None = None,
        descending: bool = False,
    ) -> CommvaultJobList:
        """Return a page of jobs from the Commvault API."""

        params: dict[str, Any] = {"limit": max(limit, 1)}
        if offset:
            params["offset"] = max(offset, 0)
        if job_type:
            params["jobType"] = job_type
        if sort_by:
            params["sortField"] = sort_by
            params["sortDirection"] = "DESC" if descending else "ASC"

        data = self._request("GET", "Job", params=params)
        total = _to_int(data.get("totalRecordsWithoutPaging"))
        jobs_payload = data.get("jobs")
        jobs: list[CommvaultJob] = []
        if isinstance(jobs_payload, Sequence):
            for entry in jobs_payload:
                summary = entry.get("jobSummary") if isinstance(entry, Mapping) else None
                if isinstance(summary, Mapping):
                    jobs.append(_parse_job_summary(summary))
        return CommvaultJobList(total_available=total, jobs=tuple(jobs))

    def list_storage_pools(self) -> tuple[CommvaultStoragePool, ...]:
        """Return summary information for all configured storage pools."""

        data = self._request("GET", "StoragePool")
        pools_payload = data.get("storagePoolList")
        if not isinstance(pools_payload, Sequence):
            return ()
        pools: list[CommvaultStoragePool] = []
        for payload in pools_payload:
            if isinstance(payload, Mapping):
                pools.append(_parse_storage_pool(payload))
        return tuple(pools)

    def get_storage_pool_details(
        self, pool_id: int, *, summary: CommvaultStoragePool | None = None
    ) -> CommvaultStoragePoolDetails:
        """Return detailed information for a storage pool."""

        data = self._request("GET", f"StoragePool/{pool_id}")
        details = data.get("storagePoolDetails")
        if not isinstance(details, Mapping):
            details = {}
        if summary is None:
            summary = next((pool for pool in self.list_storage_pools() if pool.pool_id == pool_id), None)
        if summary is None:
            raise CommvaultResponseError(f"Storage pool {pool_id} not found")
        return CommvaultStoragePoolDetails(pool=summary, details=details)

    def list_clients(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[CommvaultClientReference, ...]:
        """Return lightweight references for Commvault clients."""

        params: dict[str, Any] = {"limit": max(1, limit)}
        if offset:
            params["offset"] = max(offset, 0)
        data = self._request("GET", "Client", params=params)
        clients = data.get("clientProperties")
        if not isinstance(clients, Sequence):
            return ()
        references: list[CommvaultClientReference] = []
        for payload in clients:
            if not isinstance(payload, Mapping):
                continue
            ref = _parse_client_reference(payload)
            if ref:
                references.append(ref)
        return tuple(references)

    def get_client_summary(
        self,
        client_id: int,
        *,
        job_query: CommvaultJobQuery | None = None,
    ) -> CommvaultClientSummary:
        """Return summary information for a client, optionally with recent job metrics."""

        detail = self._request("GET", f"Client/{client_id}")
        job_metrics: CommvaultClientJobMetrics | None = None
        query = job_query or CommvaultJobQuery()
        if query.limit > 0:
            job_metrics = self._get_client_job_metrics(client_id, query)
        return _parse_client_summary(detail, job_metrics)

    def list_virtual_machines(
        self,
        *,
        limit: int = 500,
        offset: int = 0,
    ) -> tuple[CommvaultClientReference, ...]:
        """Return references to virtual machines (VM clients)."""

        params: dict[str, Any] = {"limit": max(1, limit)}
        if offset:
            params["offset"] = max(0, offset)
        data = self._request("GET", "VM", params=params)
        vm_list = data.get("vmStatusInfoList")
        if not isinstance(vm_list, Sequence):
            return ()
        refs: list[CommvaultClientReference] = []
        for vm in vm_list:
            if not isinstance(vm, Mapping):
                continue
            client_info = vm.get("client")
            if not isinstance(client_info, Mapping):
                continue
            client_id = _to_int(client_info.get("clientId"))
            name = _to_optional_str(vm.get("name"))
            if not client_id or not name:
                continue
            refs.append(
                CommvaultClientReference(
                    client_id=client_id,
                    name=name,
                    display_name=_to_optional_str(vm.get("displayName")) or name,
                )
            )
        return tuple(refs)

    def list_plans(
        self,
        *,
        limit: int = 200,
        offset: int = 0,
        plan_type: str | None = None,
    ) -> tuple[CommvaultPlan, ...]:
        """Return summary information for Commvault plans."""

        params: dict[str, Any] = {"limit": max(1, limit)}
        if offset:
            params["offset"] = max(0, offset)
        if plan_type:
            params["planType"] = plan_type

        data = self._request("GET", "Plan", params=params)
        plans_payload = _extract_plans_payload(data)
        plans: list[CommvaultPlan] = []
        for payload in plans_payload:
            if not isinstance(payload, Mapping):
                continue
            plan = _parse_plan_summary(payload)
            if plan is not None:
                plans.append(plan)
        return tuple(plans)

    def get_plan_details(self, plan_id: int) -> Mapping[str, Any]:
        """Return detailed information for a specific Commvault plan."""

        data = self._request("GET", f"Plan/{plan_id}")
        if not isinstance(data, Mapping):
            return {}
        detail = data.get("planDetail")
        if isinstance(detail, Mapping):
            return detail
        details = data.get("planDetails")
        if isinstance(details, Sequence) and details:
            first = details[0]
            if isinstance(first, Mapping):
                return first
        return data

    def _get_client_job_metrics(
        self,
        client_id: int,
        query: CommvaultJobQuery,
    ) -> CommvaultClientJobMetrics:
        chunk_size = max(25, min(200, query.limit or 200))
        since_dt = query.since
        retain_min = query.retain_cutoff
        if query.require_retain and retain_min is None:
            retain_min = datetime.now(tz=UTC)

        def _load_uncached() -> CommvaultClientJobMetrics:
            try:
                initial = self.list_jobs(limit=1, offset=0, job_type="Backup")
            except CommvaultError:
                initial = CommvaultJobList(total_available=None, jobs=())

            total_available = initial.total_available or len(initial.jobs)
            if not total_available:
                return CommvaultClientJobMetrics(
                    window_hours=query.window_hours,
                    job_count=0,
                    total_application_bytes=0,
                    total_media_bytes=0,
                    last_job_start=None,
                    within_window=False,
                    descending=query.descending,
                    retain_cutoff=retain_min,
                    retain_required=query.require_retain,
                    fetched_at=datetime.now(tz=UTC),
                    jobs=(),
                )

            filtered: list[CommvaultJob] = []
            total_app = 0
            total_media = 0
            latest_overall: datetime | None = None
            encountered = False

            processed_from_tail = 0
            max_iterations = 100
            iterations = 0

            while (
                iterations < max_iterations
                and processed_from_tail < total_available
                and (query.limit <= 0 or len(filtered) < query.limit)
            ):
                remaining = total_available - processed_from_tail
                fetch_count = min(chunk_size, remaining)
                if fetch_count <= 0:
                    break

                offset = max(0, total_available - processed_from_tail - fetch_count)
                try:
                    batch = self.list_jobs(limit=fetch_count, offset=offset, job_type="Backup")
                except CommvaultError:
                    break

                jobs_payload = list(batch.jobs)
                if batch.total_available:
                    total_available = batch.total_available
                    remaining = max(0, total_available - processed_from_tail)
                    fetch_count = min(fetch_count, remaining)
                    offset = max(0, total_available - processed_from_tail - fetch_count)
                iterations += 1
                if not jobs_payload:
                    break

                processed_from_tail += len(jobs_payload)

                for job in reversed(jobs_payload):
                    if job.client_id and job.client_id != client_id:
                        continue
                    if job.start_time and (latest_overall is None or job.start_time > latest_overall):
                        latest_overall = job.start_time
                    if since_dt and job.start_time and job.start_time < since_dt:
                        continue
                    encountered = True
                    if retain_min:
                        if job.retain_until is None:
                            if query.require_retain:
                                continue
                        elif job.retain_until < retain_min:
                            continue
                    elif query.require_retain and job.retain_until is None:
                        continue
                    filtered.append(job)
                    if job.size_of_application_bytes:
                        total_app += job.size_of_application_bytes
                    if job.size_on_media_bytes:
                        total_media += job.size_on_media_bytes
                    if query.limit > 0 and len(filtered) >= query.limit:
                        break

                if query.limit > 0 and len(filtered) >= query.limit:
                    break

                if since_dt:
                    oldest = jobs_payload[0]
                    if oldest.start_time and oldest.start_time < since_dt:
                        break

            if query.limit and len(filtered) > query.limit:
                filtered = filtered[: query.limit]

            last_start = None
            for job in filtered:
                if job.start_time and (last_start is None or job.start_time > last_start):
                    last_start = job.start_time
            if last_start is None:
                last_start = latest_overall

            if not query.descending:
                filtered = list(reversed(filtered))

            return CommvaultClientJobMetrics(
                window_hours=query.window_hours,
                job_count=len(filtered),
                total_application_bytes=total_app,
                total_media_bytes=total_media,
                last_job_start=last_start,
                within_window=encountered,
                descending=query.descending,
                retain_cutoff=retain_min,
                retain_required=query.require_retain,
                fetched_at=datetime.now(tz=UTC),
                jobs=tuple(filtered),
            )

        cache_key = _job_metrics_cache_key(client_id, query, since_dt, retain_min)
        if query.refresh_cache and cache_key is not None and _JOB_METRICS_CACHE is not None:
            _JOB_METRICS_CACHE.invalidate(cache_key)

        if cache_key is not None and _JOB_METRICS_CACHE is not None and not query.refresh_cache:
            return _JOB_METRICS_CACHE.get(cache_key, _load_uncached)

        return _load_uncached()

    # ------------------------------------------------------------------
    # Internal helpers
    def _ensure_token(self) -> str:
        if self._authtoken:
            return self._authtoken
        if self._config.username and self._config.password:
            self._authtoken = self._login()
            return self._authtoken
        raise CommvaultAuthError("No Commvault authentication token configured")

    def _login(self) -> str:
        payload = {"username": self._config.username, "password": self._config.password}
        response = self._session.post(
            self._url("Login"),
            json=payload,
            timeout=self._config.timeout,
        )
        if response.status_code in {401, 403}:
            raise CommvaultAuthError("Commvault login rejected credentials")
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:  # pragma: no cover - network dependant
            raise CommvaultAuthError(str(exc)) from exc
        data = _parse_json(response)
        token: Any = None
        if isinstance(data, Mapping):
            token = data.get("token") or data.get("authToken") or data.get("authtoken")
            if token is None and isinstance(data.get("dm2ContentIndexing_CheckCredentialResp"), Mapping):
                nested = data["dm2ContentIndexing_CheckCredentialResp"]
                token = nested.get("token") or nested.get("authtoken")
        if not token:
            message = _login_error_message(data)
            raise CommvaultAuthError(message)
        return str(token)

    def _request(self, method: str, path: str, *, params: Mapping[str, Any] | None = None, json: Any = None) -> Mapping[str, Any]:
        headers = {"Authtoken": self._ensure_token()}
        try:
            response = self._session.request(
                method,
                self._url(path),
                params=params,
                json=json,
                headers=headers,
                timeout=self._config.timeout,
            )
        except requests.RequestException as exc:  # pragma: no cover - network dependant
            raise CommvaultError(str(exc)) from exc
        if response.status_code in {401, 403}:
            raise CommvaultAuthError(
                f"Commvault API rejected the token (HTTP {response.status_code})"
            )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:  # pragma: no cover - network dependant
            raise CommvaultResponseError(str(exc)) from exc
        data = _parse_json(response)
        if _contains_error(data):
            raise _response_error_from_payload(data)
        if not isinstance(data, Mapping):
            raise CommvaultResponseError("Commvault API returned unexpected data type")
        return data

    def _url(self, path: str) -> str:
        segment = path.lstrip("/")
        return f"{self._api_root}/{segment}"


# ----------------------------------------------------------------------
# Parsing helpers


def _parse_job_summary(summary: Mapping[str, Any]) -> CommvaultJob:
    client_groups = _extract_client_groups(summary)
    return CommvaultJob(
        job_id=_to_int(summary.get("jobId")) or 0,
        job_type=_to_str(summary.get("jobType")) or "",
        status=_to_str(summary.get("status")) or "",
        localized_status=_to_optional_str(summary.get("localizedStatus")),
        localized_operation=_to_optional_str(summary.get("localizedOperationName")),
        client_name=_extract_client_name(summary),
        client_id=_extract_destination_client_id(summary),
        destination_client_name=_extract_destination_client_name(summary),
        subclient_name=_extract_subclient_name(summary),
        backup_set_name=_to_optional_str(summary.get("backupSetName")),
        application_name=_to_optional_str(summary.get("appTypeName")),
        backup_level_name=_to_optional_str(
            summary.get("localizedBackupLevelName") or summary.get("backupLevelName")
        ),
        plan_name=_extract_plan_name(summary, client_groups),
        client_groups=client_groups,
        storage_policy_name=_extract_storage_policy(summary),
        start_time=_to_datetime(summary.get("jobStartTime")),
        end_time=_to_datetime(summary.get("jobEndTime")),
        elapsed_seconds=_to_int(summary.get("jobElapsedTime")),
        size_of_application_bytes=_to_int(summary.get("sizeOfApplication")),
        size_on_media_bytes=_to_int(summary.get("sizeOfMediaOnDisk")),
        total_num_files=_to_int(summary.get("totalNumOfFiles")),
        percent_complete=_to_float(summary.get("percentComplete")),
        percent_savings=_to_float(summary.get("percentSavings")),
        average_throughput=_to_float(summary.get("averageThroughput")),
        retain_until=_to_datetime(summary.get("retainUntil")),
    )


def _extract_client_name(summary: Mapping[str, Any]) -> str | None:
    dest_name = summary.get("destClientName")
    if dest_name:
        return _to_str(dest_name)
    subclient = summary.get("subclient")
    if isinstance(subclient, Mapping):
        candidate = subclient.get("clientName")
        if candidate:
            return _to_str(candidate)
    destination = summary.get("destinationClient")
    if isinstance(destination, Mapping):
        candidate = destination.get("clientName") or destination.get("displayName")
        if candidate:
            return _to_str(candidate)
    return None


def _extract_destination_client_name(summary: Mapping[str, Any]) -> str | None:
    destination = summary.get("destinationClient")
    if isinstance(destination, Mapping):
        candidate = destination.get("displayName") or destination.get("clientName")
        if candidate:
            return _to_str(candidate)
    dest_client_name = summary.get("destClientName")
    if dest_client_name:
        return _to_str(dest_client_name)
    return None


def _extract_destination_client_id(summary: Mapping[str, Any]) -> int | None:
    destination = summary.get("destinationClient")
    if isinstance(destination, Mapping):
        client_id = destination.get("clientId")
        if client_id is not None:
            return _to_int(client_id)
    if summary.get("client") and isinstance(summary.get("client"), Mapping):
        client_id = summary["client"].get("clientId")
        if client_id is not None:
            return _to_int(client_id)
    return None


def _extract_subclient_name(summary: Mapping[str, Any]) -> str | None:
    subclient_name = summary.get("subclientName")
    if subclient_name:
        return _to_str(subclient_name)
    subclient = summary.get("subclient")
    if isinstance(subclient, Mapping):
        candidate = subclient.get("subclientName")
        if candidate:
            return _to_str(candidate)
    return None


def _extract_storage_policy(summary: Mapping[str, Any]) -> str | None:
    storage_policy = summary.get("storagePolicy")
    if isinstance(storage_policy, Mapping):
        candidate = storage_policy.get("storagePolicyName")
        if candidate:
            return _to_str(candidate)
    return None


def _extract_client_groups(summary: Mapping[str, Any]) -> tuple[str, ...]:
    groups = summary.get("clientGroups")
    if not isinstance(groups, Sequence):
        return ()
    result: list[str] = []
    for group in groups:
        if not isinstance(group, Mapping):
            continue
        name = group.get("clientGroupName") or group.get("name")
        if not name:
            continue
        text = _to_str(name).strip()
        if text:
            result.append(text)
    return tuple(result)


def _extract_plan_name(summary: Mapping[str, Any], client_groups: tuple[str, ...]) -> str | None:
    plan = summary.get("plan") or summary.get("planEntity") or summary.get("planInfo")
    if isinstance(plan, Mapping):
        for key in ("planName", "name", "displayName"):
            candidate = plan.get(key)
            if candidate:
                text = _to_str(candidate).strip()
                if text:
                    return text
    plans = summary.get("plans")
    if isinstance(plans, Sequence):
        for item in plans:
            if not isinstance(item, Mapping):
                continue
            for key in ("planName", "name", "displayName"):
                candidate = item.get(key)
                if candidate:
                    text = _to_str(candidate).strip()
                    if text:
                        return text
    generic_groups = {"all agents", "active backups", "updates needed", "mobile operations"}
    preferred = [
        group
        for group in client_groups
        if group and group.strip().lower() not in generic_groups and "plan" in group.strip().lower()
    ]
    if preferred:
        return preferred[0]
    fallback = [
        group
        for group in client_groups
        if group and group.strip().lower() not in generic_groups
    ]
    if fallback:
        return fallback[0]
    return client_groups[0] if client_groups else None


_PLAN_TYPE_LABELS: dict[int, str] = {
    2: "Server",
}


def _extract_plans_payload(data: Mapping[str, Any]) -> Sequence[Any]:
    if isinstance(data, Sequence):
        return data
    for key in (
        "plans",
        "planList",
        "planDetails",
        "planSummary",
        "planSummaryList",
        "plan",
        "items",
        "plansList",
    ):
        value = data.get(key)
        if isinstance(value, Sequence):
            return value
    single = data.get("planDetail") or data.get("plan")
    if isinstance(single, Mapping):
        return [single]
    return []


def _parse_plan_summary(payload: Mapping[str, Any]) -> CommvaultPlan | None:
    merged = dict(payload)
    for key in (
        "planDetail",
        "planInfo",
        "planProperties",
        "planSummary",
        "plan",
        "summary",
    ):
        nested = payload.get(key)
        if isinstance(nested, Mapping):
            for nested_key, nested_value in nested.items():
                merged.setdefault(nested_key, nested_value)

    plan_id = _to_int(
        merged.get("planId")
        or merged.get("planID")
        or merged.get("id")
        or merged.get("planGuid")
    )
    name = _to_optional_str(
        merged.get("planName")
        or merged.get("name")
        or merged.get("displayName")
        or merged.get("plan")
    )
    if not name:
        if plan_id is not None:
            name = f"Plan {plan_id}"
        else:
            name = "Unnamed plan"

    plan_type_text = _to_optional_str(
        merged.get("planType")
        or merged.get("plan_type")
        or merged.get("planCategory")
    )
    plan_type_code = _to_int(
        merged.get("type")
        or merged.get("planType")
        or merged.get("plan_type_code")
    )
    if plan_type_code is not None:
        plan_type_text = _PLAN_TYPE_LABELS.get(plan_type_code, plan_type_text or str(plan_type_code))
    elif plan_type_text and plan_type_text.isdigit():
        plan_type_text = _PLAN_TYPE_LABELS.get(int(plan_type_text), plan_type_text)

    summary_fields: dict[str, str] = {}
    plan_section = merged.get("plan")
    if isinstance(plan_section, Mapping):
        summary_fields = _parse_plan_summary_text(plan_section.get("planSummary"))

    associated_entities = _to_int(
        merged.get("associatedEntitiesCount")
        or merged.get("associatedEntities")
        or merged.get("noOfAssociations")
        or merged.get("numberOfClients")
        or merged.get("numberOfSubclients")
        or merged.get("entityCount")
        or merged.get("entitiesCount")
        or merged.get("numAssocEntities")
    )
    if associated_entities is None and summary_fields.get("AssociatedEntitiesCount"):
        associated_entities = _to_int(summary_fields.get("AssociatedEntitiesCount"))

    copy_count = _to_int(
        merged.get("numberOfCopies")
        or merged.get("copiesCount")
        or merged.get("copyCount")
        or merged.get("numCopies")
    )
    if copy_count is None:
        copies = merged.get("storagePolicies") or merged.get("storageCopyPolicies")
        if isinstance(copies, Sequence):
            copy_count = len(copies)
    if copy_count is None and summary_fields.get("NumberOfCopies"):
        copy_count = _to_int(summary_fields.get("NumberOfCopies"))

    status = _to_optional_str(
        merged.get("status")
        or merged.get("planStatus")
        or merged.get("state")
        or merged.get("statusName")
    )

    rpo = _extract_plan_rpo(merged)
    tags = _extract_plan_tags(payload, merged)

    return CommvaultPlan(
        plan_id=plan_id,
        name=name,
        plan_type=plan_type_text,
        associated_entities=associated_entities,
        rpo=rpo,
        copy_count=copy_count,
        status=status,
        tags=tags,
        raw=payload,
    )


def _extract_plan_rpo(payload: Mapping[str, Any]) -> str | None:
    plan_section = payload.get("plan")
    summary_fields: dict[str, str] = {}
    if isinstance(plan_section, Mapping):
        summary_fields = _parse_plan_summary_text(plan_section.get("planSummary"))
    result: str | None = None
    if summary_fields:
        rpo_hours = _to_int(summary_fields.get("RPOHours"))
        if rpo_hours is not None:
            result = _format_hours_label(rpo_hours)
        if result is None:
            rpo_minutes_field = summary_fields.get("RPOInMinutes") or summary_fields.get("RpoInMinutes")
            if rpo_minutes_field is not None:
                rpo_minutes = _to_int(rpo_minutes_field)
                if rpo_minutes is not None:
                    result = _format_minutes_label(rpo_minutes)

    if result is None:
        for key in ("formattedRpo", "displayRpo", "rpo", "rpoLabel", "planRpo", "rpoText"):
            value = payload.get(key)
            text = _normalise_plan_string(value)
            if text:
                result = text
                break

    if result is None:
        plan_sla = payload.get("planSla") or payload.get("sla") or payload.get("slaInfo")
        if isinstance(plan_sla, Mapping):
            for key in ("formattedRpo", "displayValue", "displayString", "rpoString", "rpoLabel", "rpo"):
                value = plan_sla.get(key)
                text = _normalise_plan_string(value)
                if text:
                    result = text
                    break
            if result is None:
                hours = _to_int(plan_sla.get("rpoInHours") or plan_sla.get("rpoHours"))
                if hours is not None:
                    result = _format_hours_label(hours)
                else:
                    minutes = _to_int(plan_sla.get("rpoInMinutes"))
                    if minutes is not None:
                        result = _format_minutes_label(minutes)

    if result is None:
        hours = _to_int(payload.get("rpoInHours") or payload.get("rpoHours"))
        if hours is not None:
            result = _format_hours_label(hours)
        else:
            minutes = _to_int(payload.get("rpoInMinutes"))
            if minutes is not None:
                result = _format_minutes_label(minutes)

    return result


def _normalise_plan_string(value: Any) -> str | None:
    if isinstance(value, Mapping):
        for key in ("displayValue", "displayString", "name", "value", "label", "text"):
            nested = value.get(key)
            if nested:
                return str(nested)
        return None
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _format_hours_label(hours: int) -> str:
    if hours < 0:
        hours = abs(hours)
    if hours == 0:
        return "0 hours"
    if hours % 24 == 0:
        days = hours // 24
        return f"{days} day" if days == 1 else f"{days} days"
    return f"{hours} hour" if hours == 1 else f"{hours} hours"


def _format_minutes_label(minutes: int) -> str:
    if minutes < 0:
        minutes = abs(minutes)
    if minutes == 0:
        return "0 minutes"
    if minutes % 1440 == 0:
        days = minutes // 1440
        return f"{days} day" if days == 1 else f"{days} days"
    if minutes % 60 == 0:
        hours = minutes // 60
        return _format_hours_label(hours)
    return f"{minutes} minute" if minutes == 1 else f"{minutes} minutes"


def _parse_plan_summary_text(value: Any) -> dict[str, str]:
    if not isinstance(value, str):
        return {}
    result: dict[str, str] = {}
    for segment in value.split(","):
        if ":" not in segment:
            continue
        key, raw_val = segment.split(":", 1)
        key = key.strip()
        val = raw_val.strip()
        if key:
            result[key] = val
    return result


def _extract_plan_tags(*payloads: Mapping[str, Any]) -> tuple[str, ...]:
    tags: list[str] = []
    seen: set[str] = set()

    def _add(tag_value: Any) -> None:
        text = _normalise_plan_string(tag_value)
        if not text:
            return
        key = text.casefold()
        if key in seen:
            return
        seen.add(key)
        tags.append(text)

    for payload in payloads:
        for key in ("planTags", "tags", "tagList"):
            value = payload.get(key)
            if isinstance(value, Sequence):
                for entry in value:
                    if isinstance(entry, Mapping):
                        for nested_key in ("name", "tagName", "displayName", "value", "label"):
                            nested_value = entry.get(nested_key)
                            if nested_value is not None:
                                _add(nested_value)
                                break
                    elif entry is not None:
                        _add(entry)
            elif value is not None:
                _add(value)

    return tuple(tags)


def _to_str(value: Any) -> str:
    return str(value)


def _to_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_datetime(value: Any) -> datetime | None:
    seconds = _to_int(value)
    if not seconds:
        return None
    try:
        return datetime.fromtimestamp(seconds, tz=UTC)
    except (OverflowError, OSError):  # pragma: no cover - outside typical range
        return None


def _parse_json(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError as exc:  # pragma: no cover - unexpected API response
        raise CommvaultResponseError("Failed to decode Commvault JSON response") from exc


def _contains_error(data: Any) -> bool:
    if not isinstance(data, Mapping):
        return False
    if data.get("errorCode"):
        return True
    err_list = data.get("errList")
    if isinstance(err_list, Sequence):
        return any(isinstance(item, Mapping) and item.get("errorCode") for item in err_list)
    return False


def _response_error_from_payload(data: Mapping[str, Any]) -> CommvaultError:
    message = _to_optional_str(data.get("errorMessage"))
    code = _to_int(data.get("errorCode"))
    if not message and isinstance(data.get("errList"), Sequence):
        for item in data.get("errList", []):
            if isinstance(item, Mapping) and item.get("errorCode"):
                code = _to_int(item.get("errorCode"))
                message = _to_optional_str(item.get("errLogMessage") or item.get("errorMessage"))
                break
    message = message or "Commvault API returned an error"
    if code in {401, 403, 5} or "access" in message.lower():
        return CommvaultAuthError(f"{message} (code {code})".strip())
    return CommvaultResponseError(f"{message} (code {code})".strip())


def _login_error_message(data: Any) -> str:
    if isinstance(data, Mapping):
        err_list = data.get("errList")
        if isinstance(err_list, Sequence):
            for item in err_list:
                if isinstance(item, Mapping):
                    msg = item.get("errLogMessage") or item.get("errorMessage")
                    if msg:
                        return str(msg)
        message = data.get("errorMessage")
        if message:
            return str(message)
        return "Commvault login failed"


def _normalise_api_root(base_url: str) -> str:
    trimmed = base_url.strip().rstrip("/")
    lowered = trimmed.lower()
    if lowered.endswith("/webconsole/api"):
        return trimmed
    if lowered.endswith("/webconsole"):
        return f"{trimmed}/api"
    return f"{trimmed}/webconsole/api"


def _parse_client_reference(payload: Mapping[str, Any]) -> CommvaultClientReference | None:
    client = payload.get("client")
    if not isinstance(client, Mapping):
        return None
    entity = client.get("clientEntity")
    if not isinstance(entity, Mapping):
        return None
    client_id = _to_int(entity.get("clientId"))
    name = _to_optional_str(entity.get("clientName") or entity.get("displayName"))
    if not client_id or not name:
        return None
    display = _to_optional_str(entity.get("displayName"))
    return CommvaultClientReference(client_id=client_id, name=name, display_name=display)


def _parse_client_summary(
    detail: Mapping[str, Any],
    job_metrics: CommvaultClientJobMetrics | None,
) -> CommvaultClientSummary:
    props_list = detail.get("clientProperties")
    props = props_list[0] if isinstance(props_list, Sequence) and props_list else {}
    client = props.get("client") if isinstance(props.get("client"), Mapping) else {}
    entity = client.get("clientEntity") if isinstance(client.get("clientEntity"), Mapping) else {}
    os_info = client.get("osInfo") if isinstance(client.get("osInfo"), Mapping) else {}
    os_display = os_info.get("OsDisplayInfo") if isinstance(os_info.get("OsDisplayInfo"), Mapping) else {}
    client_props = props.get("clientProps") if isinstance(props.get("clientProps"), Mapping) else {}
    readiness = props.get("clientReadiness") if isinstance(props.get("clientReadiness"), Mapping) else {}
    groups = props.get("clientGroups") if isinstance(props.get("clientGroups"), Sequence) else []
    ida_list = client.get("idaList") if isinstance(client.get("idaList"), Sequence) else []

    reference = CommvaultClientReference(
        client_id=_to_int(entity.get("clientId")) or 0,
        name=_to_optional_str(entity.get("clientName")) or "Unknown",
        display_name=_to_optional_str(entity.get("displayName")),
    )

    agent_apps: list[str] = []
    for item in ida_list:
        if not isinstance(item, Mapping):
            continue
        ida = item.get("idaEntity")
        if isinstance(ida, Mapping):
            app = _to_optional_str(ida.get("appName"))
            if app:
                agent_apps.append(app)

    group_names: list[str] = []
    for item in groups:
        if not isinstance(item, Mapping):
            continue
        name = _to_optional_str(item.get("clientGroupName") or item.get("name"))
        if name:
            group_names.append(name)

    readiness_status = _to_optional_str(readiness.get("readinessStatus"))
    online_time = readiness.get("onlineTime")
    if isinstance(online_time, Mapping):
        online_time = online_time.get("time")
    last_ready_time = _to_datetime(online_time)

    sla_status_code = _to_int(client_props.get("slaStatus"))
    sla_description = _to_optional_str(client_props.get("slaCategoryDescription"))

    summary_raw: Mapping[str, object] = props if isinstance(props, Mapping) else {}

    return CommvaultClientSummary(
        reference=reference,
        host_name=_to_optional_str(entity.get("hostName")),
        os_name=_to_optional_str(os_display.get("OSName")),
        os_type=_to_optional_str(os_info.get("Type")),
        os_subtype=_to_optional_str(os_info.get("SubType")),
        processor_type=_to_optional_str(os_display.get("ProcessorType")),
        cpu_count=_to_int(client_props.get("CPUCount")),
        is_media_agent=_to_bool(client_props.get("isMA")),
        is_virtual=_to_bool(
            client_props.get("IsVirtualClient") or client_props.get("isVirtualServerDiscoveredClient")
        ),
        is_infrastructure=_to_bool(client_props.get("isInfrastructure")),
        is_commserve=_to_bool(client_props.get("IsCommServer")),
        readiness_status=readiness_status.strip() if readiness_status else None,
        last_ready_time=last_ready_time,
        sla_status_code=sla_status_code,
        sla_description=sla_description,
        agent_applications=tuple(sorted(set(agent_apps))) if agent_apps else (),
        client_groups=tuple(sorted(set(group_names))) if group_names else (),
        job_metrics=job_metrics,
        raw=summary_raw,
    )


def _parse_storage_pool(payload: Mapping[str, Any]) -> CommvaultStoragePool:
    entity = payload.get("storagePoolEntity")
    name = _to_optional_str(_nested(entity, "storagePoolName"))
    if not name:
        name = _to_optional_str(_nested(payload.get("storagePool"), "clientGroupName")) or "Unknown"
    pool_id = _to_int(_nested(entity, "storagePoolId")) or 0
    storage_policy = payload.get("storagePolicyEntity")
    policy_id = _to_int(_nested(storage_policy, "storagePolicyId"))
    policy_name = _to_optional_str(_nested(storage_policy, "storagePolicyName"))
    region = payload.get("region") if isinstance(payload.get("region"), Mapping) else {}
    region_name = _to_optional_str(region.get("regionName"))
    region_display = _to_optional_str(region.get("displayName"))
    library_ids = tuple(
        _to_int(_nested(item, "libraryId"))
        for item in payload.get("libraryList", [])
        if isinstance(item, Mapping) and _to_int(_nested(item, "libraryId"))
    )
    return CommvaultStoragePool(
        pool_id=pool_id,
        name=name,
        status=_to_optional_str(payload.get("status")),
        storage_type_code=_to_int(payload.get("storageType")),
        storage_pool_type_code=_to_int(payload.get("storagePoolType")),
        storage_sub_type_code=_to_int(payload.get("storageSubType")),
        storage_policy_id=policy_id,
        storage_policy_name=policy_name,
        region_name=region_name,
        region_display_name=region_display,
        total_capacity_mb=_normalise_capacity_value(payload.get("totalCapacity")),
        size_on_disk_mb=_normalise_capacity_value(payload.get("sizeOnDisk")),
        total_free_space_mb=_normalise_capacity_value(payload.get("totalFreeSpace")),
        number_of_nodes=_to_int(payload.get("numberOfNodes")),
        is_archive_storage=_to_bool(payload.get("isArchiveStorage")),
        cloud_storage_class_name=_to_optional_str(payload.get("cloudStorageClassName")),
        library_ids=library_ids,
        raw=dict(payload),
    )


def _normalise_capacity_value(value: Any) -> int | None:
    number = _to_int(value)
    if number is None:
        return None
    return number


def _to_bool(value: Any) -> bool:
    intval = _to_int(value)
    if intval is None:
        return False
    return intval > 0


def _nested(payload: Mapping[str, Any] | None, key: str) -> Any:
    if not isinstance(payload, Mapping):
        return None
    return payload.get(key)
