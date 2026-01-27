
"""Client for standalone ESXi hosts using pyVmomi."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from types import TracebackType
from typing import Any
from urllib.parse import urlparse

try:
    from pyVim.connect import Disconnect, SmartConnect
    from pyVmomi import vim
except ImportError:  # pragma: no cover - optional dependency
    SmartConnect = None
    Disconnect = None
    vim = None

from .vcenter_client import VCenterClientConfig, VCenterClientError

logger = logging.getLogger(__name__)


class ESXiClient:
    """Client for direct ESXi host connections using pyVmomi (SOAP)."""

    def __init__(self, config: VCenterClientConfig) -> None:
        self._config = config
        self._base_url = config.base_url.rstrip("/")
        # ESXi uses port 443 by default for SOAP
        self._si = None
        self._content = None

        if not config.verify_ssl:
            try:
                import ssl
                _create_unverified_https_context = ssl._create_unverified_context
            except AttributeError:
                pass
            else:
                ssl._create_default_https_context = _create_unverified_https_context

    def __enter__(self) -> ESXiClient:
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def connect(self) -> None:
        """Establish connection to the ESXi host."""
        if self._si is not None:
            return

        if SmartConnect is None:
            raise VCenterClientError("pyVmomi is not installed")

        parsed = urlparse(self._base_url)
        host = parsed.hostname or self._base_url
        port = parsed.port or 443

        try:
            # We already handled global SSL context override in __init__ if needed,
            # but pyvmomi also supports ssl context passed in.
            # For simplicity, we'll rely on the standard connect arguments.
            kwargs = {
                "host": host,
                "user": self._config.username,
                "pwd": self._config.password,
                "port": port,
            }
            if not self._config.verify_ssl:
                kwargs["disableSslCertValidation"] = True
            
            self._si = SmartConnect(**kwargs)
            self._content = self._si.RetrieveContent()
        except Exception as exc:
            raise VCenterClientError(f"Failed to connect to ESXi host: {exc}") from exc

    def close(self) -> None:
        """Disconnect from the ESXi host."""
        if self._si is not None and Disconnect is not None:
            try:
                Disconnect(self._si)
            except Exception:
                logger.debug("Error disconnecting from ESXi", exc_info=True)
        self._si = None
        self._content = None

    def _ensure_connection(self) -> Any:
        if self._si is None:
            self.connect()
        return self._content

    def list_vms(self) -> list[Mapping[str, Any]]:
        """List all VMs on the host."""
        content = self._ensure_connection()
        if not content:
            return []

        vms: list[Mapping[str, Any]] = []

        try:
            container = content.rootFolder
            view_type = [vim.VirtualMachine]
            recursive = True
            container_view = content.viewManager.CreateContainerView(container, view_type, recursive)
            
            for vm in container_view.view:
                try:
                    vms.append(self._extract_vm_summary(vm))
                except Exception:
                    logger.debug("Failed to extract summary for VM %s", vm, exc_info=True)
                    continue
            
            container_view.Destroy()
        except Exception as exc:
            logger.error("Failed to list VMs from ESXi: %s", exc)
            return []

        return vms

    def get_vm(self, vm_id: str) -> Mapping[str, Any] | None:
        """Get details for a specific VM."""
        content = self._ensure_connection()
        if not content or not vm_id:
            return None

        # vm_id in our case will likely be the moid (e.g. '1', '2')
        # We can try to find by ID
        try:
            # Note: FindByInventoryPath is not efficient for IDs. 
            # We'll traverse. On standalone ESXi, there aren't that many VMs usually.
            # But searchIndex is better.
            search_index = content.searchIndex
            # This is tricky because list_vms returns 'vm' as the ID (moid).
            # ESXi MOIDs are usually simple integers.
            # Let's try to find by UUID if it looks like a uuid, or iterate if not.
            # But the 'vm_id' we store is the moid from summary.
            
            # Simple iteration for now for safety on standalone host
            container = content.rootFolder
            view_type = [vim.VirtualMachine]
            container_view = content.viewManager.CreateContainerView(container, view_type, True)
            
            found_vm = None
            for vm in container_view.view:
                if str(vm._moId) == vm_id:
                    found_vm = vm
                    break
            container_view.Destroy()

            if found_vm:
                return self._extract_vm_detail(found_vm)
            
        except Exception as exc:
            logger.debug("Error finding VM %s: %s", vm_id, exc)
        
        return None

    def _extract_vm_summary(self, vm: Any) -> dict[str, Any]:
        """Extract summary information similar to vCenter REST API list response."""
        summary = vm.summary
        config = summary.config
        guest = summary.guest
        runtime = summary.runtime
        
        return {
            "vm": str(vm._moId),
            "name": config.name,
            "power_state": str(runtime.powerState),  # poweredOn, poweredOff, suspended
            "cpu_count": config.numCpu,
            "memory_size_MiB": config.memorySizeMB,
            "guest_OS": config.guestFullName,  # This might be 'Ubuntu Linux (64-bit)'
            "connection_state": str(runtime.connectionState),
        }

    def _extract_vm_detail(self, vm: Any) -> dict[str, Any]:
        """Extract detailed information similar to vCenter REST API get response."""
        summary = vm.summary
        config = vm.config
        guest = vm.guest
        
        # Tools status
        tools_status = "UNKNOWN"
        if guest.toolsStatus:
            tools_status = str(guest.toolsStatus) # toolsNotInstalled, toolsOk, etc.

        # Network interfaces
        nics = []
        for device in config.hardware.device:
            if isinstance(device, vim.vm.device.VirtualEthernetCard):
                nics.append({
                    "value": {
                        "label": device.deviceInfo.label,
                        "mac_address": device.macAddress,
                        "backing": {
                            "network_name": device.backing.deviceName if hasattr(device.backing, "deviceName") else ""
                        }
                    }
                })

        # Identity
        identity = {
            "name": config.name,
            "instance_uuid": config.instanceUuid,
            "bios_uuid": config.uuid,
            "guest_os": config.guestFullName,
            "ip_address": guest.ipAddress,
            "host_name": guest.hostName,
            "family": guest.guestFamily,
            "full_name": guest.guestFullName,
        }

        return {
            "vm": str(vm._moId),
            "name": config.name,
            "power_state": str(summary.runtime.powerState),
            "cpu": {"count": config.hardware.numCPU},
            "memory": {"size_MiB": config.hardware.memoryMB},
            "guest_OS": config.guestFullName,
            "identity": identity,
            "nics": nics,
            "tools": {"status": tools_status},
        }

    def get_vm_guest_interfaces(self, vm_id: str) -> list[Mapping[str, Any]]:
        # PyVmomi guest info usually has IP stack
        content = self._ensure_connection()
        if not content or not vm_id:
            return []
            
        # Simplified: Use list_vms approach to find VM then extract guest net info
        # For full parity we need more complex logic, but for "Add simple ESXi", 
        # listing IPs from guest info in _extract_vm_detail might be enough?
        # The service calls this separate method though.
        
        # Let's try to lookup VM again
        vm_obj = self._find_vm_by_id(content, vm_id)
        if not vm_obj:
            return []
            
        interfaces = []
        if vm_obj.guest and vm_obj.guest.net:
            for net in vm_obj.guest.net:
                ips = []
                if net.ipConfig and net.ipConfig.ipAddress:
                    for ip in net.ipConfig.ipAddress:
                        ips.append(ip.ipAddress)
                
                interfaces.append({
                    "mac_address": net.macAddress,
                    "ip": {"ip_addresses": [{"ip_address": ip} for ip in ips]}
                })
        return interfaces

    def get_vm_disks(self, vm_id: str) -> list[Mapping[str, Any]]:
        content = self._ensure_connection()
        if not content or not vm_id:
            return []
        
        # We can reuse the same logic as VCenterClient.get_vm_disks_vim 
        # IF we can pass the uuid. But here we have ID (moid).
        # We can resolve ID to UUID or just implement the disk logic here for the object.
        vm_obj = self._find_vm_by_id(content, vm_id)
        if not vm_obj:
            return []
            
        disks = []
        # Reuse logic logic from VCenterClient would be ideal but it's bound to methods.
        # I'll implement a simplified version here.
        
        for device in vm_obj.config.hardware.device:
            if isinstance(device, vim.vm.device.VirtualDisk):
                disk_data = {
                    "label": device.deviceInfo.label,
                    "capacity_bytes": device.capacityInBytes,
                    "summary": device.deviceInfo.summary
                }
                if device.backing:
                    disk_data["disk_path"] = device.backing.fileName
                    if hasattr(device.backing, "thinProvisioned"):
                        disk_data["thin_provisioned"] = device.backing.thinProvisioned
                
                disks.append(disk_data)
        
        return disks

    def _find_vm_by_id(self, content, moid):
        container = content.rootFolder
        view_type = [vim.VirtualMachine]
        container_view = content.viewManager.CreateContainerView(container, view_type, True)
        for vm in container_view.view:
            if str(vm._moId) == moid:
                container_view.Destroy()
                return vm
        container_view.Destroy()
        return None

    def get_vm_snapshots(self, vm_id: str) -> list[Mapping[str, Any]]:
        # ESXi supports snapshots
        content = self._ensure_connection()
        vm_obj = self._find_vm_by_id(content, vm_id)
        if not vm_obj or not vm_obj.snapshot:
            return []
            
        # Recursive snapshot collector
        snapshots = []
        def collect_snaps(tree_nodes):
            for node in tree_nodes:
                snap = {
                    "id": str(node.id),
                    "name": node.name,
                    "description": node.description,
                    "create_time": node.createTime.isoformat() if node.createTime else None,
                    "state": str(node.state)
                }
                snapshots.append(snap)
                if node.childSnapshotList:
                    collect_snaps(node.childSnapshotList)
        
        if vm_obj.snapshot.rootSnapshotList:
            collect_snaps(vm_obj.snapshot.rootSnapshotList)
            
        return snapshots

