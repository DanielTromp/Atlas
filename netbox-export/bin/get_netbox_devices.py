import argparse
import csv
import os
from datetime import datetime
from pathlib import Path

from enreach_tools import backup_sync
from enreach_tools.env import apply_extra_headers, load_env, project_root, require_env
from enreach_tools.infrastructure.external import NetboxClient, NetboxClientConfig

# Note: file renamed from get_netbox_data.py to get_netbox_devices.py

# Load environment variables from central loader (.env at project root)
load_env()
require_env(["NETBOX_URL", "NETBOX_TOKEN"])

# Get NetBox URL and Token from environment variables
NETBOX_URL = os.getenv("NETBOX_URL")
NETBOX_TOKEN = os.getenv("NETBOX_TOKEN")

netbox_client = NetboxClient(NetboxClientConfig(url=NETBOX_URL, token=NETBOX_TOKEN))
nb = netbox_client.api

# Verbose debug control via env NETBOX_DEBUG=1|true
NETBOX_DEBUG = os.getenv("NETBOX_DEBUG", "").lower() in ("1", "true", "yes", "y")
PREVIEW_ATTR_LIMIT = 20


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
    """List wrapper providing an ``all`` method for compatibility."""

    def __iter__(self):  # keep typing happy for mypy later
        return super().__iter__()

    def all(self):
        return list(self)


class _AttrProxy:
    """Lightweight attribute accessor for dict payloads."""

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
def _dbg(msg: str):
    if NETBOX_DEBUG:
        print(f"[DEBUG] {msg}")

def _preview(obj):
    try:
        if obj is None:
            return "None"
        if isinstance(obj, dict):
            keys = list(obj.keys())
            return f"dict keys={keys}"
        attrs = [a for a in dir(obj) if not a.startswith("_")]
        return f"obj attrs={attrs[:PREVIEW_ATTR_LIMIT]}{'...' if len(attrs)>PREVIEW_ATTR_LIMIT else ''}"
    except Exception as e:
        return f"<preview-error {e}>"



def _req_err_details(exc) -> str:
    info = []
    try:
        req = getattr(exc, "req", None) or getattr(exc, "request", None)
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


def _norm_key(s: str) -> str:
    """Normalize a custom-field key for robust matching: lowercase, strip non-alnum."""
    try:
        return "".join(ch.lower() for ch in str(s) if ch.isalnum())
    except Exception:
        return str(s).lower()


def _cf_get(cf: dict, *candidates: str):
    """Get a custom field by trying multiple candidate names (robust to spaces/underscores/case).

    Returns a string representation; lists are joined by ", ".
    """
    if not isinstance(cf, dict) or not candidates:
        return ""
    # Build normalized lookup once
    lookup = { _norm_key(k): v for k, v in cf.items() }
    for cand in candidates:
        v = lookup.get(_norm_key(cand))
        if v is not None:
            try:
                if isinstance(v, list):
                    return ", ".join(str(x) for x in v)
                return str(v)
            except Exception:
                return str(v)
    return ""

def _get_ct_id(nb, app_label: str, model: str) -> int:
    """Get content type ID for the given app_label and model."""
    ct = nb.extras.content_types.get(app_label=app_label, model=model)
    if not ct:
        raise RuntimeError(f"ContentType {app_label}.{model} not found")
    _dbg(f"ContentType resolved: {app_label}.{model} -> id={getattr(ct, 'id', None)}")
    return ct.id

def _get_contact_assignments_endpoint(nb):
    """Get the contact assignments endpoint, handling different NetBox versions."""
    # NetBox >=3.6 uses 'contacts', older uses 'tenancy'
    if hasattr(nb, "contacts") and hasattr(nb.contacts, "contact_assignments"):
        _dbg("Using endpoint: contacts.contact_assignments")
        return nb.contacts.contact_assignments
    if hasattr(nb, "tenancy") and hasattr(nb.tenancy, "contact_assignments"):
        _dbg("Using endpoint: tenancy.contact_assignments")
        return nb.tenancy.contact_assignments
    raise RuntimeError("No contact_assignments endpoint found")

