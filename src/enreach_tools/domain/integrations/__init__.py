"""Domain-level data models for external integrations.

These dataclasses describe the information exchanged with third-party systems
so application services can rely on typed, transport-agnostic contracts.
"""
from .backup import BackupJobSummary
from .confluence import ConfluenceAttachment
from .netbox import NetboxDeviceRecord, NetboxVMRecord
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
    "ConfluenceAttachment",
    "NetboxDeviceRecord",
    "NetboxVMRecord",
    "ZabbixAckResult",
    "ZabbixHost",
    "ZabbixHostGroup",
    "ZabbixInterface",
    "ZabbixProblem",
    "ZabbixProblemList",
]
