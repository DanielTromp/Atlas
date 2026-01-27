"""Unified host lookup API endpoints for efficient AI tool calls.

These endpoints combine data from multiple sources (NetBox, Zabbix, Commvault, Jira)
into single responses, reducing the number of tool calls needed.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query, Request

from infrastructure_atlas.infrastructure.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/atlas", tags=["atlas-host"])


def generate_hostname_aliases(hostname: str) -> list[str]:
    """Generate common hostname variations to try.

    Examples:
        vw785 -> [vm785]
        vm61 -> [vw61]
        server-01 -> [server-1]
        server.domain.com -> [server]
    """
    aliases = []
    hostname_lower = hostname.lower().strip()

    # vw -> vm conversion
    if hostname_lower.startswith("vw"):
        aliases.append("vm" + hostname_lower[2:])

    # vm -> vw conversion
    if hostname_lower.startswith("vm"):
        aliases.append("vw" + hostname_lower[2:])

    # FQDN to short hostname
    if "." in hostname_lower:
        aliases.append(hostname_lower.split(".")[0])

    # Leading zero variations: server-01 <-> server-1
    match = re.search(r'(\d+)$', hostname_lower)
    if match:
        num = match.group(1)
        base = hostname_lower[:-len(num)]
        if num.startswith("0"):
            aliases.append(base + num.lstrip("0"))
        elif len(num) == 1:
            aliases.append(base + num.zfill(2))

    return aliases


async def fetch_netbox_data(hostname: str, client) -> dict[str, Any] | None:
    """Fetch device/VM data from NetBox.

    The /netbox/search endpoint returns {columns, rows, total} structure.
    Each row has both display fields (Name, Status) and original fields (name, description).

    Strategy: Search devices first, then VMs. Skip IP addresses to avoid false matches
    where IP objects have the hostname in their description/name.
    """
    hostname_lower = hostname.lower().strip()

    # Try devices first (most common for hostnames like vw785), then VMs
    for dataset in ["devices", "vms"]:
        try:
            logger.debug(f"NetBox lookup for '{hostname}' in dataset '{dataset}'")
            response = await client.get(
                "/netbox/search",
                params={"q": hostname, "limit": 20, "dataset": dataset}
            )

            if response.status_code != 200:
                logger.warning(f"NetBox search failed for '{hostname}' in {dataset}: status {response.status_code}")
                continue

            data = response.json()
            rows = data.get("rows", [])
            logger.info(f"NetBox search for '{hostname}' in {dataset} returned {len(rows)} rows")

            if not rows:
                continue

            # Priority 1: Exact match on name
            for row in rows:
                name = (row.get("name") or row.get("Name") or "").lower()
                if name == hostname_lower:
                    logger.info(f"NetBox exact match found for '{hostname}': {row.get('name')} ({dataset})")
                    return row

            # Priority 2: Partial match (hostname contained in name or vice versa)
            for row in rows:
                name = (row.get("name") or row.get("Name") or "").lower()
                if hostname_lower in name or name in hostname_lower:
                    logger.info(f"NetBox partial match found for '{hostname}': {row.get('name')} ({dataset})")
                    return row

            # Priority 3: Return first result from this dataset
            logger.info(f"NetBox no exact/partial match, returning first {dataset} result: {rows[0].get('name')}")
            return rows[0]

        except Exception as e:
            logger.warning(f"NetBox lookup failed for '{hostname}' in {dataset}: {e}")
            continue

    # No results found in any dataset
    logger.info(f"NetBox search for '{hostname}' returned no matching devices or VMs")
    return None


async def fetch_zabbix_status(hostname: str, client) -> dict[str, Any]:
    """Fetch monitoring status from Zabbix."""
    result = {
        "in_zabbix": False,
        "zabbix_host_id": None,
        "active_alerts": 0,
        "status": "UNKNOWN"
    }
    try:
        # Search for host
        response = await client.get(
            "/zabbix/host/search",
            params={"name": hostname, "limit": 5}
        )
        if response.status_code == 200:
            data = response.json()
            hosts = data.get("hosts", [])
            for host in hosts:
                if host.get("host", "").lower() == hostname.lower():
                    result["in_zabbix"] = True
                    result["zabbix_host_id"] = host.get("hostid")
                    result["status"] = "MONITORED"
                    break

            if not result["in_zabbix"] and hosts:
                # Check partial match
                result["in_zabbix"] = True
                result["zabbix_host_id"] = hosts[0].get("hostid")
                result["status"] = "MONITORED"

        # Get active alerts if host found
        if result["in_zabbix"]:
            alerts_response = await client.get(
                "/zabbix/problems",
                params={"limit": 100}
            )
            if alerts_response.status_code == 200:
                alerts_data = alerts_response.json()
                problems = alerts_data.get("items", [])
                # Count alerts for this host
                count = sum(
                    1 for p in problems
                    if hostname.lower() in str(p.get("host", "")).lower()
                )
                result["active_alerts"] = count

    except Exception as e:
        logger.warning(f"Zabbix lookup failed for {hostname}: {e}")
        result["status"] = "ERROR"
        result["error"] = str(e)

    if not result["in_zabbix"] and result["status"] != "ERROR":
        result["status"] = "NOT_MONITORED"

    return result


async def fetch_commvault_status(hostname: str, client) -> dict[str, Any]:
    """Fetch backup status from Commvault."""
    result = {
        "in_commvault": False,
        "client_name": None,
        "last_backup": None,
        "last_backup_status": None,
        "status": "UNKNOWN"
    }
    try:
        response = await client.get(
            "/commvault/backup-status",
            params={"hostname": hostname, "hours": 168, "limit": 10}
        )
        if response.status_code == 200:
            data = response.json()
            if data.get("client"):
                result["in_commvault"] = True
                result["client_name"] = data.get("client", {}).get("name")

                jobs = data.get("jobs", [])
                if jobs:
                    latest = jobs[0]
                    result["last_backup"] = latest.get("end_time")
                    result["last_backup_status"] = latest.get("status")

                    if latest.get("status") == "Completed":
                        result["status"] = "PROTECTED"
                    else:
                        result["status"] = "FAILED"
                else:
                    result["status"] = "PROTECTED"  # Client exists but no recent jobs
            else:
                result["status"] = "NOT_PROTECTED"

    except Exception as e:
        logger.warning(f"Commvault lookup failed for {hostname}: {e}")
        result["status"] = "ERROR"
        result["error"] = str(e)

    if not result["in_commvault"] and result["status"] not in ("ERROR",):
        result["status"] = "NOT_PROTECTED"

    return result


async def fetch_jira_tickets(hostname: str, months: int, client) -> list[dict[str, Any]]:
    """Fetch related Jira tickets."""
    tickets = []
    try:
        response = await client.get(
            "/jira/search",
            params={"q": hostname, "max": 20}
        )
        if response.status_code == 200:
            data = response.json()
            issues = data.get("issues", [])

            # Filter by date if needed
            cutoff = datetime.now() - timedelta(days=months * 30)

            for issue in issues:
                created_str = issue.get("created", "")
                try:
                    # Parse ISO date
                    if created_str:
                        created = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                        if created.replace(tzinfo=None) < cutoff:
                            continue
                except Exception:
                    pass

                tickets.append({
                    "key": issue.get("key"),
                    "summary": issue.get("summary"),
                    "status": issue.get("status"),
                    "assignee": issue.get("assignee"),
                    "created": issue.get("created"),
                    "priority": issue.get("priority"),
                })

    except Exception as e:
        logger.warning(f"Jira search failed for {hostname}: {e}")

    return tickets


async def fetch_confluence_docs(hostname: str, client) -> list[dict[str, Any]]:
    """Fetch related Confluence documentation."""
    docs = []
    try:
        response = await client.post(
            "/confluence-rag/search",
            json={"query": hostname, "top_k": 5}
        )
        if response.status_code == 200:
            data = response.json()
            results = data.get("results", [])

            for result in results:
                docs.append({
                    "title": result.get("title"),
                    "space": result.get("space_key"),
                    "url": result.get("url"),
                    "relevance_score": result.get("score", 0),
                })

    except Exception as e:
        logger.warning(f"Confluence search failed for {hostname}: {e}")

    return docs


@router.get("/host-info")
async def get_host_info(
    request: Request,
    hostname: str = Query(..., description="Hostname to lookup"),
    include_network_details: bool = Query(True, description="Include network interface details"),
):
    """Get comprehensive host information in a single call.

    Combines data from:
    - NetBox: identity, location, IPs, description, asset_tag
    - Zabbix: monitoring status, active alerts
    - Commvault: backup status

    Automatically tries hostname aliases if primary lookup fails.
    """
    import httpx

    # Create internal client for API calls
    base_url = str(request.base_url).rstrip("/")
    cookies = dict(request.cookies)

    # Debug: log if session cookie is present
    has_session = "session" in cookies
    logger.info(f"atlas_host_info: base_url={base_url}, has_session_cookie={has_session}, cookie_keys={list(cookies.keys())}")

    async with httpx.AsyncClient(
        base_url=base_url,
        cookies=cookies,
        timeout=30.0,
    ) as client:

        # Step 1: NetBox lookup (source of truth)
        logger.info(f"atlas_host_info: Looking up hostname '{hostname}'")
        netbox_data = await fetch_netbox_data(hostname, client)
        searched_alias = None

        # Try aliases if not found
        if not netbox_data:
            aliases = generate_hostname_aliases(hostname)
            logger.info(f"atlas_host_info: Primary lookup failed, trying aliases: {aliases}")
            for alias in aliases:
                netbox_data = await fetch_netbox_data(alias, client)
                if netbox_data:
                    searched_alias = alias
                    logger.info(f"atlas_host_info: Found via alias '{alias}'")
                    break

        if not netbox_data:
            aliases = generate_hostname_aliases(hostname)
            logger.warning(f"atlas_host_info: Host '{hostname}' not found in NetBox (tried aliases: {aliases})")
            return {
                "hostname": hostname,
                "found": False,
                "error": "Not found in NetBox",
                "aliases_tried": aliases,
                "suggestion": f"Try searching directly in NetBox UI, or check if the hostname uses a different naming pattern.",
            }

        # Step 2: Parallel lookups for Zabbix and Commvault
        lookup_hostname = searched_alias or hostname

        zabbix_task = fetch_zabbix_status(lookup_hostname, client)
        commvault_task = fetch_commvault_status(lookup_hostname, client)

        zabbix_result, commvault_result = await asyncio.gather(
            zabbix_task, commvault_task, return_exceptions=True
        )

        # Handle exceptions
        if isinstance(zabbix_result, Exception):
            zabbix_result = {"status": "ERROR", "error": str(zabbix_result)}
        if isinstance(commvault_result, Exception):
            commvault_result = {"status": "ERROR", "error": str(commvault_result)}

        # Build response
        gaps = []
        if not zabbix_result.get("in_zabbix"):
            gaps.append("No Zabbix monitoring configured")
        if not commvault_result.get("in_commvault"):
            gaps.append("No Commvault backup client found")

        # Helper to get field with fallback (NetBox returns both display and original fields)
        def get_field(primary: str, fallback: str = "", default: str = "") -> str:
            return netbox_data.get(primary) or netbox_data.get(fallback) or default

        # Determine if this is a virtual machine
        device_type = get_field("type", "Type", "")
        is_virtual = device_type == "virtual_machine" or device_type == "vm"

        result = {
            "hostname": hostname,
            "found": True,
            "searched_alias": searched_alias,

            "identity": {
                "name": get_field("name", "Name"),
                "status": get_field("Status", "status"),
                "device_type": get_field("Device Type", "type"),
                "is_virtual": is_virtual,
                "description": get_field("description", "Description"),
                "asset_tag": get_field("asset_tag", "Asset Tag"),
                "serial_number": get_field("Serial", "serial"),
                "tenant": get_field("Tenant", "tenant"),
                "platform": get_field("Platform", "platform"),
                "role": get_field("Role", "role"),
                "cluster": get_field("Cluster", "cluster") if is_virtual else None,
                "comments": get_field("comments", "Comments") if is_virtual else None,
            },

            "location": {
                "site": get_field("Site", "site"),
                "rack": get_field("Rack", "rack"),
                "position": get_field("Position", "position"),
            },

            "network": {
                "primary_ip": get_field("Primary IP", "primary_ip"),
                "oob_ip": get_field("Out-of-band IP", "oob_ip"),
            },

            "monitoring": zabbix_result,
            "backup": commvault_result,
            "gaps": gaps,

            "metadata": {
                "netbox_id": netbox_data.get("id"),
                "netbox_url": netbox_data.get("url") or netbox_data.get("ui_path"),
            },
        }

        # Add network details if requested
        if include_network_details:
            interfaces = netbox_data.get("interfaces", [])
            if not interfaces:
                # Try to get IP addresses as fallback
                ips = netbox_data.get("ip_addresses", [])
                if isinstance(ips, list):
                    result["network"]["interfaces"] = [
                        {"ip": ip.get("address"), "vrf": ip.get("vrf")}
                        for ip in ips
                    ]
            else:
                result["network"]["interfaces"] = interfaces

        return result


@router.get("/host-context")
async def get_host_context(
    request: Request,
    hostname: str = Query(..., description="Hostname to get context for"),
    ticket_months: int = Query(6, description="Months of ticket history to include"),
    include_docs: bool = Query(True, description="Include related documentation"),
):
    """Get historical context and documentation for a host.

    Combines data from:
    - Jira: recent tickets mentioning this host
    - Confluence: related documentation
    """
    import httpx

    base_url = str(request.base_url).rstrip("/")
    cookies = dict(request.cookies)

    async with httpx.AsyncClient(
        base_url=base_url,
        cookies=cookies,
        timeout=30.0,
    ) as client:

        # Parallel lookups
        tasks = [fetch_jira_tickets(hostname, ticket_months, client)]
        if include_docs:
            tasks.append(fetch_confluence_docs(hostname, client))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process tickets
        tickets = results[0] if not isinstance(results[0], Exception) else []

        # Process docs
        docs = []
        if include_docs and len(results) > 1:
            docs = results[1] if not isinstance(results[1], Exception) else []

        # Extract related hosts from tickets (mentioned together)
        related_hosts = []
        hostname_pattern = re.compile(r'\b(v[wm]\d+|vm\d+)\b', re.IGNORECASE)
        seen_hosts = {hostname.lower()}

        for ticket in tickets:
            summary = ticket.get("summary", "")
            matches = hostname_pattern.findall(summary)
            for match in matches:
                if match.lower() not in seen_hosts:
                    seen_hosts.add(match.lower())
                    related_hosts.append({
                        "hostname": match,
                        "relationship": "mentioned_together",
                        "context": f"In ticket {ticket.get('key')}",
                    })

        return {
            "hostname": hostname,

            "tickets": {
                "total_found": len(tickets),
                "items": tickets[:20],  # Limit to 20
            },

            "documentation": {
                "total_found": len(docs),
                "items": docs,
            },

            "related_hosts": related_hosts[:10],  # Limit to 10

            "metadata": {
                "search_period": f"{ticket_months} months",
                "include_docs": include_docs,
            },
        }
