"""In-process NetBox exporter infrastructure."""
from __future__ import annotations

import csv
import json
import logging
import os
import runpy
import sys
from collections.abc import Iterable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from infrastructure_atlas import backup_sync
from infrastructure_atlas.domain.integrations import NetboxDeviceRecord, NetboxVMRecord


def _coerce_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass(slots=True)
class ExportPaths:
    data_dir: Path
    devices_csv: Path
    vms_csv: Path
    merged_csv: Path
    excel_path: Path
    scripts_root: Path
    manifest_path: Path
    cache_json: Path


@dataclass(slots=True)
class ExportArtifacts:
    devices_csv: Path
    vms_csv: Path
    merged_csv: Path


@dataclass(slots=True)
class ExportManifest:
    version: int
    devices: dict[str, str]
    vms: dict[str, str]

    @classmethod
    def empty(cls) -> ExportManifest:
        return cls(version=1, devices={}, vms={})


class NetboxExporter:
    """Abstract exporter interface."""

    def export(
        self,
        *,
        force: bool = False,
        verbose: bool = False,
        devices: Sequence[NetboxDeviceRecord] | None = None,
        vms: Sequence[NetboxVMRecord] | None = None,
    ) -> ExportArtifacts:  # pragma: no cover - interface
        raise NotImplementedError


class LegacyScriptNetboxExporter(NetboxExporter):
    """Exporter that defers to the existing legacy scripts in-process."""

    def __init__(self, paths: ExportPaths) -> None:
        self._paths = paths

    def export(
        self,
        *,
        force: bool = False,
        verbose: bool = False,
        devices: Sequence[NetboxDeviceRecord] | None = None,
        vms: Sequence[NetboxVMRecord] | None = None,
    ) -> ExportArtifacts:
        self._run_script("netbox-export/bin/get_netbox_devices.py", force=force)
        self._run_script("netbox-export/bin/get_netbox_vms.py", force=force)
        return ExportArtifacts(
            devices_csv=self._paths.devices_csv,
            vms_csv=self._paths.vms_csv,
            merged_csv=self._paths.merged_csv,
        )

    def _run_script(self, relative_path: str, *, force: bool) -> None:
        script = self._paths.scripts_root / relative_path
        args: list[str] = [script.as_posix()]
        if force:
            args.append("--force")
        with _script_argv(args):
            runpy.run_path(str(script), run_name="__main__")


