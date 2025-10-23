#!/usr/bin/env python3
"""Test bulk contact assignments fetching."""

import os
from dotenv import load_dotenv
from infrastructure_atlas.infrastructure.external.netbox_client import NetboxClient, NetboxClientConfig

# Load environment
load_dotenv()

# Create client
config = NetboxClientConfig(
    url=os.environ["NETBOX_URL"],
    token=os.environ["NETBOX_TOKEN"],
)
client = NetboxClient(config)

# Get first few VMs
print("Fetching first 10 VMs...")
vms = list(client.api.virtualization.virtual_machines.filter(limit=10))
vm_ids = [vm.id for vm in vms]
print(f"VM IDs: {vm_ids}")

# Get contact assignments endpoint
if hasattr(client.api, "tenancy"):
    ca_ep = client.api.tenancy.contact_assignments
    print("✓ Using tenancy.contact_assignments")
else:
    print("✗ No endpoint found")
    exit(1)

# Test 1: Bulk fetch all VMs
print("\n=== Test 1: Bulk fetch ALL virtualmachine contacts ===")
try:
    print("Filtering with object_type='virtualization.virtualmachine', limit=0")
    all_results = list(ca_ep.filter(object_type="virtualization.virtualmachine", limit=0))
    print(f"✓ Success! Found {len(all_results)} total assignments for all VMs")
    # Filter to our specific VMs
    our_assignments = [a for a in all_results if getattr(a, "object_id", None) in vm_ids]
    print(f"✓ {len(our_assignments)} assignments match our 10 VMs")
    for assignment in our_assignments:
        object_id = getattr(assignment, "object_id", None)
        contact = getattr(assignment, "contact", None)
        role = getattr(assignment, "role", None)
        c_name = getattr(contact, "name", None) if contact else None
        r_name = getattr(role, "name", None) if role else None
        print(f"  - VM ID {object_id}: {c_name} ({r_name})")
except Exception as e:
    print(f"✗ Failed: {type(e).__name__}: {e}")

# Test 2: Using object_id__in
print("\n=== Test 2: Using object_id__in with specific VM IDs ===")
try:
    params = {
        "object_type": "virtualization.virtualmachine",
        "object_id__in": vm_ids,
        "limit": 0
    }
    print(f"Params: {params}")
    results = list(ca_ep.filter(**params))
    print(f"✓ Success! Found {len(results)} assignments")
    for assignment in results:
        object_id = getattr(assignment, "object_id", None)
        contact = getattr(assignment, "contact", None)
        role = getattr(assignment, "role", None)
        c_name = getattr(contact, "name", None) if contact else None
        r_name = getattr(role, "name", None) if role else None
        print(f"  - VM ID {object_id}: {c_name} ({r_name})")
except Exception as e:
    print(f"✗ Failed: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

# Test 3: Individual queries
print("\n=== Test 3: Individual object_id queries ===")
for vm_id in vm_ids[:3]:  # Test first 3
    try:
        params = {
            "object_type": "virtualization.virtualmachine",
            "object_id": vm_id,
            "limit": 0
        }
        results = list(ca_ep.filter(**params))
        if results:
            contact = getattr(results[0], "contact", None)
            c_name = getattr(contact, "name", None) if contact else None
            print(f"  ✓ VM ID {vm_id}: {c_name}")
        else:
            print(f"  - VM ID {vm_id}: No contacts")
    except Exception as e:
        print(f"  ✗ VM ID {vm_id}: {type(e).__name__}: {e}")

print("\n=== Done ===")
