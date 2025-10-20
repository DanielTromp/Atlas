"""Lightweight client for VMware vCenter REST APIs."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import TracebackType
from typing import Any
from urllib.parse import urlparse

import requests
from requests import Session

try:
    from pyVim.connect import Disconnect, SmartConnect
    from pyVmomi import vim
except ImportError:  # pragma: no cover - optional dependency
    SmartConnect = None
    Disconnect = None
    vim = None

logger = logging.getLogger(__name__)


class VCenterClientError(RuntimeError):
    """Base error raised for vCenter client failures."""


class VCenterAuthError(VCenterClientError):
    """Raised when authentication against vCenter fails."""


class VCenterAPIError(VCenterClientError):
    """Raised when vCenter returns an unexpected response."""


@dataclass(slots=True)
class VCenterClientConfig:
    """Connection parameters for the vCenter API client."""

    base_url: str
    username: str
    password: str
    verify_ssl: bool = True
    timeout: int = 30


class VCenterClient:
    """Minimal REST wrapper for the vCenter inventory endpoints."""

    _SESSION_ENDPOINT = "/rest/com/vmware/cis/session"
    _VM_LIST_ENDPOINT = "/rest/vcenter/vm"
    _VM_PLACEMENT_ENDPOINT = "/rest/vcenter/vm/{vm}/placement"
    _VM_GUEST_INTERFACES_ENDPOINT = "/rest/vcenter/vm/{vm}/guest/networking/interfaces"
    _DATACENTER_LIST_ENDPOINT = "/rest/vcenter/datacenter"
    _CLUSTER_LIST_ENDPOINT = "/rest/vcenter/cluster"
    _HOST_LIST_ENDPOINT = "/rest/vcenter/host"
    _RESOURCE_POOL_LIST_ENDPOINT = "/rest/vcenter/resource-pool"
    _FOLDER_LIST_ENDPOINT = "/rest/vcenter/folder"
    _VM_CUSTOM_ATTRIBUTES_ENDPOINT = "/rest/vcenter/vm/{vm}/custom-attributes"
    _VM_GUEST_IDENTITY_ENDPOINT = "/rest/vcenter/vm/{vm}/guest/identity"
    _VM_TOOLS_ENDPOINT = "/rest/vcenter/vm/{vm}/tools"
    _VM_SNAPSHOTS_ENDPOINT = "/rest/vcenter/vm/{vm}/snapshot"
    _VM_DISKS_ENDPOINT = "/rest/vcenter/vm/{vm}/hardware/disk"
    _TAG_LIST_ENDPOINT = "/rest/com/vmware/cis/tagging/tag-association?~action=list-attached-tags"
    _TAG_INFO_ENDPOINT = "/rest/com/vmware/cis/tagging/tag/id:{tag_id}"

    def __init__(self, config: VCenterClientConfig) -> None:
        self._config = config
        self._base_url = config.base_url.rstrip("/")
        self._timeout = max(int(config.timeout or 30), 1)
        self._session: Session = requests.Session()
        self._session.verify = bool(config.verify_ssl)
        self._session.headers.update({"Accept": "application/json"})
        self._authenticated = False
        self._token: str | None = None
        self._tag_cache: dict[str, str] = {}
        self._server_guid: str | None = None
        self._vim = None
        self._vim_content = None
        if not config.verify_ssl:
            try:  # optional dependency
                from urllib3 import disable_warnings
                from urllib3.exceptions import InsecureRequestWarning

                disable_warnings(InsecureRequestWarning)
            except Exception:  # pragma: no cover - urllib3 optional
                logger.debug("Unable to disable urllib3 warnings", exc_info=True)

    def __enter__(self) -> VCenterClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._session.close()
        if self._vim is not None and Disconnect is not None:  # pragma: no cover - network dependent
            try:
                Disconnect(self._vim)
            except Exception:  # pragma: no cover - best effort cleanup
                logger.debug("Failed to disconnect pyVmomi session", exc_info=True)
        self._vim = None
        self._vim_content = None

    # Authentication -----------------------------------------------------------------
    def _login(self) -> None:
        url = f"{self._base_url}{self._SESSION_ENDPOINT}"
        try:
            response = self._session.post(
                url,
                auth=(self._config.username, self._config.password),
                timeout=self._timeout,
            )
        except requests.RequestException as exc:  # pragma: no cover - network error
            raise VCenterClientError("Failed to connect to vCenter session endpoint") from exc

        if response.status_code in (401, 403):
            raise VCenterAuthError("vCenter rejected the supplied credentials")

        if response.status_code not in (200, 201):
            raise VCenterClientError(
                f"Unexpected status {response.status_code} while establishing vCenter session",
            )

        token: str | None = None
        if response.content:
            try:
                data = response.json()
            except ValueError:
                data = {}
            token = data.get("value") if isinstance(data, Mapping) else None
        if not token:
            token = response.headers.get("vmware-api-session-id")
        if not token:
            raise VCenterClientError("vCenter session response did not include a session token")

        self._token = token
        self._session.headers["vmware-api-session-id"] = token
        self._authenticated = True

    def _ensure_session(self) -> None:
        if not self._authenticated:
            self._login()

    # Low-level HTTP helpers ---------------------------------------------------------
    def _request(
        self,
        method: str,
        path: str,
        *,
        ok_status: Sequence[int] | None = None,
        null_status: Sequence[int] | None = None,
        **kwargs: Any,
    ) -> Any:
        self._ensure_session()
        url = f"{self._base_url}{path}"
        ok_codes = tuple(ok_status or (200,))
        null_codes = tuple(null_status or ())
        try:
            response = self._session.request(method, url, timeout=self._timeout, **kwargs)
        except requests.RequestException as exc:  # pragma: no cover - network error
            raise VCenterClientError(f"Error communicating with vCenter: {exc}") from exc

        if response.status_code in (401, 403):
            self._authenticated = False
            raise VCenterAuthError("vCenter session expired or credentials invalid")

        if response.status_code in null_codes:
            return None

        if response.status_code not in ok_codes:
            message = self._extract_error_message(response)
            raise VCenterAPIError(
                f"vCenter returned status {response.status_code}: {message}",
            )

        if not response.content:
            return None

        try:
            return response.json()
        except ValueError:
            return None

    @staticmethod
    def _extract_error_message(response: requests.Response) -> str:
        if not response.content:
            return "no response body"
        try:
            payload = response.json()
        except ValueError:
            return response.text.strip()
        detail = payload.get("value") if isinstance(payload, Mapping) else None
        if isinstance(detail, Mapping):
            message = detail.get("messages") or detail.get("message")
            if isinstance(message, str):
                return message
            if isinstance(message, Sequence):
                parts = [str(item) for item in message]
                if parts:
                    return "; ".join(parts)
        return response.text.strip() or "unknown error"

    # Public API ---------------------------------------------------------------------
    def list_vms(self) -> list[Mapping[str, Any]]:
        payload = self._request("GET", self._VM_LIST_ENDPOINT)
        if not isinstance(payload, Mapping):
            return []
        values = payload.get("value")
        if isinstance(values, list):
            return [item for item in values if isinstance(item, Mapping)]
        return []

    def get_vm(self, vm_id: str) -> Mapping[str, Any] | None:
        if not vm_id:
            return None
        payload = self._request(
            "GET",
            f"{self._VM_LIST_ENDPOINT}/{vm_id}",
            null_status=(404,),
        )
        if not isinstance(payload, Mapping):
            return None
        value = payload.get("value")
        return value if isinstance(value, Mapping) else None

    def get_vm_placement(self, vm_id: str) -> Mapping[str, Any] | None:
        if not vm_id:
            return None
        payload = self._request(
            "GET",
            self._VM_PLACEMENT_ENDPOINT.format(vm=vm_id),
            null_status=(401, 403, 404, 500, 501, 503),
        )
        if not isinstance(payload, Mapping):
            return None
        placement = payload.get("value")
        return placement if isinstance(placement, Mapping) else None

    # ------------------------------------------------------------------
    # vSphere (pyVmomi) helpers
    # ------------------------------------------------------------------

    def _ensure_vim_connection(self):  # pragma: no cover - network dependent
        if self._vim_content is not None:
            return self._vim_content
        if SmartConnect is None:
            logger.debug("pyVmomi is not available; placement resolution disabled")
            return None
        parsed = urlparse(self._base_url)
        host = parsed.hostname or self._base_url
        port = parsed.port or 443
        kwargs = {
            "host": host,
            "user": self._config.username,
            "pwd": self._config.password,
            "port": port,
        }
        if not self._config.verify_ssl:
            kwargs["disableSslCertValidation"] = True
        try:
            self._vim = SmartConnect(**kwargs)
            self._vim_content = self._vim.RetrieveContent()
        except Exception as exc:
            logger.debug("Failed to establish pyVmomi connection", exc_info=True)
            self._vim = None
            self._vim_content = None
            raise VCenterClientError(f"Failed to connect to vCenter via pyVmomi: {exc}") from exc
        return self._vim_content

    def get_vm_placement_vim(self, instance_uuid: str) -> dict[str, str]:  # pragma: no cover - network dependent
        placement: dict[str, str] = {}
        if not instance_uuid:
            return placement
        try:
            content = self._ensure_vim_connection()
        except VCenterClientError:
            return placement
        if content is None or vim is None:
            return placement
        try:
            search_index = getattr(content, "searchIndex", None)
            if search_index is None:
                return placement
            vm = search_index.FindByUuid(None, instance_uuid, True, True)
            if vm is None:
                return placement

            def safe_name(obj):
                return getattr(obj, "name", None) if obj else None

            def find_datacenter(entity):
                current = entity
                while current is not None:
                    if isinstance(current, vim.Datacenter):
                        return current
                    current = getattr(current, "parent", None)
                return None

            def find_vm_folder(entity):
                current = getattr(entity, "parent", None)
                while current is not None:
                    if isinstance(current, vim.Folder):
                        return current
                    current = getattr(current, "parent", None)
                return None

            host_obj = getattr(getattr(vm, "runtime", None), "host", None)
            cluster_obj = getattr(host_obj, "parent", None)
            resource_pool_obj = getattr(vm, "resourcePool", None)
            folder_obj = find_vm_folder(vm)
            datacenter_obj = find_datacenter(vm)

            host_name = safe_name(host_obj)
            if host_name:
                placement["host"] = host_name
            if isinstance(cluster_obj, vim.ClusterComputeResource | vim.ComputeResource):
                cluster_name = safe_name(cluster_obj)
                if cluster_name:
                    placement["cluster"] = cluster_name
            datacenter_name = safe_name(datacenter_obj)
            if datacenter_name:
                placement["datacenter"] = datacenter_name
            resource_pool_name = safe_name(resource_pool_obj)
            if resource_pool_name:
                placement["resource_pool"] = resource_pool_name
            folder_name = safe_name(folder_obj)
            if folder_name:
                placement["folder"] = folder_name
        except Exception:  # pragma: no cover - best effort
            logger.debug("Failed to resolve placement via pyVmomi", exc_info=True)
        return placement

    def get_vm_guest_interfaces(self, vm_id: str) -> list[Mapping[str, Any]]:
        if not vm_id:
            return []
        payload = self._request(
            "GET",
            self._VM_GUEST_INTERFACES_ENDPOINT.format(vm=vm_id),
            null_status=(401, 403, 404, 500, 501, 503),
        )
        if not isinstance(payload, Mapping):
            return []
        value = payload.get("value")
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
        return []

    def list_vm_custom_attributes(self, vm_id: str) -> dict[str, str]:
        if not vm_id:
            return {}
        payload = self._request(
            "GET",
            self._VM_CUSTOM_ATTRIBUTES_ENDPOINT.format(vm=vm_id),
            null_status=(404, 500, 501, 503),
        )
        if not isinstance(payload, Mapping):
            return {}
        values = payload.get("value")
        if not isinstance(values, list):
            return {}
        result: dict[str, str] = {}
        for item in values:
            if not isinstance(item, Mapping):
                continue
            key = item.get("name") or item.get("key")
            value = item.get("value")
            if isinstance(key, str) and key.strip():
                result[key.strip()] = str(value).strip() if value is not None else ""
        return result

    def get_vm_guest_identity(self, vm_id: str) -> Mapping[str, Any] | None:
        if not vm_id:
            return None
        payload = self._request(
            "GET",
            self._VM_GUEST_IDENTITY_ENDPOINT.format(vm=vm_id),
            null_status=(401, 403, 404, 500, 501, 503),
        )
        if not isinstance(payload, Mapping):
            return None
        identity = payload.get("value")
        return identity if isinstance(identity, Mapping) else None

    def get_vm_tools(self, vm_id: str) -> Mapping[str, Any] | None:
        if not vm_id:
            return None
        payload = self._request(
            "GET",
            self._VM_TOOLS_ENDPOINT.format(vm=vm_id),
            null_status=(401, 403, 404, 500, 501, 503),
        )
        if not isinstance(payload, Mapping):
            return None
        tools = payload.get("value")
        return tools if isinstance(tools, Mapping) else None

    def get_vm_snapshots(self, vm_id: str) -> list[Mapping[str, Any]]:
        if not vm_id:
            return []
        # Try REST API first
        payload = self._request(
            "GET",
            self._VM_SNAPSHOTS_ENDPOINT.format(vm=vm_id),
            null_status=(401, 403, 404, 500, 501, 503),
        )
        if isinstance(payload, Mapping):
            snapshots = payload.get("value")
            if isinstance(snapshots, list):
                return [item for item in snapshots if isinstance(item, Mapping)]
        return []

    def get_vm_snapshots_vim(self, instance_uuid: str) -> list[Mapping[str, Any]]:  # pragma: no cover - network dependent
        """Get VM snapshots using pyVmomi (SOAP API)."""
        snapshots: list[Mapping[str, Any]] = []
        if not instance_uuid:
            return snapshots
        try:
            content = self._ensure_vim_connection()
        except VCenterClientError as exc:
            logger.debug("Failed to connect to vCenter for snapshot retrieval", exc_info=exc)
            return snapshots
        if content is None or vim is None:
            return snapshots
        try:
            search_index = getattr(content, "searchIndex", None)
            if search_index is None:
                return snapshots
            vm = search_index.FindByUuid(None, instance_uuid, True, True)
            snapshot_info = getattr(vm, "snapshot", None) if vm else None
            if vm is None or snapshot_info is None:
                return snapshots

            # Get layout information for snapshot delta disk sizes
            # Delta disks (-000001.vmdk, -000002.vmdk, etc.) contain the actual data changes
            layout_ex = getattr(vm, "layoutEx", None)
            snapshot_sizes: dict[str, int] = {}

            # First, collect all snapshot IDs to map deltas to
            snapshot_list = []
            if snapshot_info:
                root_snapshots = getattr(snapshot_info, "rootSnapshotList", None)
                if root_snapshots:
                    def collect_snapshot_ids(snap_tree):
                        ids = []
                        if not isinstance(snap_tree, list):
                            snap_tree = [snap_tree]
                        for snap_node in snap_tree:
                            snap = getattr(snap_node, "snapshot", None)
                            if snap:
                                snap_id = getattr(snap, "_moId", None)
                                if snap_id:
                                    ids.append(snap_id)
                            children = getattr(snap_node, "childSnapshotList", None)
                            if children:
                                ids.extend(collect_snapshot_ids(children))
                        return ids
                    snapshot_list = collect_snapshot_ids(root_snapshots)

            if layout_ex:
                all_files = getattr(layout_ex, "file", None)

                if all_files:
                    # Scan all files for delta disks
                    # Delta disks have naming pattern: vmname-000001.vmdk, vmname-000002.vmdk, etc.
                    total_delta_size = 0
                    for file_info in all_files:
                        name = getattr(file_info, "name", "")
                        size = getattr(file_info, "size", 0)

                        # Look for delta disk files (contain -0000 and .vmdk)
                        if size and "-0000" in name and ".vmdk" in name:
                            total_delta_size += int(size)

                    # Assign the total delta size to the first/only snapshot
                    # For multiple snapshots, this sums all deltas (a known limitation)
                    if total_delta_size > 0 and snapshot_list:
                        snapshot_sizes[snapshot_list[0]] = total_delta_size

            def process_snapshot_tree(snapshot_tree):
                """Recursively process snapshot tree."""
                result = []
                if not isinstance(snapshot_tree, list):
                    snapshot_tree = [snapshot_tree]

                for snap_node in snapshot_tree:
                    snap = getattr(snap_node, "snapshot", None)
                    if snap is None:
                        continue

                    snap_data: dict[str, Any] = {}

                    # Get snapshot ID
                    snap_id = getattr(snap, "_moId", None)
                    if snap_id:
                        snap_data["id"] = snap_id

                    # Get snapshot name
                    name = getattr(snap_node, "name", None)
                    if name:
                        snap_data["name"] = str(name)

                    # Get description
                    description = getattr(snap_node, "description", None)
                    if description:
                        snap_data["description"] = str(description)

                    # Get creation time
                    create_time = getattr(snap_node, "createTime", None)
                    if create_time:
                        snap_data["create_time"] = create_time.isoformat() if hasattr(create_time, "isoformat") else str(create_time)

                    # Get state
                    state = getattr(snap_node, "state", None)
                    if state:
                        snap_data["state"] = str(state)

                    # Get quiesced flag
                    quiesced = getattr(snap_node, "quiesced", None)
                    if quiesced is not None:
                        snap_data["quiesced"] = bool(quiesced)

                    # Get snapshot size from layout information
                    if snap_id and snap_id in snapshot_sizes:
                        snap_data["size_bytes"] = snapshot_sizes[snap_id]

                    result.append(snap_data)

                    # Process child snapshots recursively
                    child_snapshots = getattr(snap_node, "childSnapshotList", None)
                    if child_snapshots:
                        result.extend(process_snapshot_tree(child_snapshots))

                return result

            root_snapshots = getattr(snapshot_info, "rootSnapshotList", None)
            if root_snapshots:
                snapshots = process_snapshot_tree(root_snapshots)
        except Exception as exc:  # pragma: no cover - best effort
            logger.debug("Failed to retrieve snapshots via pyVmomi", exc_info=exc)

        return snapshots

    def get_vm_disks(self, vm_id: str) -> list[Mapping[str, Any]]:
        """Get VM disk information using REST API."""
        if not vm_id:
            return []
        payload = self._request(
            "GET",
            self._VM_DISKS_ENDPOINT.format(vm=vm_id),
            null_status=(401, 403, 404, 500, 501, 503),
        )
        if isinstance(payload, Mapping):
            disks = payload.get("value")
            if isinstance(disks, list):
                return [item for item in disks if isinstance(item, Mapping)]
        return []

    def get_vm_disks_vim(self, instance_uuid: str) -> list[Mapping[str, Any]]:  # pragma: no cover - network dependent
        """Get VM disk information using pyVmomi (SOAP API)."""
        disks: list[Mapping[str, Any]] = []
        if not instance_uuid:
            return disks
        try:
            content = self._ensure_vim_connection()
        except VCenterClientError as exc:
            logger.debug("Failed to connect to vCenter for disk retrieval", exc_info=exc)
            return disks
        if content is None or vim is None:
            return disks
        try:
            search_index = getattr(content, "searchIndex", None)
            if search_index is None:
                return disks
            vm = search_index.FindByUuid(None, instance_uuid, True, True)
            config = getattr(vm, "config", None) if vm else None
            hardware = getattr(config, "hardware", None) if config else None
            devices = getattr(hardware, "device", None) if hardware else None
            if vm is None or config is None or hardware is None or not devices:
                return disks

            # Get storage info for thin provisioning details
            storage = getattr(vm, "storage", None)
            per_datastore_usage = {}
            if storage:
                per_ds_usage = getattr(storage, "perDatastoreUsage", None)
                if per_ds_usage:
                    for usage in per_ds_usage:
                        datastore = getattr(usage, "datastore", None)
                        if datastore:
                            ds_name = getattr(datastore, "name", None)
                            committed = getattr(usage, "committed", None)
                            uncommitted = getattr(usage, "uncommitted", None)
                            if ds_name:
                                per_datastore_usage[ds_name] = {
                                    "committed": committed,
                                    "uncommitted": uncommitted,
                                }

            # Process disk devices
            for device in devices:
                # Check if this is a disk device
                if not isinstance(device, vim.vm.device.VirtualDisk):
                    continue

                disk_data: dict[str, Any] = {}

                # Get device info
                device_info = getattr(device, "deviceInfo", None)
                if device_info:
                    label = getattr(device_info, "label", None)
                    if label:
                        disk_data["label"] = str(label)
                    summary = getattr(device_info, "summary", None)
                    if summary:
                        disk_data["summary"] = str(summary)

                # Get capacity
                capacity = getattr(device, "capacityInBytes", None)
                if capacity is not None:
                    disk_data["capacity_bytes"] = int(capacity)
                else:
                    # Fallback to KB if bytes not available
                    capacity_kb = getattr(device, "capacityInKB", None)
                    if capacity_kb is not None:
                        disk_data["capacity_bytes"] = int(capacity_kb) * 1024

                # Get backing info (VMDK file details)
                backing = getattr(device, "backing", None)
                if backing:
                    # Get disk mode
                    disk_mode = getattr(backing, "diskMode", None)
                    if disk_mode:
                        disk_data["disk_mode"] = str(disk_mode)

                    # Get thin provisioning
                    thin_provisioned = getattr(backing, "thinProvisioned", None)
                    if thin_provisioned is not None:
                        disk_data["thin_provisioned"] = bool(thin_provisioned)

                    # Get file name (disk path)
                    file_name = getattr(backing, "fileName", None)
                    if file_name:
                        disk_data["disk_path"] = str(file_name)
                        # Extract datastore name from path [datastore1] path/to/disk.vmdk
                        if file_name.startswith("[") and "]" in file_name:
                            datastore = file_name[1:file_name.index("]")]
                            disk_data["datastore"] = datastore

                    # Get provisioned size for thin disks
                    # For thin disks, capacity is max size, we need actual usage
                    datastore_name = disk_data.get("datastore")
                    if datastore_name and datastore_name in per_datastore_usage:
                        usage = per_datastore_usage[datastore_name]
                        # Use committed as provisioned size for thin disks
                        if usage.get("committed"):
                            disk_data["provisioned_bytes"] = int(usage["committed"])

                # Get controller type (SCSI, IDE, SATA, NVMe)
                controller_key = getattr(device, "controllerKey", None)
                if controller_key is not None:
                    # Find the controller
                    for ctrl_device in devices:
                        if getattr(ctrl_device, "key", None) == controller_key:
                            ctrl_type = type(ctrl_device).__name__
                            if "SCSI" in ctrl_type:
                                disk_data["type"] = "SCSI"
                            elif "IDE" in ctrl_type:
                                disk_data["type"] = "IDE"
                            elif "SATA" in ctrl_type:
                                disk_data["type"] = "SATA"
                            elif "NVMe" in ctrl_type:
                                disk_data["type"] = "NVMe"
                            break

                disks.append(disk_data)

        except Exception as exc:  # pragma: no cover - best effort
            logger.debug("Failed to retrieve disks via pyVmomi", exc_info=exc)

        return disks

    def _get_tag_name(self, tag_id: str) -> str | None:
        cached = self._tag_cache.get(tag_id)
        if cached:
            return cached
        payload = self._request(
            "GET",
            self._TAG_INFO_ENDPOINT.format(tag_id=tag_id),
            null_status=(404, 500, 501, 503),
        )
        if not isinstance(payload, Mapping):
            return None
        tag = payload.get("value")
        if isinstance(tag, Mapping):
            name = tag.get("name")
            if isinstance(name, str) and name.strip():
                cleaned = name.strip()
                self._tag_cache[tag_id] = cleaned
                return cleaned
        return None

    def list_vm_tags(self, vm_id: str) -> tuple[str, ...]:
        if not vm_id:
            return ()
        payload = self._request(
            "POST",
            self._TAG_LIST_ENDPOINT,
            json={"object_id": {"id": vm_id, "type": "VirtualMachine"}},
            ok_status=(200,),
            null_status=(400, 401, 403, 404, 500, 501, 503),
        )
        if not isinstance(payload, Mapping):
            return ()
        tag_ids = payload.get("value")
        if not isinstance(tag_ids, list):
            return ()
        names: list[str] = []
        for tag_id in tag_ids:
            if not isinstance(tag_id, str):
                continue
            name = self._get_tag_name(tag_id)
            if name:
                names.append(name)
        return tuple(names)

    def get_server_guid(self) -> str | None:
        cached = self._server_guid
        if cached:
            return cached

        self._ensure_session()
        url = f"{self._base_url}/sdk"
        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "Accept": "text/xml",
            "SOAPAction": "urn:vim25/ServiceInstance/RetrieveServiceContent",
        }
        envelope = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:vim25="urn:vim25">'
            "<soapenv:Body>"
            '<vim25:RetrieveServiceContent>'
            '<vim25:_this type="ServiceInstance">ServiceInstance</vim25:_this>'
            "</vim25:RetrieveServiceContent>"
            "</soapenv:Body>"
            "</soapenv:Envelope>"
        )

        server_guid: str | None = None

        try:
            response = self._session.post(url, data=envelope, headers=headers, timeout=self._timeout)
        except requests.RequestException:  # pragma: no cover - network error
            logger.debug("Failed to retrieve vCenter service content", exc_info=True)
        else:
            if response.status_code != 200:
                logger.debug(
                    "Unexpected status %s retrieving service content: %s",
                    response.status_code,
                    response.text.strip(),
                )
            else:
                content = response.text
                marker_start = "<instanceUuid>"
                marker_end = "</instanceUuid>"
                start = content.find(marker_start)
                if start != -1:
                    start += len(marker_start)
                    end = content.find(marker_end, start)
                    if end != -1:
                        candidate = content[start:end].strip()
                        if candidate:
                            server_guid = candidate

        if not server_guid:
            return None

        self._server_guid = server_guid
        return server_guid

    def _list_named_resources(self, path: str, identifier_key: str) -> dict[str, str]:
        payload = self._request("GET", path)
        if not isinstance(payload, Mapping):
            return {}
        values = payload.get("value")
        if not isinstance(values, list):
            return {}
        mapping: dict[str, str] = {}
        for item in values:
            if not isinstance(item, Mapping):
                continue
            identifier = item.get(identifier_key)
            name = item.get("name") or item.get("display_name")
            if isinstance(identifier, str):
                ident = identifier.strip()
                if not ident:
                    continue
                if isinstance(name, str) and name.strip():
                    mapping[ident] = name.strip()
                else:
                    mapping.setdefault(ident, ident)
        return mapping

    def list_datacenters(self) -> dict[str, str]:
        return self._list_named_resources(self._DATACENTER_LIST_ENDPOINT, "datacenter")

    def list_clusters(self) -> dict[str, str]:
        return self._list_named_resources(self._CLUSTER_LIST_ENDPOINT, "cluster")

    def list_hosts(self) -> dict[str, str]:
        return self._list_named_resources(self._HOST_LIST_ENDPOINT, "host")

    def list_resource_pools(self) -> dict[str, str]:
        return self._list_named_resources(self._RESOURCE_POOL_LIST_ENDPOINT, "resource_pool")

    def list_folders(self) -> dict[str, str]:
        return self._list_named_resources(self._FOLDER_LIST_ENDPOINT, "folder")
