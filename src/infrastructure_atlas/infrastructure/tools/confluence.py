"""LangChain tool wrappers for Confluence search."""

from __future__ import annotations

import json
import os
from typing import Any, ClassVar

import requests
from pydantic.v1 import BaseModel, Field, validator

from infrastructure_atlas.env import load_env

from .base import AtlasTool, ToolConfigurationError, ToolExecutionError

__all__ = ["ConfluenceSearchTool"]


class _ConfluenceSearchArgs(BaseModel):
    q: str | None = Field(default=None, description="Full-text query")
    space: str | None = Field(default=None, description="Space key or name")
    ctype: str | None = Field(default="page", description="Content type (page, blogpost, attachment)")
    labels: str | None = Field(default=None, description="Comma separated labels")
    updated: str | None = Field(default=None, description="Updated since (e.g. -30d or 2025-01-01)")
    max_results: int = Field(default=50, description="Maximum number of results (1-100)")

    @validator("q", "space", "ctype", "labels", "updated")
    def _trim(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @validator("max_results")
    def _validate_max_results(cls, value: int) -> int:
        ivalue = int(value)
        if not 1 <= ivalue <= 100:
            raise ValueError("max_results must be between 1 and 100")
        return ivalue


class ConfluenceSearchTool(AtlasTool):
    name: ClassVar[str] = "confluence_search"
    description: ClassVar[str] = "Search documentation in Confluence Cloud using CQL."
    args_schema: ClassVar[type[_ConfluenceSearchArgs]] = _ConfluenceSearchArgs

    def _run(self, **kwargs: Any) -> str:
        args = self.args_schema(**kwargs)
        session, wiki_url = self._build_session()
        try:
            payload = self._execute_search(session, wiki_url, args)
        except ToolExecutionError:
            raise
        except Exception as exc:  # pragma: no cover - network/runtime errors
            raise self._handle_exception(exc)
        return json.dumps(payload)

    def _build_session(self) -> tuple[requests.Session, str]:
        load_env()
        base = os.getenv("ATLASSIAN_BASE_URL", "").strip() or os.getenv("JIRA_BASE_URL", "").strip()
        email = os.getenv("ATLASSIAN_EMAIL", "").strip() or os.getenv("JIRA_EMAIL", "").strip()
        token = os.getenv("ATLASSIAN_API_TOKEN", "").strip() or os.getenv("JIRA_API_TOKEN", "").strip()
        if not (base and email and token):
            raise ToolConfigurationError(
                "Confluence credentials missing: set ATLASSIAN_BASE_URL, ATLASSIAN_EMAIL, ATLASSIAN_API_TOKEN"
            )
        session = requests.Session()
        session.auth = (email, token)
        session.headers.update({"Accept": "application/json"})
        wiki = base.rstrip("/") + "/wiki"
        return session, wiki

    def _execute_search(
        self,
        session: requests.Session,
        wiki_url: str,
        args: _ConfluenceSearchArgs,
    ) -> dict[str, Any]:
        space_keys = self._resolve_space_keys(session, wiki_url, args.space) if args.space else []
        if args.space and not space_keys:
            return {"total": 0, "cql": f"space unresolved: {args.space}", "results": []}
        cql = self._build_cql(args.q, args.ctype, args.labels, args.updated)
        if space_keys:
            quoted = ", ".join(f'"{key}"' for key in space_keys)
            cql = f"space in ({quoted}) AND " + cql
        params = {
            "cql": cql,
            "limit": int(args.max_results),
            "expand": "content.space,content.history",
        }
        resp = session.get(f"{wiki_url}/rest/api/search", params=params, timeout=60)
        if resp.status_code == 401:
            raise ToolExecutionError("Confluence authentication failed; check ATLASSIAN_API_TOKEN")
        if resp.status_code == 403:
            raise ToolExecutionError("Confluence permissions error: access forbidden")
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", []) if isinstance(data, dict) else []
        items: list[dict[str, Any]] = []
        for entry in results or []:
            try:
                content = entry.get("content", {}) if isinstance(entry, dict) else {}
                title = content.get("title") or entry.get("title") or ""
                ctype = content.get("type") or entry.get("type") or ""
                space_obj = content.get("space") if isinstance(content, dict) else {}
                space_key = ""
                space_name = ""
                if isinstance(space_obj, dict):
                    space_key = str(space_obj.get("key") or "")
                    space_name = str(space_obj.get("name") or "")
                if not space_name:
                    rgc = entry.get("resultGlobalContainer") if isinstance(entry, dict) else {}
                    if isinstance(rgc, dict):
                        space_name = str(rgc.get("title") or "") or space_name
                        disp = rgc.get("displayUrl") or ""
                        if disp and isinstance(disp, str) and "/spaces/" in disp and not space_key:
                            try:
                                space_key = disp.split("/spaces/")[1].split("/")[0]
                            except Exception:
                                pass
                links = (content.get("_links") or entry.get("_links") or {}) if isinstance(content, dict) else {}
                webui = links.get("webui") or links.get("base")
                url = ""
                if isinstance(webui, str):
                    url = wiki_url.rstrip("/") + webui if webui.startswith("/") else f"{wiki_url}/{webui}"
                history = content.get("history") if isinstance(content, dict) else None
                lastmod = ""
                if isinstance(history, dict):
                    last = history.get("lastUpdated")
                    if isinstance(last, dict):
                        lastmod = str(last.get("when") or "")
                if not lastmod and isinstance(entry, dict):
                    lastmod = str(entry.get("lastModified") or entry.get("friendlyLastModified") or "")
                items.append(
                    {
                        "title": title,
                        "type": ctype,
                        "space": space_name or space_key,
                        "space_key": space_key,
                        "space_name": space_name,
                        "updated": lastmod,
                        "url": url,
                    }
                )
            except Exception as exc:  # pragma: no cover - defensive sanitiser
                self.logger.debug(
                    "Skipped malformed Confluence search item",
                    exc_info=exc,
                    extra={"tool": self.name},
                )
                continue
        total = 0
        if isinstance(data, dict):
            total = int(data.get("size", 0) or 0)
            if not total:
                total = len(items)
        else:
            total = len(items)
        return {"total": total, "cql": cql, "results": items}

    def _build_cql(
        self,
        q: str | None,
        ctype: str | None,
        labels: str | None,
        updated: str | None,
    ) -> str:
        parts: list[str] = []
        if ctype:
            parts.append(f"type = {ctype}")
        if labels:
            tokens = [token.strip() for token in labels.split(",") if token.strip()]
            if len(tokens) == 1:
                parts.append(f"label = '{tokens[0]}'")
            elif tokens:
                parts.append("(" + " OR ".join(f"label = '{token}'" for token in tokens) + ")")
        if updated:
            if updated.startswith("-"):
                parts.append(f"lastmodified >= now('{updated}')")
            else:
                parts.append(f"lastmodified >= '{updated}'")
        if q:
            safe_q = q.replace('"', '\\"')
            parts.append(f'text ~ "{safe_q}"')
        if not parts:
            parts.append("lastmodified >= now(-90d)")
        cql = " AND ".join(parts)
        if "order by" not in cql.lower():
            cql += " order by lastmodified desc"
        return cql

    def _resolve_space_keys(
        self,
        session: requests.Session,
        wiki_url: str,
        raw: str | None,
    ) -> list[str]:
        if not raw:
            return []
        tokens = [token.strip() for token in raw.split(",") if token.strip()]
        keys: list[str] = []
        for token in tokens:
            if (
                token
                and all((ch.isalnum() or ch in {"_", "-"}) for ch in token)
                and not any(ch.isspace() for ch in token)
            ):
                keys.append(token)
                continue
            exact: list[str] = []
            try:
                esc = token.replace('"', '\\"')
                resp = session.get(
                    f"{wiki_url}/rest/api/search",
                    params={"cql": f'type = space AND title ~ "{esc}"', "limit": 50},
                    timeout=30,
                )
                if resp.ok:
                    data = resp.json()
                    for item in data.get("results", []) or []:
                        space = item.get("space", {}) if isinstance(item, dict) else {}
                        name = ""
                        if isinstance(space, dict):
                            name = str(space.get("name") or "")
                        if name and name.lower() == token.lower():
                            key = str(space.get("key") or "")
                            if key and key not in exact:
                                exact.append(key)
            except Exception:
                pass
            if not exact:
                try:
                    resp = session.get(
                        f"{wiki_url}/rest/api/space",
                        params={"q": token, "limit": 50},
                        timeout=30,
                    )
                    if resp.ok:
                        data = resp.json()
                        for space in data.get("results", []) or []:
                            name = str(space.get("name") or "")
                            if name and name.lower() == token.lower():
                                key = str(space.get("key") or "")
                                if key and key not in exact:
                                    exact.append(key)
                except Exception:
                    pass
            for key in exact:
                if key and key not in keys:
                    keys.append(key)
        return keys
