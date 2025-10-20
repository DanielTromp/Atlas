#!/usr/bin/env python3
"""NetBox Virtual Machine Data Retrieval Script

This script connects to NetBox API and exports virtual machine data to CSV format.
It supports incremental updates by comparing timestamps to only fetch changed data.
"""

import argparse
import csv
import os
from pathlib import Path

from infrastructure_atlas import backup_sync
from infrastructure_atlas.env import apply_extra_headers, load_env, project_root, require_env
from infrastructure_atlas.infrastructure.external import NetboxClient, NetboxClientConfig

# Load environment variables from central loader (.env at project root)
load_env()
require_env(["NETBOX_URL", "NETBOX_TOKEN"])

# NetBox configuration
NETBOX_URL = os.getenv("NETBOX_URL")
NETBOX_TOKEN = os.getenv("NETBOX_TOKEN")

netbox_client = NetboxClient(NetboxClientConfig(url=NETBOX_URL, token=NETBOX_TOKEN))
nb = netbox_client.api
apply_extra_headers(nb.http_session)

# Resolve data directory relative to project root, defaulting to legacy location under netbox-export/
_root = project_root()
_data_dir_env = os.getenv("NETBOX_DATA_DIR", "data")
_data_dir_path = Path(_data_dir_env) if os.path.isabs(_data_dir_env) else (_root / _data_dir_env)
_data_dir_path.mkdir(parents=True, exist_ok=True)
CSV_FILE = str(_data_dir_path / "netbox_vms_export.csv")

# Shared helpers -------------------------------------------------------------


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

# --- Contacts helpers (NetBox 3.x/4.x compatible) ---

def _get_ct_id(nb, app_label: str, model: str) -> int:
    ct = nb.extras.content_types.get(app_label=app_label, model=model)
    if not ct:
        raise RuntimeError(f"ContentType {app_label}.{model} not found")
    return ct.id

def _get_contact_assignments_endpoint(nb):
    # NetBox >=3.6 uses 'contacts', older uses 'tenancy'
    if hasattr(nb, "contacts") and hasattr(nb.contacts, "contact_assignments"):
        return nb.contacts.contact_assignments
    if hasattr(nb, "tenancy") and hasattr(nb.tenancy, "contact_assignments"):
        return nb.tenancy.contact_assignments
    raise RuntimeError("No contact_assignments endpoint found")

def get_vm_contacts(nb, vm):
    """Return contacts for a VM as a string like 'Alice (Owner), Bob'."""
    try:
        try:
            ca_ep = _get_contact_assignments_endpoint(nb)
        except Exception:
            return ""

        # NetBox v4 prefers object_type/object_type_id; older uses content_type/content_type_id
        try:
            ct_id = _get_ct_id(nb, "virtualization", "virtualmachine")
        except Exception:
            ct_id = None

        filter_attempts = []
        if ct_id is not None:
            filter_attempts.append({"object_type_id": ct_id, "object_id": vm.id})
        filter_attempts.append({"object_type": "virtualization.virtualmachine", "object_id": vm.id})
        if ct_id is not None:
            filter_attempts.append({"content_type_id": ct_id, "object_id": vm.id})
        filter_attempts.append({"content_type": "virtualization.virtualmachine", "object_id": vm.id})

        assignments = []
        for params in filter_attempts:
            try:
                res = list(ca_ep.filter(**params))
                if res:
                    assignments = res
                    break
            except Exception:
                pass

        contacts = []
        for a in assignments:
            contact = getattr(a, "contact", None)
            role = getattr(a, "role", None)

            # Resolve contact name
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

            # Resolve role name
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

        return ", ".join(contacts) if contacts else ""
    except Exception:
        return ""

def _req_err_details(e) -> str:
    info = []
    try:
        req = getattr(e, "req", None) or getattr(e, "request", None)
        if req is not None:
            status = getattr(req, "status_code", None)
            url = getattr(req, "url", None)
            if status:
                info.append(f"status={status}")
            if url:
                info.append(f"url={url}")
            text = getattr(req, "text", "") or ""
            if text:
                snippet = text.strip().replace("\n", " ")
                info.append(f"response_snippet={snippet[:300]}")
    except Exception:
        pass
    return (" [" + ", ".join(info) + "]") if info else ""


