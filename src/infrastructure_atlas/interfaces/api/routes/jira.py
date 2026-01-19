"""Jira API routes."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

import requests
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

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


def _resolve_assignee(sess: requests.Session, base: str, assignee: str, project: str) -> str | None:
    """Resolve a username/display name/email to a Jira account ID.

    Uses the project-specific assignable user search to only return users
    who can actually be assigned issues in that project.

    Args:
        sess: Authenticated Jira session
        base: Jira base URL
        assignee: Username, display name, email, or account ID
        project: Project key (for assignable user filtering)

    Returns:
        Account ID if found, None otherwise
    """
    # If it already looks like an account ID (contains colon), use it directly
    if ":" in assignee:
        return assignee

    # Search for assignable users in the project
    url = f"{base}/rest/api/3/user/assignable/search"
    params = {"query": assignee, "project": project, "maxResults": 10}

    try:
        r = sess.get(url, params=params, timeout=15)
        r.raise_for_status()
        users = r.json()

        if not users:
            return None

        # Try exact match first (case-insensitive)
        assignee_lower = assignee.lower()
        for user in users:
            display_name = (user.get("displayName") or "").lower()
            email = (user.get("emailAddress") or "").lower()
            if display_name == assignee_lower or email == assignee_lower:
                return user.get("accountId")
            # Check if query matches username portion of email
            if email and assignee_lower in email.split("@")[0]:
                return user.get("accountId")

        # Return first result if no exact match
        return users[0].get("accountId")
    except Exception:
        return None


def _get_project_issue_types(sess: requests.Session, base: str, project: str) -> list[str]:
    """Get valid issue type names for a project.

    Args:
        sess: Authenticated Jira session
        base: Jira base URL
        project: Project key

    Returns:
        List of valid issue type names
    """
    url = f"{base}/rest/api/3/issue/createmeta/{project}/issuetypes"

    try:
        r = sess.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
        return [it.get("name", "") for it in data.get("issueTypes", []) if it.get("name")]
    except Exception:
        return []


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


@router.get("/issue/{key}")
def get_issue(key: str):
    """Get a single Jira issue by key."""
    require_jira_enabled()
    sess, base = _jira_session()

    url = f"{base}/rest/api/3/issue/{key}"
    fields = [
        "key", "summary", "status", "assignee", "priority", "updated", "created",
        "issuetype", "project", "description", "labels", "comment"
    ]

    try:
        r = sess.get(url, params={"fields": ",".join(fields)}, timeout=30)
        if r.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Issue {key} not found")
        r.raise_for_status()
        data = r.json()

        f = data.get("fields", {})
        return {
            "key": data.get("key", ""),
            "summary": f.get("summary", ""),
            "status": (f.get("status") or {}).get("name", ""),
            "assignee": (f.get("assignee") or {}).get("displayName", ""),
            "assignee_account_id": (f.get("assignee") or {}).get("accountId", ""),
            "priority": (f.get("priority") or {}).get("name", ""),
            "issuetype": (f.get("issuetype") or {}).get("name", ""),
            "project": (f.get("project") or {}).get("key", ""),
            "labels": f.get("labels", []),
            "updated": f.get("updated", ""),
            "created": f.get("created", ""),
            "url": f"{base}/browse/{key}",
        }
    except requests.HTTPError as ex:
        raise HTTPException(status_code=ex.response.status_code, detail=str(ex))
    except Exception as ex:
        raise HTTPException(status_code=502, detail=f"Jira error: {ex}")


# Issue Models
class CreateIssueRequest(BaseModel):
    """Request to create a Jira issue."""
    project_key: str
    issue_type: str = "Task"
    summary: str
    description: str | None = None
    priority: str | None = None
    assignee: str | None = None  # Account ID or email
    labels: list[str] | None = None
    linked_issues: list[dict[str, str]] | None = None  # [{issue_key, link_type}]
    custom_fields: dict[str, Any] | None = None


class UpdateIssueRequest(BaseModel):
    """Request to update a Jira issue."""
    summary: str | None = None
    description: str | None = None
    priority: str | None = None
    assignee: str | None = None
    labels: list[str] | None = None
    custom_fields: dict[str, Any] | None = None


class AddCommentRequest(BaseModel):
    """Request to add a comment to a Jira issue."""
    body: str


@router.post("/issues")
def create_issue(req: CreateIssueRequest):
    """Create a new Jira issue."""
    require_jira_enabled()
    sess, base = _jira_session()

    # Validate issue type exists in project
    valid_types = _get_project_issue_types(sess, base, req.project_key)
    if valid_types and req.issue_type not in valid_types:
        # Try case-insensitive match
        issue_type_lower = req.issue_type.lower()
        matched = next((t for t in valid_types if t.lower() == issue_type_lower), None)
        if matched:
            req.issue_type = matched
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid issue type '{req.issue_type}' for project {req.project_key}. "
                       f"Valid types: {', '.join(valid_types)}"
            )

    # Resolve assignee to account ID if provided
    resolved_assignee = None
    if req.assignee:
        resolved_assignee = _resolve_assignee(sess, base, req.assignee, req.project_key)
        if not resolved_assignee:
            raise HTTPException(
                status_code=400,
                detail=f"Could not find assignable user '{req.assignee}' in project {req.project_key}. "
                       f"Ensure the user has permission to be assigned issues in this project."
            )

    # Build the issue fields
    fields: dict[str, Any] = {
        "project": {"key": req.project_key},
        "issuetype": {"name": req.issue_type},
        "summary": req.summary,
    }

    # Add description in ADF format if provided
    if req.description:
        fields["description"] = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": req.description}],
                }
            ],
        }

    if req.priority:
        fields["priority"] = {"name": req.priority}

    if resolved_assignee:
        fields["assignee"] = {"accountId": resolved_assignee}

    if req.labels:
        fields["labels"] = req.labels

    # Add custom fields
    if req.custom_fields:
        for field_id, value in req.custom_fields.items():
            if not field_id.startswith("customfield_") and field_id.isdigit():
                field_id = f"customfield_{field_id}"
            fields[field_id] = value

    payload = {"fields": fields}

    url = f"{base}/rest/api/3/issue"
    try:
        r = sess.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=30)
        if r.status_code == 401:
            raise HTTPException(status_code=401, detail="Unauthorized: check ATLASSIAN_EMAIL/ATLASSIAN_API_TOKEN")
        if r.status_code == 400:
            error_data = r.json() if r.text else {}
            errors = error_data.get("errors", {})
            error_messages = error_data.get("errorMessages", [])
            detail = "; ".join(error_messages) if error_messages else str(errors)
            raise HTTPException(status_code=400, detail=f"Invalid issue data: {detail}")
        if r.status_code == 403:
            raise HTTPException(status_code=403, detail=f"Forbidden: missing create permission for project {req.project_key}")
        r.raise_for_status()

        result = r.json()
        issue_key = result.get("key", "")
        issue_id = result.get("id", "")

        # Create issue links if provided
        if req.linked_issues:
            for link in req.linked_issues:
                link_issue_key = link.get("issue_key")
                link_type = link.get("link_type", "relates to")
                if link_issue_key:
                    try:
                        link_url = f"{base}/rest/api/3/issueLink"
                        link_payload = {
                            "type": {"name": link_type},
                            "inwardIssue": {"key": issue_key},
                            "outwardIssue": {"key": link_issue_key},
                        }
                        sess.post(link_url, json=link_payload, timeout=15)
                    except Exception:
                        pass  # Best effort linking

        return {
            "success": True,
            "key": issue_key,
            "id": issue_id,
            "url": f"{base}/browse/{issue_key}",
        }
    except HTTPException:
        raise
    except requests.HTTPError as ex:
        msg = getattr(ex.response, "text", str(ex))[:300]
        raise HTTPException(status_code=502, detail=f"Jira error: {msg}")
    except Exception as ex:
        raise HTTPException(status_code=502, detail=f"Jira error: {ex}")


@router.put("/issue/{key}")
def update_issue(key: str, req: UpdateIssueRequest):
    """Update an existing Jira issue."""
    require_jira_enabled()
    sess, base = _jira_session()

    fields: dict[str, Any] = {}

    if req.summary is not None:
        fields["summary"] = req.summary

    if req.description is not None:
        fields["description"] = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": req.description}],
                }
            ],
        }

    if req.priority is not None:
        fields["priority"] = {"name": req.priority}

    if req.assignee is not None:
        fields["assignee"] = {"accountId": req.assignee} if req.assignee else None

    if req.labels is not None:
        fields["labels"] = req.labels

    if req.custom_fields:
        for field_id, value in req.custom_fields.items():
            if not field_id.startswith("customfield_") and field_id.isdigit():
                field_id = f"customfield_{field_id}"
            fields[field_id] = value

    if not fields:
        return {"success": True, "message": "No fields to update", "key": key, "url": f"{base}/browse/{key}"}

    payload = {"fields": fields}

    url = f"{base}/rest/api/3/issue/{key}"
    try:
        r = sess.put(url, json=payload, headers={"Content-Type": "application/json"}, timeout=30)
        if r.status_code == 401:
            raise HTTPException(status_code=401, detail="Unauthorized: check ATLASSIAN_EMAIL/ATLASSIAN_API_TOKEN")
        if r.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Issue {key} not found")
        if r.status_code == 400:
            error_data = r.json() if r.text else {}
            errors = error_data.get("errors", {})
            error_messages = error_data.get("errorMessages", [])
            detail = "; ".join(error_messages) if error_messages else str(errors)
            raise HTTPException(status_code=400, detail=f"Invalid update data: {detail}")
        r.raise_for_status()

        return {"success": True, "key": key, "url": f"{base}/browse/{key}"}
    except HTTPException:
        raise
    except requests.HTTPError as ex:
        msg = getattr(ex.response, "text", str(ex))[:300]
        raise HTTPException(status_code=502, detail=f"Jira error: {msg}")
    except Exception as ex:
        raise HTTPException(status_code=502, detail=f"Jira error: {ex}")


@router.post("/issue/{key}/comment")
def add_comment(key: str, req: AddCommentRequest):
    """Add a comment to a Jira issue."""
    require_jira_enabled()
    sess, base = _jira_session()

    payload = {
        "body": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": req.body}],
                }
            ],
        }
    }

    url = f"{base}/rest/api/3/issue/{key}/comment"
    try:
        r = sess.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=30)
        if r.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Issue {key} not found")
        r.raise_for_status()

        result = r.json()
        return {
            "success": True,
            "id": result.get("id", ""),
            "created": result.get("created", ""),
        }
    except HTTPException:
        raise
    except requests.HTTPError as ex:
        msg = getattr(ex.response, "text", str(ex))[:300]
        raise HTTPException(status_code=502, detail=f"Jira error: {msg}")
    except Exception as ex:
        raise HTTPException(status_code=502, detail=f"Jira error: {ex}")


# Remote Link Models
class ConfluenceRemoteLinkReq(BaseModel):
    page_id: str
    title: str | None = None
    relationship: str = "Wiki Page"


@router.get("/issue/{key}/remotelink")
def get_remote_links(key: str):
    """Get remote links for an issue."""
    require_jira_enabled()
    sess, base = _jira_session()
    
    url = f"{base}/rest/api/3/issue/{key}/remotelink"
    try:
        r = sess.get(url, timeout=30)
        if r.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Issue {key} not found")
        r.raise_for_status()
        return r.json()
    except requests.HTTPError as ex:
        raise HTTPException(status_code=ex.response.status_code, detail=str(ex))
    except Exception as ex:
        raise HTTPException(status_code=502, detail=f"Jira error: {ex}")


@router.post("/issue/{key}/remotelink/confluence")
def create_confluence_remotelink(key: str, req: ConfluenceRemoteLinkReq):
    """Create a remote link to a Confluence page."""
    require_jira_enabled()
    sess, base = _jira_session()

    # Configuration constants from requirements
    # These could be moved to env/config in the future if they change
    APP_ID = "c040a8bc-dafc-3073-aee9-8b0b4ba30eb0" 
    APP_NAME = "System Confluence"
    BASE_URL = "https://enreach-services.atlassian.net" # Could derive from config but prompt specified specific details
    
    # Construct the Jira Remote Link payload
    # GlobalID format: appId=...&pageId=...
    global_id = f"appId={APP_ID}&pageId={req.page_id}"
    page_url = f"{BASE_URL}/wiki/pages/viewpage.action?pageId={req.page_id}"
    title = req.title or f"Confluence Page {req.page_id}"
    
    payload = {
        "globalId": global_id,
        "application": {
            "type": "com.atlassian.confluence",
            "name": APP_NAME
        },
        "relationship": req.relationship,
        "object": {
            "url": page_url,
            "title": title,
            "icon": {
                "url16x16": f"{BASE_URL}/wiki/favicon.ico",
                "title": "Confluence"
            }
        }
    }

    url = f"{base}/rest/api/3/issue/{key}/remotelink"
    try:
        r = sess.post(url, json=payload, timeout=30)
        r.raise_for_status()
        res_json = r.json()
        return {
            "success": True, 
            "linkId": res_json.get("id"),
            "self": res_json.get("self"),
            "url": page_url
        }
    except requests.HTTPError as ex:
        # Check for duplicates or other specific errors if Jira returns useful msg
        detail = str(ex)
        if ex.response is not None:
             detail = ex.response.text
        raise HTTPException(status_code=ex.response.status_code if ex.response else 500, detail=detail)
    except Exception as ex:
        raise HTTPException(status_code=502, detail=f"Jira error: {ex}")


@router.delete("/issue/{key}/remotelink/{link_id}")
def delete_remote_link(key: str, link_id: str):
    """Delete a remote link."""
    require_jira_enabled()
    sess, base = _jira_session()

    url = f"{base}/rest/api/3/issue/{key}/remotelink/{link_id}"
    try:
        r = sess.delete(url, timeout=30)
        if r.status_code == 404:
             raise HTTPException(status_code=404, detail="Link or Issue not found")
        r.raise_for_status()
        return {"success": True, "message": "Link deleted"}
    except requests.HTTPError as ex:
        raise HTTPException(status_code=ex.response.status_code, detail=str(ex))
    except Exception as ex:
        raise HTTPException(status_code=502, detail=f"Jira error: {ex}")


# Attachment endpoints
@router.get("/issue/{key}/attachments")
def list_attachments(key: str):
    """List all attachments on a Jira issue."""
    require_jira_enabled()
    sess, base = _jira_session()

    # Get issue with attachment field
    url = f"{base}/rest/api/3/issue/{key}"
    try:
        r = sess.get(url, params={"fields": "attachment"}, timeout=30)
        if r.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Issue {key} not found")
        r.raise_for_status()
        data = r.json()
        attachments = data.get("fields", {}).get("attachment", [])
        return {
            "issue_key": key,
            "count": len(attachments),
            "attachments": [
                {
                    "id": a.get("id"),
                    "filename": a.get("filename"),
                    "size": a.get("size"),
                    "mimeType": a.get("mimeType"),
                    "created": a.get("created"),
                    "author": (a.get("author") or {}).get("displayName"),
                    "content": a.get("content"),  # Download URL
                }
                for a in attachments
            ],
        }
    except requests.HTTPError as ex:
        raise HTTPException(status_code=ex.response.status_code, detail=str(ex))
    except Exception as ex:
        raise HTTPException(status_code=502, detail=f"Jira error: {ex}")


class AttachFromUrlRequest(BaseModel):
    file_url: str
    filename: str | None = None


@router.post("/issue/{key}/attachments/url")
def attach_file_from_url(key: str, req: AttachFromUrlRequest):
    """Download a file from URL and attach it to a Jira issue."""
    require_jira_enabled()
    sess, base = _jira_session()

    # First download the file
    try:
        file_resp = requests.get(req.file_url, timeout=60, stream=True)
        file_resp.raise_for_status()

        # Determine filename
        filename = req.filename
        if not filename:
            # Try to get from Content-Disposition header
            cd = file_resp.headers.get("Content-Disposition", "")
            if "filename=" in cd:
                import re
                match = re.search(r'filename[^;=\n]*=((["\']).*?\2|[^;\n]*)', cd)
                if match:
                    filename = match.group(1).strip("\"'")
            if not filename:
                # Use last part of URL path
                from urllib.parse import urlparse
                path = urlparse(req.file_url).path
                filename = path.split("/")[-1] or "attachment"

        file_content = file_resp.content
        content_type = file_resp.headers.get("Content-Type", "application/octet-stream")

    except Exception as ex:
        raise HTTPException(status_code=400, detail=f"Failed to download file: {ex}")

    # Now upload to Jira
    url = f"{base}/rest/api/3/issue/{key}/attachments"
    try:
        # Jira attachments require multipart/form-data
        files = {"file": (filename, file_content, content_type)}
        # Need special header for attachments
        headers = {"X-Atlassian-Token": "no-check"}
        r = sess.post(url, files=files, headers=headers, timeout=60)

        if r.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Issue {key} not found")
        r.raise_for_status()

        result = r.json()
        return {
            "success": True,
            "issue_key": key,
            "filename": filename,
            "attachment": result[0] if result else None,
        }
    except requests.HTTPError as ex:
        detail = ex.response.text if ex.response else str(ex)
        raise HTTPException(status_code=ex.response.status_code if ex.response else 500, detail=detail)
    except Exception as ex:
        raise HTTPException(status_code=502, detail=f"Jira error: {ex}")
