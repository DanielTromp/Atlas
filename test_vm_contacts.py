#!/usr/bin/env python3
"""Test script to debug VM contact assignments."""

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

# Get the VM
print("Fetching VM api-prod4...")
vms = list(client.api.virtualization.virtual_machines.filter(name="api-prod4"))
if not vms:
    print("VM not found!")
    exit(1)

vm = vms[0]
print(f"Found VM: {vm.name} (ID: {vm.id})")

# Try different ways to get contact assignments
print("\n=== Attempting to fetch contact assignments ===")

# Try to get contact assignments endpoint
try:
    if hasattr(client.api, "contacts"):
        ca_ep = client.api.contacts.contact_assignments
        print("✓ Found contacts.contact_assignments endpoint")
    elif hasattr(client.api, "tenancy"):
        ca_ep = client.api.tenancy.contact_assignments
        print("✓ Found tenancy.contact_assignments endpoint")
    else:
        print("✗ No contact_assignments endpoint found")
        exit(1)
except Exception as e:
    print(f"✗ Error accessing endpoint: {e}")
    exit(1)

# Try to get content type ID
print("\n=== Getting content type ===")
try:
    ct = client.api.extras.content_types.get(app_label="virtualization", model="virtualmachine")
    if ct:
        print(f"✓ Content Type ID: {ct.id}")
        ct_id = ct.id
    else:
        print("✗ Content type not found")
        ct_id = None
except Exception as e:
    print(f"✗ Error getting content type: {e}")
    ct_id = None

# Try different filter approaches
filter_attempts = []
if ct_id is not None:
    filter_attempts.append(("object_type_id", {"object_type_id": ct_id, "object_id": vm.id}))
filter_attempts.append(("object_type string", {"object_type": "virtualization.virtualmachine", "object_id": vm.id}))
if ct_id is not None:
    filter_attempts.append(("content_type_id", {"content_type_id": ct_id, "object_id": vm.id}))
filter_attempts.append(("content_type string", {"content_type": "virtualization.virtualmachine", "object_id": vm.id}))

print("\n=== Trying different filter methods ===")
for name, params in filter_attempts:
    print(f"\nAttempt: {name}")
    print(f"Params: {params}")
    try:
        results = list(ca_ep.filter(**params))
        print(f"✓ Success! Found {len(results)} assignments")
        for assignment in results:
            contact = getattr(assignment, "contact", None)
            role = getattr(assignment, "role", None)
            c_name = getattr(contact, "name", None) if contact else None
            r_name = getattr(role, "name", None) if role else None
            print(f"  - Contact: {c_name} ({r_name})")
        if results:
            break
    except Exception as e:
        print(f"✗ Failed: {type(e).__name__}: {e}")

print("\n=== Done ===")