class NativeNetboxExporter(NetboxExporter):
    """In-process exporter that avoids legacy scripts."""

    def __init__(self, client, paths: ExportPaths, *, logger: logging.Logger | None = None) -> None:
        self._client = client
        self._paths = paths
        self._logger = logger or logging.getLogger(__name__)
        self._api = getattr(client, "api", None)
        self._verbose = False
        self._manifest: ExportManifest = ExportManifest.empty()

    def export(
        self,
        *,
        force: bool = False,
        verbose: bool = False,
        devices: Sequence[NetboxDeviceRecord] | None = None,
        vms: Sequence[NetboxVMRecord] | None = None,
    ) -> ExportArtifacts:
        self._verbose = verbose
        self._paths.data_dir.mkdir(parents=True, exist_ok=True)
        self._manifest = _load_export_manifest(self._paths.manifest_path)
        success = False
        try:
            self._export_devices(force, records=devices)
            self._export_vms(force, records=vms)
            success = True
        finally:
            if success:
                _save_export_manifest(self._manifest, self._paths.manifest_path)
        return ExportArtifacts(
            devices_csv=self._paths.devices_csv,
            vms_csv=self._paths.vms_csv,
            merged_csv=self._paths.merged_csv,
        )

    def _export_devices(
        self,
        force: bool,
        *,
        records: Sequence[NetboxDeviceRecord] | None = None,
    ) -> None:
        if records is None:
            records = self._client.list_devices(force_refresh=force)
        records = list(records)
        record_lookup = {str(record.id): record for record in records}
        metadata = {str(record.id): _to_iso(record.last_updated) for record in records}
        existing = _load_existing_csv(self._paths.devices_csv)
        to_add, to_update, to_delete = _identify_device_changes(
            metadata,
            existing,
            force,
            previous=self._manifest.devices,
        )

        self._logger.info(
            "Device diff computed",
            extra={
                "new": len(to_add),
                "updated": len(to_update),
                "deleted": len(to_delete),
                "total": len(records),
            },
        )
        if self._verbose:
            self._logger.info(
                "Preparing device export",
                extra={
                    "force_run": force,
                    "records": len(records),
                    "prefetch_targets": len(to_add) + len(to_update),
                },
            )

        contact_assignments = _prefetch_contact_assignments(
            self._api,
            "dcim.device",
            (record_lookup.get(str(device_id)) for device_id in to_add + to_update),
            logger=self._logger,
            verbose=self._verbose,
        )

        full_rows: dict[str, dict[str, str]] = {}
        for device_id in to_add + to_update:
            try:
                record = record_lookup.get(str(device_id))
                row = _build_device_row(
                    self._client,
                    device_id,
                    record=record,
                    assignments=contact_assignments.get(str(device_id)),
                )
                full_rows[str(device_id)] = row
            except Exception as exc:  # pragma: no cover - defensive
                self._logger.warning(
                    "Failed to build device row",
                    extra={"device_id": device_id, "error": str(exc)},
                )

        for key, value in full_rows.items():
            existing[key] = {**value, "ID": key}

        for device_id in to_delete:
            existing.pop(str(device_id), None)

        headers = _derive_headers(existing, full_rows)
        _write_csv(self._paths.devices_csv, headers, existing)
        try:
            backup_sync.sync_paths([self._paths.devices_csv], note="netbox_devices")
        except Exception:  # pragma: no cover - best effort
            pass

        for device_id in to_add + to_update:
            last = metadata.get(str(device_id))
            if last is not None:
                self._manifest.devices[str(device_id)] = last
        for device_id in to_delete:
            self._manifest.devices.pop(str(device_id), None)

    def _export_vms(
        self,
        force: bool,
        *,
        records: Sequence[NetboxVMRecord] | None = None,
    ) -> None:
        if records is None:
            records = self._client.list_vms(force_refresh=force)
        records = list(records)
        record_lookup = {int(record.id): record for record in records}
        metadata = {int(record.id): _to_iso(record.last_updated) for record in records}
        existing = _load_existing_vm_csv(self._paths.vms_csv)
        to_add, to_update, to_delete = _identify_vm_changes(
            metadata,
            existing,
            force,
            previous=self._manifest.vms,
        )

        self._logger.info(
            "VM diff computed",
            extra={
                "new": len(to_add),
                "updated": len(to_update),
                "deleted": len(to_delete),
                "total": len(records),
            },
        )
        if self._verbose:
            self._logger.info(
                "Preparing VM export",
                extra={
                    "force_run": force,
                    "records": len(records),
                    "prefetch_targets": len(to_add) + len(to_update),
                },
            )

        updated_rows: dict[int, dict[str, str]] = {}
        contact_assignments = _prefetch_contact_assignments(
            self._api,
            "virtualization.virtualmachine",
            (record_lookup.get(vm_id) for vm_id in to_add + to_update),
            logger=self._logger,
            verbose=self._verbose,
        )
        for vm_id in to_add + to_update:
            try:
                record = record_lookup.get(vm_id)
                row = _build_vm_row(
                    self._client,
                    vm_id,
                    record=record,
                    assignments=contact_assignments.get(str(vm_id)),
                )
                updated_rows[int(vm_id)] = row
            except Exception as exc:  # pragma: no cover - defensive
                self._logger.warning(
                    "Failed to build VM row",
                    extra={"vm_id": vm_id, "error": str(exc)},
                )

        for vm_id, value in updated_rows.items():
            existing[vm_id] = {"last_updated": metadata.get(vm_id), "row_data": value}

        for vm_id in to_delete:
            existing.pop(vm_id, None)

        _write_vm_csv(self._paths.vms_csv, existing)
        try:
            backup_sync.sync_paths([self._paths.vms_csv], note="netbox_vms")
        except Exception:  # pragma: no cover
            pass

        for vm_id in to_add + to_update:
            last = metadata.get(vm_id)
            if last is not None:
                self._manifest.vms[str(vm_id)] = last
        for vm_id in to_delete:
            self._manifest.vms.pop(str(vm_id), None)


