"""Confluence API routes.

Confluence integration (read-only search)
- Uses same ATLASSIAN_* credentials
- Queries CQL via /wiki/rest/api/search (GET) with bounded defaults
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

import requests
from fastapi import APIRouter, HTTPException, Query

from infrastructure_atlas.infrastructure.modules import get_module_registry

router = APIRouter(prefix="/confluence", tags=["confluence"])


# Module guard dependency
def require_confluence_enabled():
    """Dependency to ensure Confluence module is enabled."""
    registry = get_module_registry()
    try:
        registry.require_enabled("confluence")
    except Exception as e:
        raise HTTPException(status_code=403, detail=f"Confluence module is disabled: {e}")


# Helper functions (duplicated from Jira for module independence)
def _jira_cfg() -> dict[str, str]:
    """Return Atlassian (Jira) credentials.

    Preferred envs: ATLASSIAN_BASE_URL, ATLASSIAN_EMAIL, ATLASSIAN_API_TOKEN
    Backwards-compatible fallbacks: JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN
    """
    base = os.getenv("ATLASSIAN_BASE_URL", "").strip() or os.getenv("JIRA_BASE_URL", "").strip()
    email = os.getenv("ATLASSIAN_EMAIL", "").strip() or os.getenv("JIRA_EMAIL", "").strip()
    token = os.getenv("ATLASSIAN_API_TOKEN", "").strip() or os.getenv("JIRA_API_TOKEN", "").strip()
    return {"base": base, "email": email, "token": token}


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


def _conf_session() -> tuple[requests.Session, str]:
    """Create authenticated Confluence session."""
    sess, base = _jira_session()
    # Confluence Cloud REST base is under /wiki
    wiki = base.rstrip("/") + "/wiki"
    return sess, wiki


def _cql_build(
    q: str | None = None,
    space: str | None = None,
    ctype: str | None = None,
    labels: str | None = None,
    updated: str | None = None,
) -> str:
    """Build CQL query from filters."""
    parts: list[str] = []
    if space and space.strip():
        s = space.strip()
        # If looks like a key (no spaces), use space = "KEY"; otherwise match by title
        esc = s.replace('"', '\\"')
        if any(ch.isspace() for ch in s):
            parts.append(f'space.title = "{esc}"')
        else:
            parts.append(f'space = "{esc}"')
    if ctype and ctype.strip():
        # Confluence types: page, blogpost, attachment, comment, etc.
        parts.append(f"type = {ctype.strip()}")
    if labels and labels.strip():
        arr = [v.strip() for v in labels.split(",") if v.strip()]
        if len(arr) == 1:
            parts.append(f"label = '{arr[0]}'")
        elif arr:
            parts.append("(" + " OR ".join([f"label = '{v}'" for v in arr]) + ")")
    if updated and updated.strip():
        up = updated.strip()
        if up.startswith("-"):
            parts.append(f"lastmodified >= now('{up}')")
        else:
            parts.append(f"lastmodified >= '{up}'")
    # Add text query last to help relevance
    if q and q.strip():
        qq = q.replace('"', '\\"')
        parts.append(f'text ~ "{qq}"')
    # Bound the query if still empty (avoid unbounded errors/pagination surprises)
    if not parts:
        parts.append("lastmodified >= now(-90d)")
    # Order by last modified desc
    cql = " AND ".join(parts)
    cql += " order by lastmodified desc"
    return cql


# API Routes


@router.get("/config")
def confluence_config():
    """Return Confluence configuration status."""
    require_confluence_enabled()
    cfg = _jira_cfg()
    ok = bool(cfg.get("base") and cfg.get("email") and cfg.get("token"))
    base = (cfg.get("base") or "").rstrip("/")
    return {"configured": ok, "base_url": base + "/wiki" if ok else base}


@router.get("/search")
def confluence_search(
    q: str | None = Query(None, description="Full-text query"),
    space: str | None = Query(None, description="Space key (e.g., DOCS)"),
    ctype: str | None = Query("page", description="Type: page, blogpost, attachment"),
    labels: str | None = Query(None, description="Comma-separated labels"),
    updated: str | None = Query(None, description="-30d or 2025-01-01"),
    max_results: int = Query(50, ge=1, le=100),
):
    """Search Confluence content with CQL filters."""
    require_confluence_enabled()
    sess, wiki = _conf_session()

    # Resolve space names to keys when needed (names often contain spaces; CQL expects keys)
    def _resolve_space_keys(raw: str) -> list[str]:
        toks = [t.strip() for t in (raw or "").split(",") if t.strip()]
        keys: list[str] = []
        for t in toks:
            # Likely a key if no spaces and matches typical key charset
            if t and all((ch.isalnum() or ch in ("_", "-")) for ch in t) and (not any(ch.isspace() for ch in t)):
                keys.append(t)
                continue
            # 1) Lookup by name using CQL; then keep only exact title/name matches
            exact_keys: list[str] = []
            try:
                esc = t.replace('"', '\\"')
                url_s = wiki + "/rest/api/search"
                r_s = sess.get(url_s, params={"cql": f'type = space AND title ~ "{esc}"', "limit": 50}, timeout=30)
                if r_s.ok:
                    data_s = r_s.json()
                    for it in data_s.get("results", []) or []:
                        sp = it.get("space", {}) if isinstance(it, dict) else {}
                        name = (
                            (sp.get("name") or it.get("title") or "")
                            if isinstance(sp, dict)
                            else (it.get("title") or "")
                        )
                        if isinstance(name, str) and name.strip().lower() == t.strip().lower():
                            k = sp.get("key") if isinstance(sp, dict) else None
                            if k and (k not in exact_keys):
                                exact_keys.append(k)
            except Exception:
                pass
            # 2) Fallback: spaces REST listing filtered by q, then exact name match
            if not exact_keys:
                try:
                    rs = sess.get(wiki + "/rest/api/space", params={"q": t, "limit": 50}, timeout=30)
                    if rs.ok:
                        ds = rs.json()
                        for sp in ds.get("results", []) or []:
                            nm = sp.get("name") or ""
                            if isinstance(nm, str) and nm.strip().lower() == t.strip().lower():
                                k = sp.get("key") or ""
                                if k and (k not in exact_keys):
                                    exact_keys.append(k)
                except Exception:
                    pass
            # Only add exact match keys to avoid partial-space spills
            keys.extend([k for k in exact_keys if k and k not in keys])
        return keys

    space_keys: list[str] = []
    if space and space.strip():
        space_keys = _resolve_space_keys(space)

    cql = _cql_build(q=q, space=None, ctype=ctype, labels=labels, updated=updated)
    if space and space.strip() and not space_keys:
        # Space provided but not resolved exactly -> return empty set
        return {"total": 0, "cql": f"space unresolved: {space}", "results": []}
    if space_keys:
        quoted_keys = ", ".join(f'"{k}"' for k in space_keys)
        cql = f"space in ({quoted_keys}) AND " + cql
    url = wiki + "/rest/api/search"
    # Ask Confluence to include space + history info so we can display Space and Updated reliably
    params = {"cql": cql, "limit": int(max_results), "expand": "content.space,content.history"}
    try:
        r = sess.get(url, params=params, timeout=60)
        if r.status_code == 401:
            raise HTTPException(status_code=401, detail="Unauthorized: check ATLASSIAN_EMAIL/ATLASSIAN_API_TOKEN")
        if r.status_code == 403:
            raise HTTPException(status_code=403, detail="Forbidden: missing permissions for this CQL/fields")
        r.raise_for_status()
        data = r.json()
    except requests.HTTPError as ex:
        msg = getattr(ex.response, "text", "")
        raise HTTPException(status_code=502, detail=f"Confluence error: {ex} {msg[:300]}")
    except Exception as ex:
        raise HTTPException(status_code=502, detail=f"Confluence error: {ex}")

    items = data.get("results", []) if isinstance(data, dict) else []
    out: list[dict[str, Any]] = []
    for it in items or []:
        if not isinstance(it, Mapping):
            continue
        content_raw = it.get("content")
        content = content_raw if isinstance(content_raw, Mapping) else {}
        title = str(content.get("title") or it.get("title") or "")
        ctype_val = str(content.get("type") or it.get("type") or "")
        space_obj_raw = content.get("space")
        space_obj = space_obj_raw if isinstance(space_obj_raw, Mapping) else {}
        space_key = space_obj.get("key") if isinstance(space_obj, Mapping) else None
        space_name = space_obj.get("name") if isinstance(space_obj, Mapping) else None
        if not space_name:
            rgc_raw = it.get("resultGlobalContainer")
            rgc = rgc_raw if isinstance(rgc_raw, Mapping) else {}
            if rgc:
                space_name = space_name or rgc.get("title")
                disp = rgc.get("displayUrl") or ""
                if (not space_key) and isinstance(disp, str) and "/spaces/" in disp:
                    parts = disp.split("/spaces/")
                    if len(parts) > 1:
                        tail = parts[1]
                        space_key = tail.split("/")[0]
        links_raw = content.get("_links") or it.get("_links")
        links = links_raw if isinstance(links_raw, Mapping) else {}
        webui = links.get("webui") or links.get("base")
        link = (
            wiki + webui
            if isinstance(webui, str) and webui.startswith("/")
            else (wiki + "/" + webui if isinstance(webui, str) and webui else "")
        )
        lastmod = None
        hist_raw = content.get("history")
        hist = hist_raw if isinstance(hist_raw, Mapping) else {}
        last = hist.get("lastUpdated") if isinstance(hist, Mapping) else None
        if isinstance(last, Mapping):
            lastmod = last.get("when")
        if not lastmod:
            lastmod = it.get("lastModified") or it.get("friendlyLastModified") or ""
        out.append(
            {
                "title": title,
                "type": ctype_val,
                "space": (space_name or space_key or ""),
                "space_key": (space_key or ""),
                "space_name": (space_name or ""),
                "updated": lastmod or "",
                "url": link,
            }
        )
    total = int(data.get("size", 0) or 0) if isinstance(data, dict) else len(out)
    if not total:
        total = len(out)
    return {"total": total, "cql": cql, "results": out}
