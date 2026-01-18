# Atlas Host Tools Specification

## Overview

Two new unified tools to reduce token usage and tool calls for common host lookups.

| Tool | Purpose | Data Sources | Use Case |
|------|---------|--------------|----------|
| `atlas_host_info` | Current state | NetBox + Zabbix + Commvault | "Tell me about X" |
| `atlas_host_context` | History & docs | Jira + Confluence + NetBox changelog | "What happened with X" |

## Tool 1: `atlas_host_info`

### Purpose
Single-call comprehensive host lookup combining identity, monitoring, and backup status.

### Input Parameters
```json
{
  "hostname": "vw785",           // Required: hostname to lookup
  "include_network_details": true // Optional: include full interface list
}
```

### Output Schema
```json
{
  "hostname": "vw785",
  "found": true,
  "source": "netbox",

  "identity": {
    "name": "vw785",
    "aliases": ["vm61"],           // From NetBox comments/custom fields
    "status": "active",
    "device_type": "Dell PowerEdge R340",
    "is_virtual": false,
    "description": "BFX Radius Node 1 - Production", // NEW: from NetBox
    "asset_tag": "SYS-AM8-0785",                     // NEW: from NetBox
    "serial_number": "ABC123XYZ",
    "tenant": "Systems Infrastructure",
    "platform": "Debian 12 (bookworm)"
  },

  "location": {
    "site": "Equinix AM8",
    "site_code": "am8",
    "rack": "0304",
    "position": "U12"
  },

  "network": {
    "primary_ip": "172.18.48.161/24",
    "interfaces": [                    // Only if include_network_details=true
      {
        "name": "bond0",
        "ip": "172.18.48.161/24",
        "vlan": null,
        "vrf": "default"
      },
      {
        "name": "bond0.50",
        "ip": "10.255.255.116/24",
        "vlan": 50,
        "vrf": "Enreach Offices"
      }
    ]
  },

  "monitoring": {
    "in_zabbix": false,
    "zabbix_host_id": null,
    "active_alerts": 0,
    "last_check": null,
    "status": "NOT_MONITORED"        // MONITORED | NOT_MONITORED | UNKNOWN
  },

  "backup": {
    "in_commvault": false,
    "client_name": null,
    "last_backup": null,
    "last_backup_status": null,
    "status": "NOT_PROTECTED"        // PROTECTED | NOT_PROTECTED | FAILED | UNKNOWN
  },

  "gaps": [                          // Auto-detected issues
    "No Zabbix monitoring configured",
    "No Commvault backup client found"
  ],

  "metadata": {
    "netbox_id": 1628,
    "netbox_url": "https://netbox.example.com/dcim/devices/1628/",
    "last_updated": "2026-01-17T19:21:35Z",
    "query_time_ms": 450
  }
}
```

### Implementation Logic

```python
async def atlas_host_info(hostname: str, include_network_details: bool = True) -> dict:
    """
    Combined host lookup - NetBox + Zabbix + Commvault in parallel.
    """
    result = {
        "hostname": hostname,
        "found": False,
        "gaps": []
    }

    # Step 1: NetBox lookup (required - source of truth)
    netbox_data = await netbox_search(hostname)

    if not netbox_data:
        # Try alias variations
        aliases = generate_aliases(hostname)  # vw785 -> [vm785, vw785.domain.com]
        for alias in aliases:
            netbox_data = await netbox_search(alias)
            if netbox_data:
                result["searched_alias"] = alias
                break

    if not netbox_data:
        return {"hostname": hostname, "found": False, "error": "Not found in NetBox"}

    result["found"] = True
    result["identity"] = extract_identity(netbox_data)  # Include description, asset_tag
    result["location"] = extract_location(netbox_data)
    result["network"] = extract_network(netbox_data, include_network_details)

    # Step 2: Parallel lookups for Zabbix and Commvault
    zabbix_task = zabbix_host_lookup(hostname)
    commvault_task = commvault_client_lookup(hostname)

    zabbix_result, commvault_result = await asyncio.gather(
        zabbix_task, commvault_task, return_exceptions=True
    )

    # Process Zabbix
    if isinstance(zabbix_result, Exception):
        result["monitoring"] = {"status": "UNKNOWN", "error": str(zabbix_result)}
    elif zabbix_result:
        result["monitoring"] = {
            "in_zabbix": True,
            "zabbix_host_id": zabbix_result["hostid"],
            "active_alerts": zabbix_result.get("alert_count", 0),
            "status": "MONITORED"
        }
    else:
        result["monitoring"] = {"in_zabbix": False, "status": "NOT_MONITORED"}
        result["gaps"].append("No Zabbix monitoring configured")

    # Process Commvault
    if isinstance(commvault_result, Exception):
        result["backup"] = {"status": "UNKNOWN", "error": str(commvault_result)}
    elif commvault_result:
        result["backup"] = {
            "in_commvault": True,
            "client_name": commvault_result["clientName"],
            "last_backup": commvault_result.get("lastBackup"),
            "status": "PROTECTED" if commvault_result.get("lastBackupStatus") == "Success" else "FAILED"
        }
    else:
        result["backup"] = {"in_commvault": False, "status": "NOT_PROTECTED"}
        result["gaps"].append("No Commvault backup client found")

    return result
```

### Alias Generation Logic

