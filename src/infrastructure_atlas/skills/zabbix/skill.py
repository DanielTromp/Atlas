"""Zabbix skill implementation for agent workflows.

Provides monitoring and alerting actions:
- Get host details and status
- View current problems/alerts
- Search for hosts
- Acknowledge problems
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from infrastructure_atlas.infrastructure.external.zabbix_client import (
    ZabbixClient,
    ZabbixError,
)
from infrastructure_atlas.infrastructure.logging import get_logger
from infrastructure_atlas.skills.base import BaseSkill

logger = get_logger(__name__)


class ZabbixSkill(BaseSkill):
    """Skill for interacting with Zabbix monitoring system.

    Provides actions for:
    - Viewing host details and status
    - Getting current problems and alerts
    - Searching for monitored hosts
    - Acknowledging problems
    """

    name = "zabbix"
    description = "Interact with Zabbix monitoring system for alerts, hosts, and problems"
    category = "monitoring"

    def __init__(self) -> None:
        super().__init__()
        self._client: ZabbixClient | None = None

    def _get_client(self) -> ZabbixClient:
        """Get or create Zabbix client lazily."""
        if self._client is None:
            self._client = ZabbixClient.from_env()
        return self._client

    def initialize(self) -> None:
        """Register all Zabbix actions."""
        self.register_action(
            name="get_host",
            func=self._get_host,
            description="Get detailed information about a Zabbix host by ID",
            is_destructive=False,
        )

        self.register_action(
            name="search_hosts",
            func=self._search_hosts,
            description="Search for Zabbix hosts by name pattern (supports wildcards)",
            is_destructive=False,
        )

        self.register_action(
            name="get_problems",
            func=self._get_problems,
            description="Get current Zabbix problems/alerts with optional filters",
            is_destructive=False,
        )

        self.register_action(
            name="get_host_problems",
            func=self._get_host_problems,
            description="Get all current problems for a specific host",
            is_destructive=False,
        )

        self.register_action(
            name="acknowledge_problem",
            func=self._acknowledge_problem,
            description="Acknowledge a Zabbix problem/event with optional message",
            is_destructive=True,
            requires_confirmation=True,
        )

        self.register_action(
            name="get_interfaces",
            func=self._get_interfaces,
            description="Get Zabbix host interfaces by IP address",
            is_destructive=False,
        )

        logger.info("ZabbixSkill initialized with 6 actions")

    def _get_host(self, host_id: str) -> dict[str, Any]:
        """Get detailed host information.

        Args:
            host_id: The Zabbix host ID

        Returns:
            Host details including groups, interfaces, inventory, macros, and tags
        """
        try:
            client = self._get_client()
            host = client.get_host(host_id)

            return {
                "success": True,
                "host": {
                    "id": host.id,
                    "name": host.name,
                    "technical_name": host.technical_name,
                    "groups": [
                        {"id": g.id, "name": g.name}
                        for g in host.groups
                    ],
                    "interfaces": [
                        {
                            "id": iface.id,
                            "ip": iface.ip,
                            "dns": iface.dns,
                            "main": iface.main,
                            "type": iface.type,
                        }
                        for iface in host.interfaces
                    ],
                    "inventory": dict(host.inventory) if host.inventory else {},
                    "tags": [dict(t) for t in host.tags],
                },
            }
        except ZabbixError as e:
            logger.error(f"Failed to get Zabbix host {host_id}: {e}")
            return {"success": False, "error": str(e)}

    def _search_hosts(
        self,
        pattern: str,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Search for hosts by name pattern.

        Args:
            pattern: Search pattern (supports * wildcards)
            limit: Maximum number of results (default 50)

        Returns:
            List of matching hosts
        """
        try:
            client = self._get_client()
            hosts = client.search_hosts(pattern, limit=limit)

            return {
                "success": True,
                "count": len(hosts),
                "hosts": [
                    {
                        "id": h.id,
                        "name": h.name,
                        "technical_name": h.technical_name,
                    }
                    for h in hosts
                ],
            }
        except ZabbixError as e:
            logger.error(f"Failed to search Zabbix hosts with pattern '{pattern}': {e}")
            return {"success": False, "error": str(e)}

    def _get_problems(
        self,
        min_severity: int = 0,
        unacknowledged_only: bool = False,
        search: str | None = None,
        limit: int = 100,
        hours: int | None = None,
    ) -> dict[str, Any]:
        """Get current Zabbix problems.

        Args:
            min_severity: Minimum severity level (0-5, default 0)
                0 = Not classified
                1 = Information
                2 = Warning
                3 = Average
                4 = High
                5 = Disaster
            unacknowledged_only: Only show unacknowledged problems
            search: Optional search pattern for problem name
            limit: Maximum number of results (default 100)
            hours: Only show problems from last N hours

        Returns:
            List of current problems with details
        """
        try:
            client = self._get_client()

            # Calculate time_from if hours specified
            time_from = None
            if hours:
                time_from = int(datetime.now(UTC).timestamp()) - (hours * 3600)

            # Build severities list
            severities = list(range(min_severity, 6)) if min_severity > 0 else None

            problem_list = client.get_problems(
                severities=severities,
                unacknowledged=unacknowledged_only,
                search=search,
                limit=limit,
                time_from=time_from,
            )

            return {
                "success": True,
                "count": len(problem_list.items),
                "problems": [
                    {
                        "event_id": p.event_id,
                        "name": p.name,
                        "severity": p.severity,
                        "severity_name": self._severity_name(p.severity),
                        "status": p.status,
                        "acknowledged": p.acknowledged,
                        "suppressed": p.suppressed,
                        "host_name": p.host_name,
                        "host_id": p.host_id,
                        "duration": p.duration,
                        "clock_iso": p.clock_iso,
                        "opdata": p.opdata,
                        "host_url": p.host_url,
                        "problem_url": p.problem_url,
                        "tags": [dict(t) for t in p.tags],
                        "host_groups": [
                            {"id": g.id, "name": g.name}
                            for g in p.host_groups
                        ],
                    }
                    for p in problem_list.items
                ],
            }
        except ZabbixError as e:
            logger.error(f"Failed to get Zabbix problems: {e}")
            return {"success": False, "error": str(e)}

    def _get_host_problems(
        self,
        host_id: str,
        min_severity: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Get all current problems for a specific host.

        Args:
            host_id: The Zabbix host ID
            min_severity: Minimum severity level (0-5, default 0)
            limit: Maximum number of results (default 50)

        Returns:
            List of problems for the specified host
        """
        try:
            client = self._get_client()

            severities = list(range(min_severity, 6)) if min_severity > 0 else None

            problem_list = client.get_problems(
                hostids=[int(host_id)],
                severities=severities,
                limit=limit,
            )

            return {
                "success": True,
                "host_id": host_id,
                "count": len(problem_list.items),
                "problems": [
                    {
                        "event_id": p.event_id,
                        "name": p.name,
                        "severity": p.severity,
                        "severity_name": self._severity_name(p.severity),
                        "status": p.status,
                        "acknowledged": p.acknowledged,
                        "duration": p.duration,
                        "clock_iso": p.clock_iso,
                        "opdata": p.opdata,
                        "problem_url": p.problem_url,
                    }
                    for p in problem_list.items
                ],
            }
        except ZabbixError as e:
            logger.error(f"Failed to get problems for host {host_id}: {e}")
            return {"success": False, "error": str(e)}

    def _acknowledge_problem(
        self,
        event_id: str,
        message: str | None = None,
    ) -> dict[str, Any]:
        """Acknowledge a Zabbix problem/event.

        Args:
            event_id: The Zabbix event ID to acknowledge
            message: Optional acknowledgment message

        Returns:
            Acknowledgment result
        """
        try:
            client = self._get_client()
            result = client.acknowledge([event_id], message=message)

            return {
                "success": True,
                "acknowledged_events": list(result.succeeded),
                "message": message or "Acknowledged via Infrastructure Atlas",
            }
        except ZabbixError as e:
            logger.error(f"Failed to acknowledge event {event_id}: {e}")
            return {"success": False, "error": str(e)}

    def _get_interfaces(
        self,
        ip_address: str,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Get Zabbix host interfaces by IP address.

        Args:
            ip_address: IP address to search for
            limit: Maximum number of results (default 50)

        Returns:
            List of matching interfaces
        """
        try:
            client = self._get_client()
            interfaces = client.interfaces_by_ip(ip_address, limit=limit)

            return {
                "success": True,
                "count": len(interfaces),
                "interfaces": [
                    {
                        "id": iface.id,
                        "ip": iface.ip,
                        "dns": iface.dns,
                        "main": iface.main,
                        "type": iface.type,
                    }
                    for iface in interfaces
                ],
            }
        except ZabbixError as e:
            logger.error(f"Failed to get interfaces for IP {ip_address}: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def _severity_name(severity: int) -> str:
        """Convert severity number to name."""
        names = {
            0: "Not classified",
            1: "Information",
            2: "Warning",
            3: "Average",
            4: "High",
            5: "Disaster",
        }
        return names.get(severity, f"Unknown ({severity})")


__all__ = ["ZabbixSkill"]
