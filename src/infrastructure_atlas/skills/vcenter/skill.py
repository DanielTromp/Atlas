"""vCenter skill implementation for agent workflows.

Provides virtualization actions:
- Get VM details and status
- Search for VMs
- List all VMs with filtering
"""

from __future__ import annotations

import re
from typing import Any

from infrastructure_atlas.application.services.vcenter import VCenterService
from infrastructure_atlas.db import get_sessionmaker
from infrastructure_atlas.infrastructure.logging import get_logger
from infrastructure_atlas.skills.base import BaseSkill

logger = get_logger(__name__)


class VCenterSkill(BaseSkill):
    """Skill for interacting with vCenter virtualization platform.

    Provides actions for:
    - Getting VM details and power state
    - Searching for VMs by name
    - Listing all VMs from configured vCenters
    """

    name = "vcenter"
    description = "Interact with vCenter for virtual machine management and status"
    category = "virtualization"

    def __init__(self) -> None:
        super().__init__()
        self._service: VCenterService | None = None

    def _get_service(self) -> VCenterService:
        """Get or create vCenter service lazily."""
        if self._service is None:
            Sessionmaker = get_sessionmaker()
            session = Sessionmaker()
            self._service = VCenterService(session)
        return self._service

    def initialize(self) -> None:
        """Register all vCenter actions."""
        self.register_action(
            name="get_vm",
            func=self._get_vm,
            description="Get detailed information about a VM by name",
            is_destructive=False,
        )

        self.register_action(
            name="search_vms",
            func=self._search_vms,
            description="Search for VMs by name pattern across all vCenters",
            is_destructive=False,
        )

        self.register_action(
            name="list_vms",
            func=self._list_vms,
            description="List all VMs from a specific vCenter configuration",
            is_destructive=False,
        )

        self.register_action(
            name="list_vcenter_configs",
            func=self._list_configs,
            description="List all configured vCenter connections",
            is_destructive=False,
        )

        self.register_action(
            name="get_vm_by_ip",
            func=self._get_vm_by_ip,
            description="Find a VM by its IP address",
            is_destructive=False,
        )

        self.register_action(
            name="get_vm_power_state",
            func=self._get_vm_power_state,
            description="Get the power state of a VM by name",
            is_destructive=False,
        )

        logger.info("VCenterSkill initialized with 6 actions")

    def _get_vm(self, vm_name: str, config_id: str | None = None) -> dict[str, Any]:
        """Get detailed VM information by name.

        Args:
            vm_name: The VM name to search for
            config_id: Optional vCenter config ID to limit search

        Returns:
            VM details if found
        """
        try:
            service = self._get_service()
            configs = service.list_configs()

            if config_id:
                configs = [c for c in configs if c.id == config_id]

            for config in configs:
                try:
                    _, vms, _ = service.get_inventory(config.id)
                    for vm in vms:
                        if vm.name.lower() == vm_name.lower():
                            return {
                                "success": True,
                                "vm": self._vm_to_dict(vm, config.name),
                            }
                except Exception as e:
                    logger.warning(f"Error getting inventory from {config.name}: {e}")
                    continue

            return {"success": False, "error": f"VM '{vm_name}' not found"}
        except Exception as e:
            logger.error(f"Failed to get VM '{vm_name}': {e}")
            return {"success": False, "error": str(e)}

    def _search_vms(
        self,
        pattern: str,
        config_id: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Search for VMs by name pattern.

        Args:
            pattern: Search pattern (regex supported)
            config_id: Optional vCenter config ID to limit search
            limit: Maximum number of results (default 50)

        Returns:
            List of matching VMs
        """
        try:
            service = self._get_service()
            configs = service.list_configs()

            if config_id:
                configs = [c for c in configs if c.id == config_id]

            matches = []
            regex = re.compile(pattern, re.IGNORECASE)

            for config in configs:
                try:
                    _, vms, _ = service.get_inventory(config.id)
                    for vm in vms:
                        if regex.search(vm.name):
                            matches.append(self._vm_summary(vm, config.name))
                            if len(matches) >= limit:
                                break
                except Exception as e:
                    logger.warning(f"Error searching inventory from {config.name}: {e}")
                    continue
                if len(matches) >= limit:
                    break

            return {
                "success": True,
                "count": len(matches),
                "vms": matches[:limit],
            }
        except Exception as e:
            logger.error(f"Failed to search VMs: {e}")
            return {"success": False, "error": str(e)}

    def _list_vms(
        self,
        config_id: str,
        power_state: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """List all VMs from a vCenter configuration.

        Args:
            config_id: The vCenter configuration ID
            power_state: Optional filter by power state (POWERED_ON, POWERED_OFF, SUSPENDED)
            limit: Maximum number of results (default 100)

        Returns:
            List of VMs
        """
        try:
            service = self._get_service()
            config, vms, meta = service.get_inventory(config_id)

            # Apply power state filter
            if power_state:
                vms = [v for v in vms if v.power_state and v.power_state.upper() == power_state.upper()]

            return {
                "success": True,
                "vcenter": config.name,
                "total_vms": len(vms),
                "source": meta.get("source", "unknown"),
                "cached_at": meta.get("refreshed_at"),
                "vms": [self._vm_summary(v, config.name) for v in vms[:limit]],
            }
        except Exception as e:
            logger.error(f"Failed to list VMs from {config_id}: {e}")
            return {"success": False, "error": str(e)}

    def _list_configs(self) -> dict[str, Any]:
        """List all configured vCenter connections.

        Returns:
            List of vCenter configurations
        """
        try:
            service = self._get_service()
            configs = service.list_configs()

            return {
                "success": True,
                "count": len(configs),
                "vcenters": [
                    {
                        "id": c.id,
                        "name": c.name,
                        "base_url": c.base_url,
                        "is_active": c.is_active,
                        "is_esxi": c.is_esxi,
                    }
                    for c in configs
                ],
            }
        except Exception as e:
            logger.error(f"Failed to list vCenter configs: {e}")
            return {"success": False, "error": str(e)}

    def _get_vm_by_ip(
        self,
        ip_address: str,
        config_id: str | None = None,
    ) -> dict[str, Any]:
        """Find a VM by its IP address.

        Args:
            ip_address: The IP address to search for
            config_id: Optional vCenter config ID to limit search

        Returns:
            VM details if found
        """
        try:
            service = self._get_service()
            configs = service.list_configs()

            if config_id:
                configs = [c for c in configs if c.id == config_id]

            for config in configs:
                try:
                    _, vms, _ = service.get_inventory(config.id)
                    for vm in vms:
                        if vm.ip_addresses and ip_address in vm.ip_addresses:
                            return {
                                "success": True,
                                "vm": self._vm_to_dict(vm, config.name),
                            }
                except Exception as e:
                    logger.warning(f"Error searching inventory from {config.name}: {e}")
                    continue

            return {"success": False, "error": f"VM with IP '{ip_address}' not found"}
        except Exception as e:
            logger.error(f"Failed to find VM by IP '{ip_address}': {e}")
            return {"success": False, "error": str(e)}

    def _get_vm_power_state(
        self,
        vm_name: str,
        config_id: str | None = None,
    ) -> dict[str, Any]:
        """Get the power state of a VM.

        Args:
            vm_name: The VM name
            config_id: Optional vCenter config ID to limit search

        Returns:
            Power state information
        """
        try:
            result = self._get_vm(vm_name, config_id)
            if not result.get("success"):
                return result

            vm = result.get("vm", {})
            return {
                "success": True,
                "vm_name": vm.get("name"),
                "power_state": vm.get("power_state"),
                "vcenter": vm.get("vcenter"),
                "tools_status": vm.get("tools_status"),
            }
        except Exception as e:
            logger.error(f"Failed to get power state for '{vm_name}': {e}")
            return {"success": False, "error": str(e)}

    def _vm_to_dict(self, vm, vcenter_name: str) -> dict[str, Any]:
        """Convert a VCenterVM to a detailed dict."""
        return {
            "vm_id": vm.vm_id,
            "name": vm.name,
            "power_state": vm.power_state,
            "guest_os": vm.guest_os,
            "cpu_count": vm.cpu_count,
            "memory_mib": vm.memory_mib,
            "tools_status": vm.tools_status,
            "hardware_version": vm.hardware_version,
            "is_template": vm.is_template,
            "instance_uuid": vm.instance_uuid,
            "bios_uuid": vm.bios_uuid,
            "ip_addresses": list(vm.ip_addresses) if vm.ip_addresses else [],
            "mac_addresses": list(vm.mac_addresses) if vm.mac_addresses else [],
            "datacenter": vm.datacenter,
            "cluster": vm.cluster,
            "host": vm.host,
            "resource_pool": vm.resource_pool,
            "folder": vm.folder,
            "vcenter": vcenter_name,
            "vm_link": vm.vm_link,
            "tags": list(vm.tags) if vm.tags else [],
            "custom_attributes": dict(vm.custom_attributes) if vm.custom_attributes else {},
            "disks": [
                {
                    "label": d.get("label"),
                    "capacity_gb": d.get("capacity_gb"),
                    "thin_provisioned": d.get("thin_provisioned"),
                }
                for d in (vm.disks or [])
            ],
            "snapshots": [
                {
                    "name": s.get("name"),
                    "created_at": s.get("created_at"),
                    "size_bytes": s.get("size_bytes"),
                }
                for s in (vm.snapshots or [])
            ],
        }

    def _vm_summary(self, vm, vcenter_name: str) -> dict[str, Any]:
        """Convert a VCenterVM to a summary dict."""
        return {
            "name": vm.name,
            "power_state": vm.power_state,
            "guest_os": vm.guest_os,
            "cpu_count": vm.cpu_count,
            "memory_mib": vm.memory_mib,
            "ip_addresses": list(vm.ip_addresses)[:3] if vm.ip_addresses else [],
            "datacenter": vm.datacenter,
            "cluster": vm.cluster,
            "vcenter": vcenter_name,
        }


__all__ = ["VCenterSkill"]