# Helper functions -----------------------------------------------------------------


def _to_iso(dt):
    if not dt:
        return ""
    if isinstance(dt, str):
        return dt
    try:
        return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except Exception:
        return str(dt)


class _ListProxy(list):
    def all(self):
        return list(self)


class _AttrProxy:
    def __init__(self, payload):
        self._payload = payload or {}

    def __getattr__(self, item):
        if item == "_payload":
            return super().__getattribute__(item)
        value = self._payload.get(item)
        if isinstance(value, dict):
            return _AttrProxy(value)
        if isinstance(value, list):
            proxied = [_AttrProxy(v) if isinstance(v, dict) else v for v in value]
            return _ListProxy(proxied)
        return value


_DEF_HEADERS = [
    "Comments",
    "Platform",
    "Server Group",
    "DTAP state",
    "CPU",
    "Memory",
    "Monitor hardware",
    "HW buy date",
    "HW warranty expiration",
    "Warranty type",
]


def _load_existing_csv(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    data: dict[str, dict[str, str]] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            key = row.get("ID")
            if key:
                data[str(key)] = row
    return data


def _load_existing_vm_csv(path: Path) -> dict[int, dict[str, object]]:
    if not path.exists():
        return {}
    data: dict[int, dict[str, object]] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if not row.get("ID"):
                continue
            vm_id = _coerce_int(row.get("ID"))
            if vm_id is None:
                continue
            data[vm_id] = {"last_updated": row.get("Last updated"), "row_data": row}
    return data


def _identify_device_changes(
    metadata: Mapping[str, str],
    existing: Mapping[str, dict[str, str]],
    force: bool,
    *,
    previous: Mapping[str, str] | None = None,
) -> tuple[list[str], list[str], list[str]]:
    if previous is not None:
        source = dict(previous)
    else:
        source = {key: row.get("Last updated") for key, row in existing.items()}

    if force:
        to_delete = [key for key in source if key not in metadata]
        return list(metadata.keys()), [], to_delete

    to_add: list[str] = []
    to_update: list[str] = []
    for device_id, last_updated in metadata.items():
        previous_last = source.get(device_id)
        if previous_last is None:
            to_add.append(device_id)
        elif previous_last != last_updated:
            to_update.append(device_id)

    to_delete = [key for key in source if key not in metadata]
    return to_add, to_update, to_delete


def _identify_vm_changes(
    metadata: Mapping[int, str],
    existing: Mapping[int, dict[str, object]],
    force: bool,
    *,
    previous: Mapping[str, str] | None = None,
) -> tuple[list[int], list[int], list[int]]:
    if previous is not None:
        prev_lookup: dict[int, str | None] = {}
        for key, value in previous.items():
            try:
                prev_lookup[int(key)] = value
            except (TypeError, ValueError):
                continue
    else:
        prev_lookup = {vm_id: row.get("last_updated") for vm_id, row in existing.items()}

    if force:
        to_delete = [key for key in prev_lookup if key not in metadata]
        return list(metadata.keys()), [], to_delete

    new_vms: list[int] = []
    updated_vms: list[int] = []
    for vm_id, meta in metadata.items():
        previous_last = prev_lookup.get(vm_id)
        if previous_last is None:
            new_vms.append(vm_id)
        elif previous_last != meta:
            updated_vms.append(vm_id)

    deleted = [key for key in prev_lookup if key not in metadata]
    return new_vms, updated_vms, deleted


def _derive_headers(existing: Mapping[str, dict[str, str]], updates: Mapping[str, dict[str, str]]) -> list[str]:
    headers: list[str] = []
    sample_row = None
    if existing:
        sample_row = next(iter(existing.values()))
    elif updates:
        sample_row = next(iter(updates.values()))
    if sample_row:
        headers.extend(sample_row.keys())
    seen = set(headers)
    for rows in (existing.values(), updates.values()):
        for row in rows:
            for key in row.keys():
                if key not in seen:
                    headers.append(key)
                    seen.add(key)
    for key in _DEF_HEADERS:
        if key not in seen:
            headers.append(key)
            seen.add(key)
    return headers


def _write_csv(path: Path, headers: Sequence[str], rows: Mapping[str, dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(headers))
        writer.writeheader()
        for row in rows.values():
            writer.writerow(row)


def _write_vm_csv(path: Path, existing: Mapping[int, dict[str, object]]) -> None:
    headers = [
        "Name",
        "Status",
        "Site",
        "Cluster",
        "Role",
        "Tenant",
        "VCPUs",
        "Memory (MB)",
        "Disk",
        "IP Address",
        "ID",
        "Device",
        "Tenant Group",
        "IPv4 Address",
        "IPv6 Address",
        "Description",
        "Comments",
        "Config Template",
        "Serial number",
        "Contacts",
        "Tags",
        "Created",
        "Last updated",
        "Platform",
        "Interfaces",
        "Virtual Disks",
        "Backup",
        "DTAP state",
        "Harddisk",
        "open actions",
        "Server Group",
    ]
    os.makedirs(path.parent, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=headers)
        writer.writeheader()
        for _vm_id, payload in existing.items():
            row_data = payload.get("row_data")
            if isinstance(row_data, dict):
                writer.writerow(row_data)


# Device detail helpers -----------------------------------------------------------


def _build_device_row(
    client,
    device_id: str | int,
    *,
    record: NetboxDeviceRecord | None = None,
    assignments: Sequence[object] | None = None,
) -> dict[str, str]:
    record = record or client.get_device(device_id)
    device = record.source or _AttrProxy(record.raw)
    custom_fields = record.custom_fields or {}
    last_updated_str = _to_iso(record.last_updated) or _to_iso(getattr(device, "last_updated", ""))
    base = {
        "Name": record.name,
        "Status": record.status_label or "",
        "Tenant": record.tenant or "",
        "Site": record.site or "",
        "Location": record.location or "",
        "Rack": getattr(device, "rack", ""),
        "Rack Position": _rack_position(device),
        "Role": record.role or "",
        "Manufacturer": record.manufacturer or "",
        "Type": record.model or "",
        "IP Address": record.primary_ip_best or "",
        "ID": str(record.id),
        "Tenant Group": record.tenant_group or "",
        "Serial number": record.serial or "",
        "Asset tag": record.asset_tag or "",
        "Region": record.region or "",
        "Site Group": record.site_group or "",
        "Parent Device": _stringify(getattr(getattr(device, "parent_device", None), "name", "")),
        "Position (Device Bay)": _stringify(getattr(device, "device_bay", "")),
        "Position": _stringify(getattr(device, "position", "")),
        "Rack face": _stringify(getattr(device, "face", "")),
        "Latitude": _stringify(getattr(device, "latitude", "")),
        "Longitude": _stringify(getattr(device, "longitude", "")),
        "Airflow": _stringify(getattr(device, "airflow", "")),
        "IPv4 Address": record.primary_ip4 or "",
        "IPv6 Address": record.primary_ip6 or "",
        "OOB IP": record.oob_ip or "",
        "Cluster": record.cluster or "",
        "Virtual Chassis": _stringify(getattr(device, "virtual_chassis", "")),
        "VC Position": _stringify(getattr(device, "vc_position", "")),
        "VC Priority": _stringify(getattr(device, "vc_priority", "")),
        "Description": record.description or _stringify(getattr(device, "description", "")),
        "Config Template": _stringify(getattr(getattr(device, "config_template", None), "name", "")),
        "Comments": _stringify(getattr(device, "comments", "")),
        "Contacts": _render_contacts(client.api, assignments, device),
        "Tags": ", ".join(record.tags),
        "Created": _stringify(getattr(device, "created", "")),
        "Last updated": last_updated_str,
        "Platform": _stringify(getattr(getattr(device, "platform", None), "name", "")),
        "Server Group": _cf_get(custom_fields, "Server Group", "Server_Group"),
        "Backup": _cf_get(custom_fields, "Backup"),
        "DTAP state": _cf_get(custom_fields, "DTAP state", "DTAP_state"),
        "Harddisk": _cf_get(custom_fields, "Harddisk"),
        "open actions": _cf_get(custom_fields, "open actions", "open_actions"),
        "CPU": _cf_get(custom_fields, "CPU"),
        "Memory": _cf_get(custom_fields, "Memory"),
        "Monitor hardware": _cf_get(custom_fields, "Monitor hardware", "Monitor_hardware"),
        "HW buy date": _cf_get(custom_fields, "HW buy date", "HW_buy_date", "HW purchase date", "Purchase date"),
        "HW warranty expiration": _cf_get(custom_fields, "HW warranty expiration", "HW_warranty_expiration", "Warranty expiration", "Warranty expiry", "Warranty until"),
        "Warranty type": _cf_get(custom_fields, "Warranty type", "Warranty_type"),
        "Console ports": _stringify(getattr(device, "console_port_count", 0)),
        "Console server ports": _stringify(getattr(device, "console_server_port_count", 0)),
        "Power ports": _stringify(getattr(device, "power_port_count", 0)),
        "Power outlets": _stringify(getattr(device, "power_outlet_count", 0)),
        "Interfaces": _stringify(getattr(device, "interface_count", 0)),
        "Front ports": _stringify(getattr(device, "front_port_count", 0)),
        "Rear ports": _stringify(getattr(device, "rear_port_count", 0)),
        "Device bays": _stringify(getattr(device, "device_bay_count", 0)),
        "Module bays": _stringify(getattr(device, "module_bay_count", 0)),
        "Inventory items": _stringify(getattr(device, "inventory_item_count", "")),
    }
    return {k: _stringify(v) for k, v in base.items()}


def _rack_position(device) -> str:
    face = getattr(getattr(device, "face", ""), "label", getattr(device, "face", ""))
    position = getattr(device, "position", "")
    if face and position:
        return f"{face} {position}".strip()
    return str(position or "")


def _stringify(value) -> str:
    if value is None:
        return ""
    return str(value)


def _build_vm_row(
    client,
    vm_id: int,
    *,
    record: NetboxVMRecord | None = None,
    assignments: Sequence[object] | None = None,
) -> dict[str, str]:
    record = record or client.get_vm(vm_id)
    vm = record.source or _AttrProxy(record.raw)
    custom_fields = record.custom_fields or {}
    base = {
        "Name": record.name,
        "Status": record.status_label or (record.status or ""),
        "Site": record.site or "",
        "Cluster": record.cluster or "",
        "Role": record.role_detail or record.role or "",
        "Tenant": record.tenant or "",
        "VCPUs": _stringify(getattr(vm, "vcpus", "")),
        "Memory (MB)": _stringify(getattr(vm, "memory", "")),
        "Disk": _stringify(getattr(vm, "disk", "")),
        "IP Address": record.primary_ip_best or "",
        "ID": str(record.id),
        "Device": _stringify(getattr(vm, "device", "")),
        "Tenant Group": record.tenant_group or "",
        "IPv4 Address": record.primary_ip4 or "",
        "IPv6 Address": record.primary_ip6 or "",
        "Description": record.description or _stringify(getattr(vm, "description", "")),
        "Comments": _stringify(getattr(vm, "comments", "")),
        "Config Template": _stringify(getattr(getattr(vm, "config_template", None), "name", "")),
        "Serial number": "",
        "Contacts": "",
        "Tags": ", ".join(record.tags),
        "Created": _to_iso(getattr(vm, "created", "")),
        "Last updated": _to_iso(record.last_updated) or _to_iso(getattr(vm, "last_updated", "")),
        "Platform": record.platform or "",
        "Interfaces": _vm_interface_count(vm),
        "Virtual Disks": _stringify(custom_fields.get("Virtual_Disks", "")),
        "Backup": _stringify(custom_fields.get("Backup", "")),
        "DTAP state": _stringify(custom_fields.get("DTAP_state", "")),
        "Harddisk": _stringify(custom_fields.get("Harddisk", "")),
        "open actions": _stringify(custom_fields.get("open_actions", "")),
        "Server Group": _stringify(custom_fields.get("Server Group", "")),
    }
    contacts_str = _render_vm_contacts(client.api, assignments, vm)
    base["Contacts"] = contacts_str
    # Debug logging
    if hasattr(vm, "id") and getattr(vm, "id", None) == 229:  # api-prod4
        import logging
        logger = logging.getLogger(__name__)
        logger.info(
            "DEBUG api-prod4 contacts",
            extra={
                "vm_id": 229,
                "assignments": assignments if assignments else "None/Empty",
                "contacts_str": contacts_str,
            },
        )
    return {k: _stringify(v) for k, v in base.items()}


def _vm_interface_count(vm) -> str:
    try:
        interfaces_attr = getattr(vm, "interfaces", None)
        if interfaces_attr is not None:
            if hasattr(interfaces_attr, "count"):
                return str(interfaces_attr.count())
            return str(len(interfaces_attr))
    except Exception:
        return "0"
    return "0"


def _get_device_contacts(nb, device) -> str:
    if nb is None:
        return ""
    try:
        ca_ep = _get_contact_assignments_endpoint(nb)
    except Exception:
        return ""

    ct_id = None
    try:
        ct_id = _get_ct_id(nb, "dcim", "device")
    except Exception:
        ct_id = None

    filter_attempts = []
    if ct_id is not None:
        filter_attempts.append({"object_type_id": ct_id, "object_id": getattr(device, "id", None)})
    filter_attempts.append({"object_type": "dcim.device", "object_id": getattr(device, "id", None)})
    if ct_id is not None:
        filter_attempts.append({"content_type_id": ct_id, "object_id": getattr(device, "id", None)})
    filter_attempts.append({"content_type": "dcim.device", "object_id": getattr(device, "id", None)})

    assignments = []
    for params in filter_attempts:
        try:
            result_iter = ca_ep.filter(**params)
        except Exception:
            result_iter = None
        if result_iter is None:
            continue
        result: list[object] = list(result_iter)
        if result:
            assignments = result
            break

    return _render_assignments(nb, assignments)


def _get_vm_contacts(nb, vm) -> str:
    if nb is None:
        return ""
    try:
        ct_id = _get_ct_id(nb, "virtualization", "virtualmachine")
    except Exception:
        ct_id = None

    try:
        ca_ep = _get_contact_assignments_endpoint(nb)
    except Exception:
        return ""

    filter_attempts = []
    if ct_id is not None:
        filter_attempts.append({"object_type_id": ct_id, "object_id": getattr(vm, "id", None)})
    filter_attempts.append({"object_type": "virtualization.virtualmachine", "object_id": getattr(vm, "id", None)})
    if ct_id is not None:
        filter_attempts.append({"content_type_id": ct_id, "object_id": getattr(vm, "id", None)})
    filter_attempts.append({"content_type": "virtualization.virtualmachine", "object_id": getattr(vm, "id", None)})

    assignments = []
    for params in filter_attempts:
        try:
            result_iter = ca_ep.filter(**params)
        except Exception:
            result_iter = None
        if result_iter is None:
            continue
        result: list[object] = list(result_iter)
        if result:
            assignments = result
            break

    return _render_assignments(nb, assignments)

def _render_contacts(nb, assignments: Sequence[object] | None, device) -> str:
    if assignments is None:
        return _get_device_contacts(nb, device)
    if not assignments:
        return ""
    return _render_assignments(nb, assignments)


def _render_vm_contacts(nb, assignments: Sequence[object] | None, vm) -> str:
    if assignments is None:
        return _get_vm_contacts(nb, vm)
    if not assignments:
        return ""
    return _render_assignments(nb, assignments)


def _render_assignments(nb, assignments: Sequence[object]) -> str:
    contacts: list[str] = []
    for assignment in assignments:
        contact = getattr(assignment, "contact", None)
        role = getattr(assignment, "role", None)
        c_name = getattr(contact, "name", None)
        if not c_name and isinstance(contact, dict):
            c_name = contact.get("name") or contact.get("display")
            if not c_name and contact.get("id") and hasattr(nb, "contacts") and hasattr(nb.contacts, "contacts"):
                try:
                    c_obj = nb.contacts.contacts.get(contact.get("id"))
                    if c_obj:
                        c_name = getattr(c_obj, "name", None) or getattr(c_obj, "display", None)
                except Exception:
                    pass
        r_name = getattr(role, "name", None)
        if not r_name and isinstance(role, dict):
            r_name = role.get("name") or role.get("display")
            if not r_name and role.get("id") and hasattr(nb, "contacts") and hasattr(nb.contacts, "contact_roles"):
                try:
                    r_obj = nb.contacts.contact_roles.get(role.get("id"))
                    if r_obj:
                        r_name = getattr(r_obj, "name", None) or getattr(r_obj, "display", None)
                except Exception:
                    pass
        if c_name:
            contacts.append(f"{c_name} ({r_name})" if r_name else c_name)
    if contacts:
        return ", ".join(contacts)
    return ""


def _chunked(values: Sequence[int], size: int) -> Iterable[Sequence[int]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _assign_contact_results(assignments: dict[str, list[object]], result_iter: Iterable[object]) -> None:
    for item in result_iter:
        object_id = getattr(item, "object_id", None)
        if object_id is None:
            obj = getattr(item, "object", None)
            object_id = getattr(obj, "id", None)
        key = str(object_id) if object_id is not None else None
        if key and key in assignments:
            assignments[key].append(item)


def _prefetch_contact_assignments(
    nb,
    object_type: str,
    records: Iterable[NetboxDeviceRecord | NetboxVMRecord | None],
    *,
    batch_size: int = 1000,
    logger: logging.Logger | None = None,
    verbose: bool = False,
) -> dict[str, list[object]]:
    if nb is None:
        return {}
    try:
        ca_ep = _get_contact_assignments_endpoint(nb)
    except Exception:
        return {}

    normalized_ids: list[int] = []
    for record in records:
        if record is None:
            continue
        identifier = getattr(record, "id", None)
        if identifier is None:
            continue
        coerced = _coerce_int(identifier)
        if coerced is None:
            continue
        normalized_ids.append(coerced)

    if not normalized_ids:
        return {}

    unique_ids = sorted(set(normalized_ids))
    assignments: dict[str, list[object]] = {str(identifier): [] for identifier in unique_ids}
    chunk_size = max(1, batch_size)

    if verbose and logger:
        total_chunks = max(1, (len(unique_ids) + chunk_size - 1) // chunk_size)
        logger.info(
            "Prefetching NetBox contact assignments",
            extra={
                "object_type": object_type,
                "targets": len(unique_ids),
                "batch_size": chunk_size,
                "chunks": total_chunks,
            },
        )
    else:
        total_chunks = None

    # Always use bulk fetch - it's more efficient and avoids 414 errors with object_id__in
    try:
        if verbose and logger:
            logger.info(
                "Bulk fetching contact assignments",
                extra={
                    "object_type": object_type,
                    "targets": len(unique_ids),
                },
            )
        bulk_iter = ca_ep.filter(object_type=object_type, limit=0)
        total_assignments = 0
        for item in bulk_iter:
            object_id = getattr(item, "object_id", None)
            if object_id is None:
                obj = getattr(item, "object", None)
                object_id = getattr(obj, "id", None)
            key = str(object_id) if object_id is not None else None
            if key and key in assignments:
                assignments[key].append(item)
                total_assignments += 1
        if verbose and logger:
            logger.info(
                "Bulk contact fetch completed",
                extra={
                    "object_type": object_type,
                    "targets": len(unique_ids),
                    "assignments": total_assignments,
                },
            )
        return assignments
    except Exception as exc:
        if verbose and logger:
            logger.warning(
                "Bulk contact fetch failed; falling back to individual requests",
                extra={
                    "object_type": object_type,
                    "error": str(exc),
                },
            )

    # Fallback: fetch individually (slower but more reliable)
    for index, identifier in enumerate(unique_ids, start=1):
        if verbose and logger and index % 100 == 0:
            logger.info(
                "Fetching contacts individually",
                extra={
                    "object_type": object_type,
                    "progress": f"{index}/{len(unique_ids)}",
                },
            )
        params = {"object_type": object_type, "limit": 0, "object_id": identifier}
        try:
            result_iter = ca_ep.filter(**params)
            _assign_contact_results(assignments, result_iter)
        except Exception as exc:
            if verbose and logger:
                logger.warning(
                    "Contact fetch failed for individual item",
                    extra={
                        "object_type": object_type,
                        "object_id": identifier,
                        "error": str(exc),
                    },
                )
            continue
    if verbose and logger:
        logger.info(
            "Contact prefetch completed",
            extra={
                "object_type": object_type,
                "targets": len(unique_ids),
                "assignments": sum(len(items) for items in assignments.values()),
            },
        )
    return assignments


def _get_contact_assignments_endpoint(nb):
    if hasattr(nb, "contacts") and hasattr(nb.contacts, "contact_assignments"):
        return nb.contacts.contact_assignments
    if hasattr(nb, "tenancy") and hasattr(nb.tenancy, "contact_assignments"):
        return nb.tenancy.contact_assignments
    raise RuntimeError("No contact_assignments endpoint found")


def _get_ct_id(nb, app_label: str, model: str) -> int:
    ct = nb.extras.content_types.get(app_label=app_label, model=model)
    if not ct:
        raise RuntimeError(f"ContentType {app_label}.{model} not found")
    return ct.id


def _norm_key(value: str) -> str:
    try:
        return "".join(ch.lower() for ch in str(value) if ch.isalnum())
    except Exception:
        return str(value).lower()


def _cf_get(cf: Mapping[str, object], *candidates: str) -> str:
    if not cf or not candidates:
        return ""
    lookup = {_norm_key(k): v for k, v in cf.items()}
    for candidate in candidates:
        value = lookup.get(_norm_key(candidate))
        if value is None:
            continue
        if isinstance(value, list):
            return ", ".join(str(item) for item in value)
        return str(value)
    return ""


def _load_export_manifest(path: Path) -> ExportManifest:
    if not path.exists():
        return ExportManifest.empty()
    try:
        with path.open(encoding="utf-8") as fh:
            payload = json.load(fh)
    except Exception:
        return ExportManifest.empty()

    version = int(payload.get("version", 1))
    devices_raw = payload.get("devices", {})
    vms_raw = payload.get("vms", {})
    devices = _normalize_manifest_entries(devices_raw)
    vms = _normalize_manifest_entries(vms_raw)
    return ExportManifest(version=version, devices=devices, vms=vms)


def _save_export_manifest(manifest: ExportManifest, path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": manifest.version,
            "devices": manifest.devices,
            "vms": manifest.vms,
        }
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
        tmp_path.replace(path)
    except Exception:
        # Best-effort persistence; ignore failures to keep export resilient.
        pass


def _normalize_manifest_entries(raw: Mapping[str, object]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in raw.items():
        if key is None:
            continue
        normalized[str(key)] = "" if value in (None, "") else str(value)
    return normalized


@contextmanager
def _script_argv(args: Iterable[str]):
    old = sys.argv[:]
    sys.argv = list(args)
    try:
        yield
    finally:
        sys.argv = old


__all__ = [
    "ExportArtifacts",
    "ExportManifest",
    "ExportPaths",
    "LegacyScriptNetboxExporter",
    "NativeNetboxExporter",
    "NetboxExporter",
]
