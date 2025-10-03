"""Typed models describing Commvault backup jobs."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class CommvaultJob:
    """Normalized representation of a Commvault job summary."""

    job_id: int
    job_type: str
    status: str
    localized_status: str | None
    localized_operation: str | None
    client_name: str | None
    client_id: int | None
    destination_client_name: str | None
    subclient_name: str | None
    backup_set_name: str | None
    application_name: str | None
    backup_level_name: str | None
    plan_name: str | None
    client_groups: tuple[str, ...]
    storage_policy_name: str | None
    start_time: datetime | None
    end_time: datetime | None
    elapsed_seconds: int | None
    size_of_application_bytes: int | None
    size_on_media_bytes: int | None
    total_num_files: int | None
    percent_complete: float | None
    percent_savings: float | None
    average_throughput: float | None
    retain_until: datetime | None


@dataclass(slots=True)
class CommvaultJobList:
    """A collection of jobs along with metadata from the Commvault API."""

    total_available: int | None
    jobs: tuple[CommvaultJob, ...]

    @property
    def returned(self) -> int:
        return len(self.jobs)


@dataclass(slots=True)
class CommvaultStoragePool:
    """Summary of a Commvault storage pool."""

    pool_id: int
    name: str
    status: str | None
    storage_type_code: int | None
    storage_pool_type_code: int | None
    storage_sub_type_code: int | None
    storage_policy_id: int | None
    storage_policy_name: str | None
    region_name: str | None
    region_display_name: str | None
    total_capacity_mb: int | None
    size_on_disk_mb: int | None
    total_free_space_mb: int | None
    number_of_nodes: int | None
    is_archive_storage: bool
    cloud_storage_class_name: str | None
    library_ids: tuple[int, ...]
    raw: Mapping[str, object]


@dataclass(slots=True)
class CommvaultStoragePoolDetails:
    """Detailed view of a Commvault storage pool."""

    pool: CommvaultStoragePool
    details: Mapping[str, object]


@dataclass(slots=True)
class CommvaultClientReference:
    """Lightweight identifier for a Commvault client/server."""

    client_id: int
    name: str
    display_name: str | None = None


@dataclass(slots=True)
class CommvaultClientJobMetrics:
    """Aggregated job statistics for a client within a time window."""

    window_hours: int
    job_count: int
    total_application_bytes: int
    total_media_bytes: int
    last_job_start: datetime | None
    within_window: bool
    descending: bool
    retain_cutoff: datetime | None
    retain_required: bool
    fetched_at: datetime
    jobs: tuple[CommvaultJob, ...]


@dataclass(slots=True)
class CommvaultClientSummary:
    """Summary information about a Commvault client/server."""

    reference: CommvaultClientReference
    host_name: str | None
    os_name: str | None
    os_type: str | None
    os_subtype: str | None
    processor_type: str | None
    cpu_count: int | None
    is_media_agent: bool
    is_virtual: bool
    is_infrastructure: bool
    is_commserve: bool
    readiness_status: str | None
    last_ready_time: datetime | None
    sla_status_code: int | None
    sla_description: str | None
    agent_applications: tuple[str, ...]
    client_groups: tuple[str, ...]
    job_metrics: CommvaultClientJobMetrics | None
    raw: Mapping[str, object]
