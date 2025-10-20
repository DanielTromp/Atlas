"""Domain data models for interacting with Zabbix."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TypeAlias

JSONPrimitive: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONPrimitive | Sequence["JSONValue"] | Mapping[str, "JSONValue"]


@dataclass(slots=True)
class ZabbixHostGroup:
    id: str
    name: str


@dataclass(slots=True)
class ZabbixInterface:
    id: str
    ip: str | None
    dns: str | None
    main: bool
    type: str | None


@dataclass(slots=True)
class ZabbixHost:
    id: str
    name: str
    technical_name: str | None
    groups: tuple[ZabbixHostGroup, ...]
    interfaces: tuple[ZabbixInterface, ...]
    inventory: Mapping[str, JSONValue]
    macros: tuple[Mapping[str, JSONValue], ...]
    tags: tuple[Mapping[str, JSONValue], ...]
    raw: Mapping[str, JSONValue]


@dataclass(slots=True)
class ZabbixProblem:
    event_id: str
    name: str
    opdata: str | None
    severity: int
    acknowledged: bool
    suppressed: bool
    status: str
    clock: int
    clock_iso: str
    host_name: str | None
    host_id: str | None
    host_url: str | None
    problem_url: str | None
    tags: tuple[Mapping[str, JSONValue], ...]


@dataclass(slots=True)
class ZabbixProblemList:
    items: tuple[ZabbixProblem, ...]

    @property
    def count(self) -> int:
        return len(self.items)


@dataclass(slots=True)
class ZabbixAckResult:
    succeeded: tuple[str, ...]
    response: Mapping[str, JSONValue]