def get_device_contacts(nb, device):
    """Get contacts for a device using robust NetBox API filters across NB 3.x/4.x, with verbose debug."""
    try:
        _dbg(f"get_device_contacts(): device.id={getattr(device,'id',None)} name={getattr(device,'name',None)}")

        # Best-effort NetBox version print
        try:
            _dbg(f"NetBox API version: {getattr(nb, 'version', 'unknown')}")
        except Exception:
            pass

        # Determine contact-assignments endpoint (contacts or tenancy)
        try:
            ca_ep = _get_contact_assignments_endpoint(nb)
        except Exception as e:
            _dbg(f"No contact_assignments endpoint: {e}")
            return ""

        # Compute both CT IDs; 4.x uses object_type_id; older uses content_type_id
        ct_id = None
        try:
            ct_id = _get_ct_id(nb, "dcim", "device")
        except Exception as e:
            _dbg(f"Could not resolve ContentType id: {e}")
            ct_id = None

        assignments = []

        # Try filters in order of most recent NetBox first (v4+) then older fallbacks
        filter_attempts = []

        # v4+: object_type_id/object_type
        if ct_id is not None:
            filter_attempts.append({"object_type_id": ct_id, "object_id": device.id})
        filter_attempts.append({"object_type": "dcim.device", "object_id": device.id})

        # v3.x: content_type_id/content_type
        if ct_id is not None:
            filter_attempts.append({"content_type_id": ct_id, "object_id": device.id})
        filter_attempts.append({"content_type": "dcim.device", "object_id": device.id})

        _dbg(f"Filter attempts ({len(filter_attempts)}): " + " | ".join([str(p) for p in filter_attempts]))

        for i, params in enumerate(filter_attempts, 1):
            try:
                _dbg(f"Attempt {i}: filter {params}")
                result = list(ca_ep.filter(**params))
                _dbg(f"Attempt {i}: returned {len(result)} items")
                if result:
                    assignments = result
                    break
            except Exception as e:
                _dbg(f"Attempt {i} raised: {type(e).__name__}: {e}")
                continue

        if not assignments:
            _dbg("No contact assignments found for this device.")

        contacts = []
        for idx, a in enumerate(assignments):
            try:
                _dbg(f"Assignment[{idx}] preview: {_preview(getattr(a,'_values', getattr(a,'__dict__', a)))}")
            except Exception:
                pass

            contact = getattr(a, "contact", None)
            role = getattr(a, "role", None)

            _dbg(f"  contact raw: {_preview(contact)} | role raw: {_preview(role)}")

            # --- Resolve CONTACT name ---
            c_name = getattr(contact, "name", None)
            # dict form: may only have id/url/display in v4
            if not c_name and isinstance(contact, dict):
                c_name = contact.get("name") or contact.get("display")
                if not c_name and contact.get("id") and hasattr(nb, "contacts") and hasattr(nb.contacts, "contacts"):
                    try:
                        _dbg(f"  Fetching contact detail id={contact.get('id')}")
                        c_obj = nb.contacts.contacts.get(contact.get("id"))
                        if c_obj:
                            c_name = getattr(c_obj, "name", None) or getattr(c_obj, "display", None)
                    except Exception as e:
                        _dbg(f"  Contact detail fetch failed: {e}")

            # --- Resolve ROLE name ---
            r_name = getattr(role, "name", None)
            if not r_name and isinstance(role, dict):
                r_name = role.get("name") or role.get("display")
                if not r_name and role.get("id") and hasattr(nb, "contacts") and hasattr(nb.contacts, "contact_roles"):
                    try:
                        _dbg(f"  Fetching role detail id={role.get('id')}")
                        r_obj = nb.contacts.contact_roles.get(role.get("id"))
                        if r_obj:
                            r_name = getattr(r_obj, "name", None) or getattr(r_obj, "display", None)
                    except Exception as e:
                        _dbg(f"  Role detail fetch failed: {e}")

            _dbg(f"  Resolved: contact='{c_name}' role='{r_name}'")

            if c_name:
                contacts.append(f"{c_name} ({r_name})" if r_name else c_name)

        out = ", ".join(contacts) if contacts else ""
        _dbg(f"Final contacts string: '{out}'")
        return out

    except Exception as e:
        _dbg(f"get_device_contacts() error: {type(e).__name__}: {e}")
        # Fail closed; do not break the sync
        return ""


