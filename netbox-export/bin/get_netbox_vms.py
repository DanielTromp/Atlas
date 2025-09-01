#!/usr/bin/env python3
"""NetBox Virtual Machine Data Retrieval Script

This script connects to NetBox API and exports virtual machine data to CSV format.
It supports incremental updates by comparing timestamps to only fetch changed data.
"""

import csv
import os
import sys
from pathlib import Path

import pynetbox

from enreach_tools.env import apply_extra_headers, load_env, project_root, require_env

# Load environment variables from central loader (.env at project root)
load_env()
require_env(["NETBOX_URL", "NETBOX_TOKEN"])

# NetBox configuration
NETBOX_URL = os.getenv("NETBOX_URL")
NETBOX_TOKEN = os.getenv("NETBOX_TOKEN")

# Resolve data directory relative to project root, defaulting to legacy location under netbox-export/
_root = project_root()
_data_dir_env = os.getenv("NETBOX_DATA_DIR", "netbox-export/data")
_data_dir_path = Path(_data_dir_env) if os.path.isabs(_data_dir_env) else (_root / _data_dir_env)
CSV_FILE = str(_data_dir_path / "netbox_vms_export.csv")

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


def connect_to_netbox():
    """Connect to NetBox API"""
    try:
        nb = pynetbox.api(NETBOX_URL, token=NETBOX_TOKEN)
        apply_extra_headers(nb.http_session)
        return nb
    except Exception as e:
        print(f"Error connecting to NetBox: {e}")
        sys.exit(1)

def get_vm_metadata(nb):
    """Get VM metadata (id and last_updated) for comparison"""
    print("Fetching VM list from NetBox...")
    try:
        # Get all VMs with minimal fields for comparison
        vms = nb.virtualization.virtual_machines.all()
        vm_metadata = {}

        for vm in vms:
            # Handle last_updated field - it might be a string or datetime object
            last_updated = vm.last_updated
            if last_updated:
                if hasattr(last_updated, "isoformat"):
                    last_updated = last_updated.isoformat()
                else:
                    last_updated = str(last_updated)

            vm_metadata[vm.id] = {
                "last_updated": last_updated,
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

def get_vm_details(nb, vm_ids):
    """Get detailed VM information for specified VM IDs"""
    vm_details = {}

    if not vm_ids:
        return vm_details

    total_vms = len(vm_ids)
    print(f"Fetching details for {total_vms} VMs...")

    for i, vm_id in enumerate(vm_ids, 1):
        try:
            vm = nb.virtualization.virtual_machines.get(vm_id)
            if vm:
                # Extract VM data with comprehensive field mapping
                vm_data = {
                    "Name": vm.name or "",
                    "Status": str(vm.status) if vm.status else "",
                    "Site": str(vm.site) if vm.site else "",
                    "Cluster": str(vm.cluster) if vm.cluster else "",
                    "Role": str(vm.role) if vm.role else "",
                    "Tenant": str(vm.tenant) if vm.tenant else "",
                    "VCPUs": str(vm.vcpus) if vm.vcpus else "",
                    "Memory (MB)": str(vm.memory) if vm.memory else "",
                    "Disk": str(vm.disk) if vm.disk else "",
                    "IP Address": "",  # Will be populated from primary IP
                    "ID": str(vm.id),
                    "Device": "",
                    "Tenant Group": "",
                    "IPv4 Address": "",
                    "IPv6 Address": "",
                    "Description": vm.description or "",
                    "Comments": vm.comments or "",
                    "Config Template": "",
                    "Serial number": "",  # VMs typically don't have serial numbers
                    "Contacts": "",
                    "Tags": ", ".join([str(tag) for tag in vm.tags]) if vm.tags else "",
                    "Created": "",
                    "Last updated": "",
                    "Platform": str(vm.platform) if vm.platform else "",
                    "Interfaces": "0",
                    "Virtual Disks": "",
                    "Backup": "",
                    "DTAP state": "",
                    "Harddisk": "",
                    "open actions": "",
                    "Server Group": "",
                }

                # Handle Device field
                if hasattr(vm, "device") and vm.device:
                    vm_data["Device"] = str(vm.device)

                # Handle Tenant Group field
                if vm.tenant and hasattr(vm.tenant, "group") and vm.tenant.group:
                    vm_data["Tenant Group"] = str(vm.tenant.group)

                # Handle Config Template field
                if hasattr(vm, "config_template") and vm.config_template:
                    vm_data["Config Template"] = str(vm.config_template)

                # Handle Created field
                if vm.created:
                    if hasattr(vm.created, "isoformat"):
                        vm_data["Created"] = vm.created.isoformat()
                    else:
                        vm_data["Created"] = str(vm.created)

                # Handle Last updated field
                if vm.last_updated:
                    if hasattr(vm.last_updated, "isoformat"):
                        vm_data["Last updated"] = vm.last_updated.isoformat()
                    else:
                        vm_data["Last updated"] = str(vm.last_updated)

                # Handle Interfaces count - simplified to avoid API performance issues
                try:
                    # Check if VM has interfaces attribute directly
                    if hasattr(vm, "interfaces") and vm.interfaces is not None:
                        # Try to get count without fully loading all interfaces
                        vm_data["Interfaces"] = str(vm.interfaces.count() if hasattr(vm.interfaces, "count") else len(vm.interfaces))
                    else:
                        # Default to 0 if no interfaces info available
                        vm_data["Interfaces"] = "0"
                except Exception:
                    vm_data["Interfaces"] = "0"

                # Handle Contacts field via contact assignments
                vm_data["Contacts"] = get_vm_contacts(nb, vm)

                # Handle Custom Fields
                if hasattr(vm, "custom_fields") and vm.custom_fields:
                    custom_fields = vm.custom_fields

                    # Map custom fields to CSV columns using exact field names from NetBox
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

                    if custom_fields.get("Server_Group"):
                        vm_data["Server Group"] = str(custom_fields["Server_Group"])

                # Get primary IP address
                if vm.primary_ip4:
                    vm_data["IP Address"] = str(vm.primary_ip4).split("/")[0]
                    vm_data["IPv4 Address"] = str(vm.primary_ip4)
                elif vm.primary_ip6:
                    vm_data["IP Address"] = str(vm.primary_ip6).split("/")[0]
                    vm_data["IPv6 Address"] = str(vm.primary_ip6)

                vm_details[vm_id] = vm_data

                # Progress indicator
                if i % 50 == 0 or i == total_vms:
                    print(f"Progress: {i}/{total_vms} VMs processed")

        except Exception as e:
            extra = _req_err_details(e)
            print(f"Error fetching details for VM {vm_id}: {e}{extra}")

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

        print(f"CSV file updated successfully: {CSV_FILE}")

    except Exception as e:
        print(f"Error writing CSV file: {e}")

def main():
    """Main function"""
    print("Starting NetBox VM data synchronization...")

    # Connect to NetBox
    nb = connect_to_netbox()

    # Get VM metadata from NetBox
    netbox_metadata = get_vm_metadata(nb)
    if not netbox_metadata:
        print("No VMs found in NetBox or error occurred.")
        return

    # Read existing CSV data
    existing_data = read_existing_csv()

    # Identify changes
    new_vms, updated_vms, deleted_vms = identify_changes(netbox_metadata, existing_data)

    # Get details for new and updated VMs
    vms_to_fetch = new_vms + updated_vms
    vm_details = get_vm_details(nb, vms_to_fetch)

    # Write updated data to CSV
    write_csv_data(vm_details, existing_data, deleted_vms)

    print("Sync complete.")

if __name__ == "__main__":
    main()
