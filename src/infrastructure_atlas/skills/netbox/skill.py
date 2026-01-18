"""NetBox skill implementation for agent workflows.

Provides CMDB/IPAM actions:
- Get device and VM details
- Search for assets
- List devices and VMs with filtering
"""

from __future__ import annotations

import os
import re
from typing import Any

from infrastructure_atlas.infrastructure.external.netbox_client import (
    NetboxClient,
    NetboxClientConfig,
)
from infrastructure_atlas.infrastructure.logging import get_logger
from infrastructure_atlas.skills.base import BaseSkill

logger = get_logger(__name__)


class NetBoxSkill(BaseSkill):
    """Skill for interacting with NetBox CMDB/IPAM system.

    Provides actions for:
    - Getting device and VM details
    - Searching for infrastructure assets
    - Listing all devices and VMs
    """

    name = "netbox"
    description = "Interact with NetBox CMDB for devices, VMs, and IP addresses"
    category = "cmdb"

    def __init__(self) -> None:
        super().__init__()
        self._client: NetboxClient | None = None

    def _get_client(self) -> NetboxClient:
        """Get or create NetBox client lazily."""
        if self._client is None:
            url = os.getenv("NETBOX_URL", "").strip()
            token = os.getenv("NETBOX_TOKEN", "").strip()
            if not url or not token:
                raise ValueError("NETBOX_URL and NETBOX_TOKEN environment variables required")
            config = NetboxClientConfig(url=url, token=token)
            self._client = NetboxClient(config)
        return self._client

    def initialize(self) -> None:
        """Register all NetBox actions."""
        self.register_action(
            name="get_device",
            func=self._get_device,
            description="Get detailed information about a NetBox device by ID",
            is_destructive=False,
        )

        self.register_action(
            name="get_vm",
            func=self._get_vm,
            description="Get detailed information about a NetBox virtual machine by ID",
            is_destructive=False,
        )

        self.register_action(
            name="search_devices",
            func=self._search_devices,
            description="Search for NetBox devices by name pattern",
            is_destructive=False,
        )

        self.register_action(
            name="search_vms",
            func=self._search_vms,
            description="Search for NetBox virtual machines by name pattern",
            is_destructive=False,
        )

        self.register_action(
            name="list_devices",
            func=self._list_devices,
            description="List all NetBox devices with optional filtering",
            is_destructive=False,
        )

        self.register_action(
            name="list_vms",
            func=self._list_vms,
            description="List all NetBox virtual machines with optional filtering",
            is_destructive=False,
        )

        self.register_action(
            name="get_device_by_name",
            func=self._get_device_by_name,
            description="Get a NetBox device by exact name",
            is_destructive=False,
        )

        self.register_action(
            name="get_vm_by_name",
            func=self._get_vm_by_name,
            description="Get a NetBox virtual machine by exact name",
            is_destructive=False,
        )

        logger.info("NetBoxSkill initialized with 8 actions")

    def _get_device(self, device_id: int | str) -> dict[str, Any]:
        """Get detailed device information.

        Args:
            device_id: The NetBox device ID

        Returns:
            Device details including site, role, IPs, and custom fields
        """
        try:
            client = self._get_client()
            device = client.get_device(device_id)

            return {
                "success": True,
                "device": {
                    "id": device.id,
                    "name": device.name,
                    "status": device.status,
                    "status_label": device.status_label,
                    "role": device.role,
                    "tenant": device.tenant,
                    "site": device.site,
                    "location": device.location,
                    "rack": device.rack,
                    "rack_unit": device.rack_unit,
                    "manufacturer": device.manufacturer,
                    "model": device.model,
                    "serial": device.serial,
                    "asset_tag": device.asset_tag,
                    "primary_ip": device.primary_ip,
                    "primary_ip4": device.primary_ip4,
                    "primary_ip6": device.primary_ip6,
                    "oob_ip": device.oob_ip,
                    "cluster": device.cluster,
                    "region": device.region,
                    "site_group": device.site_group,
                    "description": device.description,
                    "tags": list(device.tags),
                    "custom_fields": dict(device.custom_fields) if device.custom_fields else {},
                    "last_updated": device.last_updated.isoformat() if device.last_updated else None,
                },
            }
        except LookupError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            logger.error(f"Failed to get NetBox device {device_id}: {e}")
            return {"success": False, "error": str(e)}

    def _get_vm(self, vm_id: int | str) -> dict[str, Any]:
        """Get detailed VM information.

        Args:
            vm_id: The NetBox VM ID

        Returns:
            VM details including cluster, site, IPs, and custom fields
        """
        try:
            client = self._get_client()
            vm = client.get_vm(vm_id)

            return {
                "success": True,
                "vm": {
                    "id": vm.id,
                    "name": vm.name,
                    "status": vm.status,
                    "status_label": vm.status_label,
                    "role": vm.role,
                    "role_detail": vm.role_detail,
                    "tenant": vm.tenant,
                    "site": vm.site,
                    "cluster": vm.cluster,
                    "platform": vm.platform,
                    "primary_ip": vm.primary_ip,
                    "primary_ip4": vm.primary_ip4,
                    "primary_ip6": vm.primary_ip6,
                    "description": vm.description,
                    "tags": list(vm.tags),
                    "custom_fields": dict(vm.custom_fields) if vm.custom_fields else {},
                    "last_updated": vm.last_updated.isoformat() if vm.last_updated else None,
                },
            }
        except LookupError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            logger.error(f"Failed to get NetBox VM {vm_id}: {e}")
            return {"success": False, "error": str(e)}

    def _search_devices(
        self,
        pattern: str,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Search for devices by name pattern.

        Args:
            pattern: Search pattern (regex supported)
            limit: Maximum number of results (default 50)

        Returns:
            List of matching devices
        """
        try:
            client = self._get_client()
            all_devices = client.list_devices()

            # Filter by pattern (case-insensitive)
            regex = re.compile(pattern, re.IGNORECASE)
            matches = [d for d in all_devices if regex.search(d.name)][:limit]

            return {
                "success": True,
                "count": len(matches),
                "total_devices": len(all_devices),
                "devices": [
                    {
                        "id": d.id,
                        "name": d.name,
                        "status": d.status_label,
                        "role": d.role,
                        "site": d.site,
                        "primary_ip": d.primary_ip,
                    }
                    for d in matches
                ],
            }
        except Exception as e:
            logger.error(f"Failed to search NetBox devices: {e}")
            return {"success": False, "error": str(e)}

    def _search_vms(
        self,
        pattern: str,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Search for VMs by name pattern.

        Args:
            pattern: Search pattern (regex supported)
            limit: Maximum number of results (default 50)

        Returns:
            List of matching VMs
        """
        try:
            client = self._get_client()
            all_vms = client.list_vms()

            # Filter by pattern (case-insensitive)
            regex = re.compile(pattern, re.IGNORECASE)
            matches = [v for v in all_vms if regex.search(v.name)][:limit]

            return {
                "success": True,
                "count": len(matches),
                "total_vms": len(all_vms),
                "vms": [
                    {
                        "id": v.id,
                        "name": v.name,
                        "status": v.status_label,
                        "role": v.role,
                        "cluster": v.cluster,
                        "primary_ip": v.primary_ip,
                    }
                    for v in matches
                ],
            }
        except Exception as e:
            logger.error(f"Failed to search NetBox VMs: {e}")
            return {"success": False, "error": str(e)}

    def _list_devices(
        self,
        site: str | None = None,
        role: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """List all devices with optional filtering.

        Args:
            site: Filter by site name
            role: Filter by role
            status: Filter by status (active, planned, staged, failed, etc.)
            limit: Maximum number of results (default 100)

        Returns:
            List of devices
        """
        try:
            client = self._get_client()
            all_devices = client.list_devices()

            # Apply filters
            devices = list(all_devices)
            if site:
                devices = [d for d in devices if d.site and site.lower() in d.site.lower()]
            if role:
                devices = [d for d in devices if d.role and role.lower() in d.role.lower()]
            if status:
                devices = [d for d in devices if d.status and status.lower() == d.status.lower()]

            devices = devices[:limit]

            return {
                "success": True,
                "count": len(devices),
                "total_devices": len(all_devices),
                "devices": [
                    {
                        "id": d.id,
                        "name": d.name,
                        "status": d.status_label,
                        "role": d.role,
                        "site": d.site,
                        "rack": d.rack,
                        "manufacturer": d.manufacturer,
                        "model": d.model,
                        "primary_ip": d.primary_ip,
                    }
                    for d in devices
                ],
            }
        except Exception as e:
            logger.error(f"Failed to list NetBox devices: {e}")
            return {"success": False, "error": str(e)}

    def _list_vms(
        self,
        cluster: str | None = None,
        site: str | None = None,
        role: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """List all VMs with optional filtering.

        Args:
            cluster: Filter by cluster name
            site: Filter by site name
            role: Filter by role
            status: Filter by status (active, planned, staged, etc.)
            limit: Maximum number of results (default 100)

        Returns:
            List of VMs
        """
        try:
            client = self._get_client()
            all_vms = client.list_vms()

            # Apply filters
            vms = list(all_vms)
            if cluster:
                vms = [v for v in vms if v.cluster and cluster.lower() in v.cluster.lower()]
            if site:
                vms = [v for v in vms if v.site and site.lower() in v.site.lower()]
            if role:
                vms = [v for v in vms if v.role and role.lower() in v.role.lower()]
            if status:
                vms = [v for v in vms if v.status and status.lower() == v.status.lower()]

            vms = vms[:limit]

            return {
                "success": True,
                "count": len(vms),
                "total_vms": len(all_vms),
                "vms": [
                    {
                        "id": v.id,
                        "name": v.name,
                        "status": v.status_label,
                        "role": v.role,
                        "cluster": v.cluster,
                        "platform": v.platform,
                        "primary_ip": v.primary_ip,
                    }
                    for v in vms
                ],
            }
        except Exception as e:
            logger.error(f"Failed to list NetBox VMs: {e}")
            return {"success": False, "error": str(e)}

    def _get_device_by_name(self, name: str) -> dict[str, Any]:
        """Get a device by exact name.

        Args:
            name: Exact device name

        Returns:
            Device details if found
        """
        try:
            client = self._get_client()
            all_devices = client.list_devices()

            # Find exact match (case-insensitive)
            for device in all_devices:
                if device.name.lower() == name.lower():
                    return self._get_device(device.id)

            return {"success": False, "error": f"Device '{name}' not found"}
        except Exception as e:
            logger.error(f"Failed to get NetBox device by name '{name}': {e}")
            return {"success": False, "error": str(e)}

    def _get_vm_by_name(self, name: str) -> dict[str, Any]:
        """Get a VM by exact name.

        Args:
            name: Exact VM name

        Returns:
            VM details if found
        """
        try:
            client = self._get_client()
            all_vms = client.list_vms()

            # Find exact match (case-insensitive)
            for vm in all_vms:
                if vm.name.lower() == name.lower():
                    return self._get_vm(vm.id)

            return {"success": False, "error": f"VM '{name}' not found"}
        except Exception as e:
            logger.error(f"Failed to get NetBox VM by name '{name}': {e}")
            return {"success": False, "error": str(e)}


__all__ = ["NetBoxSkill"]