def get_full_device_data(client, device_id):
    """Fetches detailed data for a single device."""
    nb = client.api
    record = client.get_device(device_id)
    device = record.source or _AttrProxy(record.raw)
    custom_fields = record.custom_fields or {}

    last_updated_str = (
        record.last_updated.isoformat().replace("+00:00", "Z")
        if record.last_updated
        else str(getattr(device, "last_updated", "") or "")
    )

    return {
        "Name": record.name,
        "Status": record.status_label or "",
        "Tenant": record.tenant or "",
        "Site": record.site or "",
        "Location": record.location or "",
        "Rack": getattr(device.rack, "name", "") if getattr(device, "rack", None) else "",
        # New: Rack Position (U) with optional face prefix
        "Rack Position": (
            (f"{getattr(getattr(device, 'face', ''), 'label', getattr(device, 'face', ''))} {getattr(device, 'position', '')}").strip()
            if getattr(device, "position", None) not in (None, "") else ""
        ),
        "Role": record.role or "",
        "Manufacturer": record.manufacturer or "",
        "Type": record.model or "",
        "IP Address": record.primary_ip_best or "",
        "ID": record.id,
        "Tenant Group": record.tenant_group or "",
        "Serial number": record.serial or "",
        "Asset tag": record.asset_tag or "",
        "Region": record.region or "",
        "Site Group": record.site_group or "",
        "Parent Device": getattr(device.parent_device, "name", "") if getattr(device, "parent_device", None) else "",
        "Position (Device Bay)": getattr(device, "device_bay", ""),
        "Position": getattr(device, "position", ""),
        "Rack face": getattr(device, "face", ""),
        "Latitude": getattr(device, "latitude", ""),
        "Longitude": getattr(device, "longitude", ""),
        "Airflow": getattr(device, "airflow", ""),
        "IPv4 Address": record.primary_ip4 or "",
        "IPv6 Address": record.primary_ip6 or "",
        "OOB IP": record.oob_ip or "",
        "Cluster": record.cluster or "",
        "Virtual Chassis": getattr(device, "virtual_chassis", ""),
        "VC Position": getattr(device, "vc_position", ""),
        "VC Priority": getattr(device, "vc_priority", ""),
        "Description": record.description or getattr(device, "description", ""),
        "Config Template": getattr(device.config_template, "name", "") if getattr(device, "config_template", None) else "",
        "Comments": getattr(device, "comments", ""),
        "Contacts": get_device_contacts(nb, device),
        "Tags": ", ".join(record.tags),
        "Created": str(getattr(device, "created", "") or ""),
        "Last updated": last_updated_str,
        "Platform": getattr(device.platform, "name", "") if getattr(device, "platform", None) else "",
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
        "Console ports": getattr(device, "console_port_count", 0),
        "Console server ports": getattr(device, "console_server_port_count", 0),
        "Power ports": getattr(device, "power_port_count", 0),
        "Power outlets": getattr(device, "power_outlet_count", 0),
        "Interfaces": getattr(device, "interface_count", 0),
        "Front ports": getattr(device, "front_port_count", 0),
        "Rear ports": getattr(device, "rear_port_count", 0),
        "Device bays": getattr(device, "device_bay_count", 0),
        "Module bays": getattr(device, "module_bay_count", 0),
        "Inventory items": len(list(device.inventory_items.all())) if hasattr(device, "inventory_items") else 0,
    }