```python
def generate_aliases(hostname: str) -> list[str]:
    """Generate common hostname variations to try."""
    aliases = []

    # vw785 -> vm785
    if hostname.startswith("vw"):
        aliases.append("vm" + hostname[2:])

    # vm61 -> vw61
    if hostname.startswith("vm"):
        aliases.append("vw" + hostname[2:])

    # Short to FQDN
    if "." not in hostname:
        aliases.append(f"{hostname}.internal.domain.com")
        aliases.append(f"{hostname}.domain.com")

    # FQDN to short
    if "." in hostname:
        aliases.append(hostname.split(".")[0])

    # Leading zero variations: server-01 <-> server-1
    import re
    match = re.search(r'(\d+)$', hostname)
    if match:
        num = match.group(1)
        base = hostname[:-len(num)]
        if num.startswith("0"):
            aliases.append(base + num.lstrip("0"))
        else:
            aliases.append(base + num.zfill(2))

    return aliases
```

---

## Tool 2: `atlas_host_context`

### Purpose
Get historical context, tickets, and documentation for a host.

### Input Parameters
```json
{
  "hostname": "vw785",
  "ticket_months": 6,      // How far back to search Jira
  "include_docs": true     // Search Confluence for related docs
}
```

### Output Schema
```json
{
  "hostname": "vw785",

  "tickets": {
    "total_found": 5,
    "items": [
      {
        "key": "ESD-39031",
        "summary": "vm59 (vw785) – Unreachable via VLAN 50 and VLAN 544",
        "status": "Closed",
        "assignee": "Ilker Yayla",
        "created": "2025-11-04",
        "resolved": "2025-11-06",
        "priority": "High"
      }
    ]
  },

  "documentation": {
    "total_found": 2,
    "items": [
      {
        "title": "NL/AM8: 0304 Equipment overview",
        "space": "SPS",
        "url": "https://confluence.example.com/...",
        "relevance_score": 0.85
      }
    ]
  },

  "netbox_history": {
    "comments": "Replaced vm14 as BFX Radius Node 1 in Jan 2026",
    "custom_fields": {
      "service": "BFX Radius",
      "owner_team": "Mobile Infrastructure"
    },
    "recent_changes": [
      {
        "date": "2026-01-16",
        "user": "daniel",
        "action": "Updated primary IP"
      }
    ]
  },

  "related_hosts": [
    {
      "hostname": "vw831",
      "relationship": "mentioned_together",
      "context": "Switchport configuration"
    }
  ],

  "metadata": {
    "search_period": "2025-07-17 to 2026-01-17",
    "query_time_ms": 890
  }
}
```

### Implementation Logic

```python
async def atlas_host_context(
    hostname: str,
    ticket_months: int = 6,
    include_docs: bool = True
) -> dict:
    """
    Get historical context - Jira + Confluence + NetBox history.
    """
    result = {"hostname": hostname}

    # Calculate date range
    from_date = datetime.now() - timedelta(days=ticket_months * 30)

    # Parallel queries
    tasks = [
        jira_search_host(hostname, from_date),
        netbox_get_history(hostname)
    ]

    if include_docs:
        tasks.append(confluence_search_host(hostname))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Process Jira tickets
    jira_result = results[0]
    if not isinstance(jira_result, Exception):
        result["tickets"] = {
            "total_found": len(jira_result),
            "items": format_tickets(jira_result)
        }

    # Process NetBox history
    netbox_result = results[1]
    if not isinstance(netbox_result, Exception):
        result["netbox_history"] = netbox_result

    # Process Confluence docs
    if include_docs and len(results) > 2:
        confluence_result = results[2]
        if not isinstance(confluence_result, Exception):
            result["documentation"] = {
                "total_found": len(confluence_result),
                "items": format_docs(confluence_result)
            }

    # Extract related hosts from tickets
    result["related_hosts"] = extract_related_hosts(result.get("tickets", {}).get("items", []))

    return result
```

---

## Integration Notes

### Authentication Requirements

The unified host tools (`atlas_host_info`, `atlas_host_context`) require proper session authentication to make internal API calls. The authentication flow is:

```
AI Chat Request (with atlas_ui cookie)
    │
    ▼
ToolRegistry (forwards cookie in requests)
    │
    ▼
/atlas/host-info endpoint (receives cookie)
    │
    ▼
Internal calls to /netbox/search, /zabbix/*, /commvault/*
    (cookie forwarded via httpx client)
```

**Key implementation details:**

1. **Cookie extraction** (`ai_chat.py`):
   ```python
   session_cookie = request.cookies.get("atlas_ui")  # NOT "session"
   ```

2. **Cookie forwarding** (`registry.py`):
   ```python
   def _get_cookies(self) -> dict[str, str]:
       if self.session_cookie:
           return {"atlas_ui": self.session_cookie}  # Correct cookie name
       return {}
   ```

3. **Internal call forwarding** (`atlas_host.py`):
   ```python
   cookies = dict(request.cookies)  # Forward all cookies
   async with httpx.AsyncClient(base_url=base_url, cookies=cookies) as client:
       response = await client.get("/netbox/search", ...)
   ```

### Where to implement handlers

The tool definitions are in:
```
src/infrastructure_atlas/ai/tools/definitions.py
```

The handlers should be implemented in a new file:
```
src/infrastructure_atlas/ai/tools/handlers/host_tools.py
```

### Required API clients

- `NetBoxClient` - existing in `agents/netbox.py`
- `ZabbixClient` - existing in `agents/zabbix.py`
- `CommvaultClient` - needs to be created or imported
- `JiraClient` - existing in `agents/jira.py`
- `ConfluenceClient` - existing in `agents/confluence.py`

### Performance targets

| Metric | Target |
|--------|--------|
| `atlas_host_info` response time | < 2 seconds |
| `atlas_host_context` response time | < 5 seconds |
| Token savings vs multiple calls | 50-70% |

### Testing

Test cases should include:
1. Valid hostname found in all systems
2. Valid hostname missing from Zabbix/Commvault (gaps)
3. Hostname not found, alias found
4. Hostname not found anywhere
5. Partial failures (e.g., Commvault timeout)
