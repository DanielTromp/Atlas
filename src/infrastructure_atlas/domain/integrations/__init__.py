"""Domain-level data models for external integrations.

These dataclasses describe the information exchanged with third-party systems
so application services can rely on typed, transport-agnostic contracts.
"""
from .backup import BackupJobSummary
from .commvault import (
    CommvaultClientJobMetrics,
    CommvaultClientReference,
    CommvaultClientSummary,
    CommvaultJob,
    CommvaultJobList,
    CommvaultStoragePool,
    CommvaultStoragePoolDetails,
)
from .confluence import ConfluenceAttachment
from .jira import JiraAttachment
from .netbox import NetboxDeviceRecord, NetboxVMRecord
from .vcenter import VCenterVM
from .zabbix import (
    ZabbixAckResult,
    ZabbixHost,
    ZabbixHostGroup,
    ZabbixInterface,
    ZabbixProblem,
    ZabbixProblemList,
)

__all__ = [
    "BackupJobSummary",
    "CommvaultClientJobMetrics",
    "CommvaultClientReference",
    "CommvaultClientSummary",
    "CommvaultJob",
    "CommvaultJobList",
    "CommvaultStoragePool",
    "CommvaultStoragePoolDetails",
    "ConfluenceAttachment",
    "JiraAttachment",
    "NetboxDeviceRecord",
    "NetboxVMRecord",
    "VCenterVM",
    "ZabbixAckResult",
    "ZabbixHost",
    "ZabbixHostGroup",
    "ZabbixInterface",
    "ZabbixProblem",
    "ZabbixProblemList",
]