def sync_netbox_to_csv(force: bool = False):
    """Connects to NetBox, retrieves all devices, and incrementally updates a CSV file.
    """
    if not NETBOX_URL or not NETBOX_TOKEN:
        print("Error: NETBOX_URL and NETBOX_TOKEN must be set in the .env file.")
        return
    print("Starting NetBox Devices data synchronization...")

    try:
        apply_extra_headers(nb.http_session)

        print("Fetching device list from NetBox...")
        devices = netbox_client.list_devices(force_refresh=force)
        netbox_device_info = {str(d.id): _to_iso(d.last_updated) for d in devices}
        print(f"Found {len(netbox_device_info)} devices in NetBox.")

        # Resolve data directory relative to project root
        root = project_root()
        data_dir_env = os.getenv("NETBOX_DATA_DIR", "data")
        data_dir_path = Path(data_dir_env) if os.path.isabs(data_dir_env) else (root / data_dir_env)
        data_dir_path.mkdir(parents=True, exist_ok=True)
        csv_file_path = data_dir_path / "netbox_devices_export.csv"

        # 2. Read existing data from CSV
        existing_devices = {}
        if os.path.exists(csv_file_path):
            print("Reading existing CSV data...")
            with open(csv_file_path, newline="") as file:
                reader = csv.DictReader(file)
                for row in reader:
                    existing_devices[row["ID"]] = row
            print(f"Found {len(existing_devices)} devices in the CSV file.")

        # 3. Identify changes (or force full refresh)
        to_update = []
        to_add = []

        if force:
            print("Force refresh enabled: re-fetching all devices...")
            to_add = list(netbox_device_info.keys())
            to_update = []
        else:
            for device_id, last_updated_str in netbox_device_info.items():
                last_updated_dt = (
                    datetime.fromisoformat(last_updated_str.replace("Z", "+00:00"))
                    if last_updated_str
                    else datetime.min
                )

                if device_id not in existing_devices:
                    to_add.append(device_id)
                else:
                    csv_last_updated_str = existing_devices[device_id].get("Last updated")
                    if csv_last_updated_str:
                        csv_last_updated_dt = datetime.fromisoformat(csv_last_updated_str.replace("Z", "+00:00"))
                        if last_updated_dt > csv_last_updated_dt:
                            to_update.append(device_id)
                    else:
                        to_update.append(device_id)

        to_delete = {k for k in existing_devices if k not in netbox_device_info}

        print(f"Identified {len(to_add)} new devices.")
        print(f"Identified {len(to_update)} updated devices.")
        print(f"Identified {len(to_delete)} devices to delete.")

        _dbg(f"To add: {to_add}")
        _dbg(f"To update: {to_update}")
        _dbg(f"To delete: {sorted(list(to_delete))}")

        # 4. Fetch full data for new and updated devices
        updated_data = {}
        devices_to_fetch = to_add + to_update
        count = 0
        total_to_fetch = len(devices_to_fetch)
        if total_to_fetch > 0:
            print(f"Fetching details for {total_to_fetch} devices...")
            for device_id in devices_to_fetch:
                count += 1
                print(f"Progress: {count}/{total_to_fetch} devices processed")
                updated_data[device_id] = get_full_device_data(netbox_client, device_id)

        # 5. Update the device dictionary
        for device_id, data in updated_data.items():
            existing_devices[device_id] = data

        # 6. Remove deleted devices
        for device_id in to_delete:
            del existing_devices[device_id]

        # 7. Write back to CSV
        os.makedirs(data_dir_path, exist_ok=True)

        print("Writing updated data to CSV...")
        # Build a robust header list that includes all observed keys across rows,
        # preserving a canonical order derived from a sample device.
        headers = []
        if netbox_device_info:
            try:
                first_device_id = next(iter(netbox_device_info.keys()))
                headers = list(get_full_device_data(netbox_client, first_device_id).keys())
            except Exception:
                headers = []

        seen = set(headers)
        def _extend_headers_from_rows(rows_dict):
            for row in rows_dict.values():
                for k in row.keys():
                    if k not in seen:
                        headers.append(k)
                        seen.add(k)

        _extend_headers_from_rows(existing_devices)
        _extend_headers_from_rows(updated_data)

        # Ensure important fields are present even if empty in sample/legacy CSVs
        for must_have in [
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
        ]:
            if must_have not in seen:
                headers.append(must_have)
                seen.add(must_have)


        with open(csv_file_path, "w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=headers)
            writer.writeheader()
            writer.writerows(existing_devices.values())

        print("Sync complete.")

        try:
            backup_sync.sync_paths([csv_file_path], note="netbox_devices")
        except Exception:  # pragma: no cover - defensive logging
            pass
    except Exception as e:
        extra = _req_err_details(e)
        print(f"Error interacting with NetBox: {e}{extra}")

def main():
    parser = argparse.ArgumentParser(description="Export NetBox devices to CSV")
    parser.add_argument("--force", action="store_true", help="Re-fetch all devices and rewrite CSV")
    args = parser.parse_args()
    sync_netbox_to_csv(force=args.force)


if __name__ == "__main__":
    main()