def get_vm_metadata(client, *, force_refresh: bool = False):
    """Get VM metadata (id and last_updated) for comparison"""
    print("Fetching VM list from NetBox...")
    try:
        vms = client.list_vms(force_refresh=force_refresh)
        vm_metadata = {}

        for vm in vms:
            vm_metadata[vm.id] = {
                "last_updated": _to_iso(vm.last_updated),
            }

        print(f"Found {len(vm_metadata)} VMs in NetBox.")
        return vm_metadata
    except Exception as e:
        extra = _req_err_details(e)
        print(f"Error fetching VM metadata: {e}{extra}")
        return {}

def read_existing_csv():
    """Read existing CSV data and return as dictionary"""
    existing_data = {}

    if not os.path.exists(CSV_FILE):
        print("No existing CSV file found.")
        return existing_data

    print("Reading existing CSV data...")
    try:
        with open(CSV_FILE, newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            for row in reader:
                if row.get("ID"):
                    vm_id = int(row["ID"])
                    existing_data[vm_id] = {
                        "last_updated": row.get("Last updated"),
                        "row_data": row,
                    }

        print(f"Found {len(existing_data)} VMs in the CSV file.")
        return existing_data
    except Exception as e:
        print(f"Error reading existing CSV: {e}")
        return {}

def identify_changes(netbox_metadata, existing_data):
    """Identify new, updated, and deleted VMs"""
    new_vms = []
    updated_vms = []
    deleted_vms = []

    # Find new and updated VMs
    for vm_id, metadata in netbox_metadata.items():
        if vm_id not in existing_data:
            new_vms.append(vm_id)
        else:
            existing_updated = existing_data[vm_id]["last_updated"]
            netbox_updated = metadata["last_updated"]

            if existing_updated != netbox_updated:
                updated_vms.append(vm_id)

    # Find deleted VMs
    for vm_id in existing_data:
        if vm_id not in netbox_metadata:
            deleted_vms.append(vm_id)

    print(f"Identified {len(new_vms)} new VMs.")
    print(f"Identified {len(updated_vms)} updated VMs.")
    print(f"Identified {len(deleted_vms)} VMs to delete.")

    return new_vms, updated_vms, deleted_vms


def get_vm_details(client, vm_ids):
    """Get detailed VM information for specified VM IDs"""
    vm_details = {}

    if not vm_ids:
        return vm_details

    total_vms = len(vm_ids)
    print(f"Fetching details for {total_vms} VMs...")

    for i, vm_id in enumerate(vm_ids, 1):
        try:
            record = client.get_vm(vm_id)
            if not record:
                continue
            vm = record.source or _AttrProxy(record.raw)

            vm_data = {
                "Name": record.name,
                "Status": record.status_label or (record.status or ""),
                "Site": record.site or "",
                "Cluster": record.cluster or "",
                "Role": record.role_detail or record.role or "",
                "Tenant": record.tenant or "",
                "VCPUs": str(getattr(vm, "vcpus", "")) if getattr(vm, "vcpus", None) else "",
                "Memory (MB)": str(getattr(vm, "memory", "")) if getattr(vm, "memory", None) else "",
                "Disk": str(getattr(vm, "disk", "")) if getattr(vm, "disk", None) else "",
                "IP Address": record.primary_ip_best or "",
                "ID": str(record.id),
                "Device": str(getattr(vm, "device", "")) if getattr(vm, "device", None) else "",
                "Tenant Group": record.tenant_group or "",
                "IPv4 Address": record.primary_ip4 or "",
                "IPv6 Address": record.primary_ip6 or "",
                "Description": record.description or getattr(vm, "description", "") or "",
                "Comments": getattr(vm, "comments", "") or "",
                "Config Template": str(getattr(vm, "config_template", "")) if getattr(vm, "config_template", None) else "",
                "Serial number": "",
                "Contacts": get_vm_contacts(client.api, vm),
                "Tags": ", ".join(record.tags),
                "Created": _to_iso(getattr(vm, "created", "")),
                "Last updated": _to_iso(record.last_updated) or _to_iso(getattr(vm, "last_updated", "")),
                "Platform": record.platform or "",
                "Interfaces": "0",
                "Virtual Disks": "",
                "Backup": "",
                "DTAP state": "",
                "Harddisk": "",
                "open actions": "",
                "Server Group": "",
            }

            try:
                interfaces_attr = getattr(vm, "interfaces", None)
                if interfaces_attr is not None:
                    if hasattr(interfaces_attr, "count"):
                        vm_data["Interfaces"] = str(interfaces_attr.count())
                    else:
                        vm_data["Interfaces"] = str(len(interfaces_attr))
            except Exception:
                vm_data["Interfaces"] = "0"

            custom_fields = record.custom_fields or {}
            if custom_fields.get("Virtual_Disks"):
                vm_data["Virtual Disks"] = str(custom_fields["Virtual_Disks"])
            if custom_fields.get("Backup"):
                vm_data["Backup"] = str(custom_fields["Backup"])
            if custom_fields.get("DTAP_state"):
                vm_data["DTAP state"] = str(custom_fields["DTAP_state"])
            if custom_fields.get("Harddisk"):
                vm_data["Harddisk"] = str(custom_fields["Harddisk"])
            if custom_fields.get("open_actions"):
                vm_data["open actions"] = str(custom_fields["open_actions"])
            if custom_fields.get("Server Group"):
                vm_data["Server Group"] = str(custom_fields["Server Group"])

            vm_details[vm_id] = vm_data
            print(f"Progress: {i}/{total_vms} VMs processed")
        except Exception as e:
            extra = _req_err_details(e)
            print(f"Error fetching VM {vm_id}: {e}{extra}")

    return vm_details


def write_csv_data(vm_details, existing_data, deleted_vm_ids):
    """Write updated VM data to CSV file"""
    print("Writing updated data to CSV...")

    # Define CSV headers based on the exported structure
    headers = [
        "Name", "Status", "Site", "Cluster", "Role", "Tenant", "VCPUs", "Memory (MB)",
        "Disk", "IP Address", "ID", "Device", "Tenant Group", "IPv4 Address",
        "IPv6 Address", "Description", "Comments", "Config Template", "Serial number",
        "Contacts", "Tags", "Created", "Last updated", "Platform", "Interfaces",
        "Virtual Disks", "Backup", "DTAP state", "Harddisk", "open actions", "Server Group",
    ]

    # Create data directory if it doesn't exist
    os.makedirs(os.path.dirname(CSV_FILE), exist_ok=True)

    try:
        with open(CSV_FILE, "w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=headers)
            writer.writeheader()

            # Write existing data (excluding deleted VMs)
            for vm_id, data in existing_data.items():
                if vm_id not in deleted_vm_ids:
                    if vm_id not in vm_details:  # Keep unchanged existing data
                        writer.writerow(data["row_data"])

            # Write new/updated VM data
            for vm_data in vm_details.values():
                writer.writerow(vm_data)

        # CSV file written; summary printed by caller
        try:
            backup_sync.sync_paths([Path(CSV_FILE)], note="netbox_vms")
        except Exception:  # pragma: no cover - defensive logging
            pass
    except Exception as e:
        print(f"Error writing CSV file: {e}")

def main():
    """Main function"""
    parser = argparse.ArgumentParser(description="Export NetBox VMs to CSV")
    parser.add_argument("--force", action="store_true", help="Re-fetch all VMs and rewrite CSV")
    args = parser.parse_args()

    print("Starting NetBox VMs data synchronization...")

    netbox_metadata = get_vm_metadata(netbox_client, force_refresh=args.force)
    if not netbox_metadata:
        print("No VMs found in NetBox or error occurred.")
        return

    if args.force:
        print("Force refresh enabled: re-fetching all VMs...")
        existing_data = {}
        vms_to_fetch = list(netbox_metadata.keys())
        deleted_vms = []
    else:
        # Read existing CSV data
        existing_data = read_existing_csv()
        # Identify changes
        new_vms, updated_vms, deleted_vms = identify_changes(netbox_metadata, existing_data)
        vms_to_fetch = new_vms + updated_vms

    # Get details for target VMs
    vm_details = get_vm_details(netbox_client, vms_to_fetch)

    # Write updated data to CSV
    write_csv_data(vm_details, existing_data, deleted_vms)

    print("Sync complete.")

if __name__ == "__main__":
    main()
