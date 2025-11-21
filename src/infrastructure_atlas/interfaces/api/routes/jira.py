"""Jira API routes."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

import requests
from fastapi import APIRouter, HTTPException, Query

from infrastructure_atlas.infrastructure.modules import get_module_registry

router = APIRouter(prefix="/jira", tags=["jira"])


# Module guard dependency
def require_jira_enabled():
    """Dependency to ensure Jira module is enabled."""
    registry = get_module_registry()
    try:
        registry.require_enabled("jira")
    except Exception as e:
        raise HTTPException(status_code=403, detail=f"Jira module is disabled: {e}")


# Helper functions
def _jira_cfg() -> dict[str, str]:
    """Return Atlassian (Jira) credentials.

    Preferred envs: ATLASSIAN_BASE_URL, ATLASSIAN_EMAIL, ATLASSIAN_API_TOKEN
    Backwards-compatible fallbacks: JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN
    """
    base = os.getenv("ATLASSIAN_BASE_URL", "").strip() or os.getenv("JIRA_BASE_URL", "").strip()
    email = os.getenv("ATLASSIAN_EMAIL", "").strip() or os.getenv("JIRA_EMAIL", "").strip()
    token = os.getenv("ATLASSIAN_API_TOKEN", "").strip() or os.getenv("JIRA_API_TOKEN", "").strip()
    return {"base": base, "email": email, "token": token}


def _jira_configured() -> bool:
    """Check if Jira is configured."""
    cfg = _jira_cfg()
    return bool(cfg["base"] and cfg["email"] and cfg["token"])


def _jira_session() -> tuple[requests.Session, str]:
    """Create authenticated Jira session."""
    cfg = _jira_cfg()
    if not (cfg["base"] and cfg["email"] and cfg["token"]):
        raise HTTPException(
            status_code=400,
            detail="Jira not configured: set ATLASSIAN_BASE_URL, ATLASSIAN_EMAIL, ATLASSIAN_API_TOKEN in .env",
        )
    sess = requests.Session()
    sess.auth = (cfg["email"], cfg["token"])  # Basic auth for Jira Cloud
    sess.headers.update({"Accept": "application/json"})
    base = cfg["base"].rstrip("/")
    return sess, base


def _jira_build_jql(
    q: str | None = None,
    project: str | None = None,
    status: str | None = None,
    assignee: str | None = None,
    priority: str | None = None,
    issuetype: str | None = None,
    updated: str | None = None,
    team: str | None = None,
    only_open: bool = True,
) -> str:
    """Build JQL query from filters."""
    parts: list[str] = []
    # Only open maps better via statusCategory != Done (workflow agnostic)
    if only_open:
        parts.append("statusCategory != Done")
    if project:
        # Accept both key and name
        p = project.strip()
        if p:
            if any(ch.isspace() for ch in p) or not p.isalnum():
                parts.append(f'project = "{p}"')
            else:
                parts.append(f"project = {p}")
    if status:
        s = status.strip()
        if s:
            # Allow comma separated
            if "," in s:
                vals = ",".join([f'"{v.strip()}"' for v in s.split(",") if v.strip()])
                if vals:
                    parts.append(f"status in ({vals})")
            else:
                parts.append(f'status = "{s}"')
    if assignee:
        a = assignee.strip()
        if a:
            parts.append(f'assignee = "{a}"')
    if priority:
        pr = priority.strip()
        if pr:
            if "," in pr:
                vals = ",".join([f'"{v.strip()}"' for v in pr.split(",") if v.strip()])
                if vals:
                    parts.append(f"priority in ({vals})")
            else:
                parts.append(f'priority = "{pr}"')
    if issuetype:
        it = issuetype.strip()
        if it:
            parts.append(f'issuetype = "{it}"')
    # Custom field: Team (Service Desk) -> cf[10575]
    if team:
        tv = team.strip()
        if tv:
            if "," in tv:
                vals = ",".join([f'"{v.strip()}"' for v in tv.split(",") if v.strip()])
                if vals:
                    parts.append(f"cf[10575] in ({vals})")
            else:
                parts.append(f'cf[10575] = "{tv}"')
    if updated:
        up = updated.strip()
        if up:
            # Accept absolute date (YYYY-MM-DD) or relative (-7d / -4w)
            parts.append(f"updated >= {up}")
    # Jira /search/jql requires bounded queries; if user provided no limiting filters,
    # apply a safe default of last 30 days to avoid 400 errors.
    if not any(
        [project, status, assignee, priority, issuetype, team, (updated and updated.strip()), (q and q.strip())]
    ):
        parts.append("updated >= -30d")
    if q and q.strip():
        # text ~ search across summary, description, comments (Cloud behavior)
        # Escape quotes in q
        qq = q.replace('"', '\\"')
        parts.append(f'text ~ "{qq}"')
    jql = " AND ".join(parts) if parts else "order by updated desc"
    if "order by" not in jql.lower():
        jql += " ORDER BY updated DESC"
    return jql


# API Routes

@router.get("/config")
def jira_config():
    """Return Jira configuration status."""
    require_jira_enabled()
    cfg = _jira_cfg()
    return {"configured": _jira_configured(), "base_url": cfg.get("base")}


@router.get("/search")
def jira_search(
    q: str | None = Query(None, description="Free-text search (text ~ '...')"),
    jql: str | None = Query(None, description="Explicit JQL overrides other filters"),
    project: str | None = Query(None),
    status: str | None = Query(None),
    assignee: str | None = Query(None),
    priority: str | None = Query(None),
    issuetype: str | None = Query(None),
    updated: str | None = Query(None, description=">= constraint, e.g. -14d or 2025-01-01"),
    team: str | None = Query(None, description='Team (Servicedesk), e.g. "Systems Infrastructure"'),
    only_open: int = Query(1, ge=0, le=1),
    max_results: int = Query(50, ge=1, le=200),
):
    """Search Jira issues with JQL filters."""
    require_jira_enabled()
    sess, base = _jira_session()
    # Build JQL
    jql_str = (
        jql.strip()
        if jql and jql.strip()
        else _jira_build_jql(
            q=q,
            project=project,
            status=status,
            assignee=assignee,
            priority=priority,
            issuetype=issuetype,
            updated=updated,
            team=team,
            only_open=bool(only_open),
        )
    )
    fields = [
        "key",
        "summary",
        "status",
        "assignee",
        "priority",
        "updated",
        "created",
        "issuetype",
        "project",
    ]

    # Use the new /search/jql endpoint with GET + query params (legacy /search is removed)
    data: dict[str, Any] | None = None
    used_endpoint = ""
    try:
        url_jql = f"{base}/rest/api/3/search/jql"
        params = {
            "jql": jql_str,
            "startAt": 0,
            "maxResults": int(max_results),
            "fields": ",".join(fields),
        }
        r = sess.get(url_jql, params=params, timeout=60)
        if r.status_code == 401:
            raise HTTPException(status_code=401, detail="Unauthorized: check ATLASSIAN_EMAIL/ATLASSIAN_API_TOKEN")
        if r.status_code == 403:
            raise HTTPException(status_code=403, detail="Forbidden: missing permissions for this JQL/fields")
        if r.status_code == 400:
            # Jira may return a generic 400 for unbounded queries; surface detail
            raise HTTPException(status_code=400, detail=r.text or "Bad request to Jira /search/jql")
        r.raise_for_status()
        data = r.json()
        used_endpoint = "/rest/api/3/search/jql (GET)"
    except HTTPException:
        raise
    except requests.HTTPError as ex:
        msg = getattr(ex.response, "text", "")
        raise HTTPException(status_code=502, detail=f"Jira /search/jql error: {ex} {msg[:300]}")
    except Exception as ex:
        raise HTTPException(status_code=502, detail=f"Jira /search/jql error: {ex}")

    # Normalize issues list from either shape
    issues = []
    if isinstance(data, dict):
        if isinstance(data.get("issues"), list):
            issues = data.get("issues")
        elif isinstance(data.get("results"), list) and data["results"] and isinstance(data["results"][0], dict):
            issues = data["results"][0].get("issues", [])
    out: list[dict[str, Any]] = []
    for it in issues:
        if not isinstance(it, Mapping):
            continue
        k = str(it.get("key") or "")
        fields = it.get("fields")
        f = fields if isinstance(fields, Mapping) else {}
        out.append(
            {
                "key": k,
                "summary": str(f.get("summary") or ""),
                "status": str((f.get("status") or {}).get("name") or ""),
                "assignee": str((f.get("assignee") or {}).get("displayName") or ""),
                "priority": str((f.get("priority") or {}).get("name") or ""),
                "issuetype": str((f.get("issuetype") or {}).get("name") or ""),
                "project": (
                    str((f.get("project") or {}).get("key") or "")
                    or str((f.get("project") or {}).get("name") or "")
                ),
                "updated": str(f.get("updated") or ""),
                "created": str(f.get("created") or ""),
                "url": f"{base}/browse/{k}" if k else "",
            }
        )
    total = 0
    if isinstance(data, dict):
        # New endpoint may not return 'total'; compute from page or use provided
        total = int(data.get("total", 0) or 0)
        if not total and isinstance(data.get("isLast"), bool):
            total = len(out)
        if (
            not total
            and isinstance(data.get("results"), list)
            and data["results"]
            and isinstance(data["results"][0], dict)
        ):
            total = int(data["results"][0].get("total", 0) or 0)
        if not total:
            total = len(out)
    else:
        total = len(out)
    return {"total": total, "issues": out, "jql": jql_str, "endpoint": used_endpoint}
