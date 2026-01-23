"""LangChain tool wrappers for Confluence search."""

from __future__ import annotations

import json
import os
from typing import Any, ClassVar

import requests
from pydantic.v1 import BaseModel, Field, validator

from infrastructure_atlas.env import load_env

from .base import AtlasTool, ToolConfigurationError, ToolExecutionError

__all__ = [
    "ConfluenceAppendToPageTool",
    "ConfluenceConvertMarkdownTool",
    "ConfluenceCreatePageTool",
    "ConfluenceDeletePageTool",
    "ConfluenceGetPageByTitleTool",
    "ConfluenceGetPageTool",
    "ConfluenceSearchTool",
    "ConfluenceUpdatePageTool",
]


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


def _markdown_to_storage(markdown: str) -> str:
    """Convert markdown to Confluence storage format (basic conversion)."""
    import re

    content = markdown

    # Headers
    content = re.sub(r"^### (.+)$", r"<h3>\1</h3>", content, flags=re.MULTILINE)
    content = re.sub(r"^## (.+)$", r"<h2>\1</h2>", content, flags=re.MULTILINE)
    content = re.sub(r"^# (.+)$", r"<h1>\1</h1>", content, flags=re.MULTILINE)

    # Bold and italic
    content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", content)
    content = re.sub(r"\*(.+?)\*", r"<em>\1</em>", content)

    # Code blocks
    content = re.sub(
        r"```(\w+)?\n(.*?)\n```",
        r'<ac:structured-macro ac:name="code"><ac:parameter ac:name="language">\1</ac:parameter>'
        r"<ac:plain-text-body><![CDATA[\2]]></ac:plain-text-body></ac:structured-macro>",
        content,
        flags=re.DOTALL,
    )
    content = re.sub(r"`([^`]+)`", r"<code>\1</code>", content)

    # Lists (basic)
    lines = content.split("\n")
    in_list = False
    result: list[str] = []
    for line in lines:
        if line.startswith("- "):
            if not in_list:
                result.append("<ul>")
                in_list = True
            result.append(f"<li>{line[2:]}</li>")
        elif line.startswith("* "):
            if not in_list:
                result.append("<ul>")
                in_list = True
            result.append(f"<li>{line[2:]}</li>")
        else:
            if in_list:
                result.append("</ul>")
                in_list = False
            result.append(line)
    if in_list:
        result.append("</ul>")
    content = "\n".join(result)

    # Paragraphs (wrap non-html lines)
    lines = content.split("\n")
    result = []
    for raw_line in lines:
        stripped = raw_line.strip()
        if stripped and not stripped.startswith("<"):
            result.append(f"<p>{stripped}</p>")
        else:
            result.append(stripped)

    return "\n".join(result)


# --- Get Page by ID Tool ---


class _ConfluenceGetPageArgs(BaseModel):
    page_id: str = Field(..., description="Confluence page ID")


class ConfluenceGetPageTool(AtlasTool):
    name: ClassVar[str] = "confluence_get_page_content"
    description: ClassVar[str] = (
        "Get a Confluence page with full content by its ID. "
        "Returns page title, content in storage format, version info, and ancestors."
    )
    args_schema: ClassVar[type[_ConfluenceGetPageArgs]] = _ConfluenceGetPageArgs

    def _run(self, **kwargs: Any) -> str:
        args = self.args_schema(**kwargs)
        session, wiki_url = self._build_session()
        try:
            return self._get_page(session, wiki_url, args.page_id)
        except ToolExecutionError:
            raise
        except Exception as exc:
            raise self._handle_exception(exc)

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

    def _get_page(self, session: requests.Session, wiki_url: str, page_id: str) -> str:
        url = f"{wiki_url}/rest/api/content/{page_id}"
        params = {"expand": "body.storage,version,space,ancestors"}
        resp = session.get(url, params=params, timeout=30)
        if resp.status_code == 401:
            raise ToolExecutionError("Confluence authentication failed; check ATLASSIAN_API_TOKEN")
        if resp.status_code == 403:
            raise ToolExecutionError("Confluence permissions error: access forbidden")
        if resp.status_code == 404:
            raise ToolExecutionError(f"Page {page_id} not found")
        resp.raise_for_status()
        data = resp.json()
        return json.dumps(
            {
                "page_id": data.get("id", ""),
                "title": data.get("title", ""),
                "space_key": (data.get("space") or {}).get("key", ""),
                "version": (data.get("version") or {}).get("number", 1),
                "content": (data.get("body", {}).get("storage", {}) or {}).get("value", ""),
                "url": f"{wiki_url}{(data.get('_links') or {}).get('webui', '')}",
                "ancestors": [{"id": a.get("id"), "title": a.get("title")} for a in (data.get("ancestors") or [])],
            }
        )


# --- Get Page by Title Tool ---


class _ConfluenceGetPageByTitleArgs(BaseModel):
    space_key: str = Field(..., description="Confluence space key (e.g., DOCS, IT)")
    title: str = Field(..., description="Exact page title to find")


class ConfluenceGetPageByTitleTool(AtlasTool):
    name: ClassVar[str] = "confluence_get_page_by_title"
    description: ClassVar[str] = (
        "Find a Confluence page by exact title in a specific space. Returns page ID, title, content, and URL if found."
    )
    args_schema: ClassVar[type[_ConfluenceGetPageByTitleArgs]] = _ConfluenceGetPageByTitleArgs

    def _run(self, **kwargs: Any) -> str:
        args = self.args_schema(**kwargs)
        session, wiki_url = self._build_session()
        try:
            return self._find_page(session, wiki_url, args.space_key, args.title)
        except ToolExecutionError:
            raise
        except Exception as exc:
            raise self._handle_exception(exc)

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

    def _find_page(self, session: requests.Session, wiki_url: str, space_key: str, title: str) -> str:
        # Use CQL to search for exact title in space
        escaped_title = title.replace('"', '\\"')
        cql = f'space = "{space_key}" AND title = "{escaped_title}"'
        params = {"cql": cql, "limit": 1, "expand": "body.storage,version,space"}
        resp = session.get(f"{wiki_url}/rest/api/search", params=params, timeout=30)
        if resp.status_code == 401:
            raise ToolExecutionError("Confluence authentication failed; check ATLASSIAN_API_TOKEN")
        if resp.status_code == 403:
            raise ToolExecutionError("Confluence permissions error: access forbidden")
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        if not results:
            return json.dumps({"found": False, "space_key": space_key, "title": title})
        content = results[0].get("content", {}) if results else {}
        page_id = content.get("id", "")
        # Fetch full content since search may not include body
        if page_id:
            full_resp = session.get(
                f"{wiki_url}/rest/api/content/{page_id}",
                params={"expand": "body.storage,version,space"},
                timeout=30,
            )
            if full_resp.ok:
                content = full_resp.json()
        return json.dumps(
            {
                "found": True,
                "page_id": content.get("id", ""),
                "title": content.get("title", ""),
                "space_key": (content.get("space") or {}).get("key", space_key),
                "version": (content.get("version") or {}).get("number", 1),
                "content": (content.get("body", {}).get("storage", {}) or {}).get("value", ""),
                "url": f"{wiki_url}{(content.get('_links') or {}).get('webui', '')}",
            }
        )


# --- Update Page Tool ---


class _ConfluenceUpdatePageArgs(BaseModel):
    page_id: str = Field(..., description="Confluence page ID to update")
    content: str = Field(..., description="New page content")
    content_format: str = Field(default="storage", description="Format: 'storage' (HTML) or 'markdown'")
    title: str | None = Field(default=None, description="New title (optional, keeps current if not provided)")
    version_comment: str | None = Field(default=None, description="Version comment for the change")
    minor_edit: bool = Field(default=False, description="Mark as minor edit (no notifications)")


class ConfluenceUpdatePageTool(AtlasTool):
    name: ClassVar[str] = "confluence_update_page"
    description: ClassVar[str] = (
        "Update an existing Confluence page content. Supports storage format (HTML) or markdown. "
        "[DESTRUCTIVE: This action modifies data]"
    )
    args_schema: ClassVar[type[_ConfluenceUpdatePageArgs]] = _ConfluenceUpdatePageArgs

    def _run(self, **kwargs: Any) -> str:
        args = self.args_schema(**kwargs)
        session, wiki_url = self._build_session()
        try:
            return self._update_page(session, wiki_url, args)
        except ToolExecutionError:
            raise
        except Exception as exc:
            raise self._handle_exception(exc)

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
        session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
        wiki = base.rstrip("/") + "/wiki"
        return session, wiki

    def _update_page(self, session: requests.Session, wiki_url: str, args: _ConfluenceUpdatePageArgs) -> str:
        # Get current page for version number
        get_url = f"{wiki_url}/rest/api/content/{args.page_id}"
        resp = session.get(get_url, params={"expand": "version,space"}, timeout=30)
        if resp.status_code == 404:
            raise ToolExecutionError(f"Page {args.page_id} not found")
        if resp.status_code == 401:
            raise ToolExecutionError("Confluence authentication failed; check ATLASSIAN_API_TOKEN")
        resp.raise_for_status()
        current = resp.json()

        current_version = (current.get("version") or {}).get("number", 0)
        current_title = current.get("title", "")
        space_key = (current.get("space") or {}).get("key", "")

        # Convert markdown if needed
        content = args.content
        if args.content_format == "markdown":
            content = _markdown_to_storage(args.content)

        title = args.title if args.title is not None else current_title

        payload: dict[str, Any] = {
            "type": "page",
            "title": title,
            "version": {"number": current_version + 1, "minorEdit": args.minor_edit},
            "body": {"storage": {"value": content, "representation": "storage"}},
        }
        if args.version_comment:
            payload["version"]["message"] = args.version_comment

        resp = session.put(f"{wiki_url}/rest/api/content/{args.page_id}", json=payload, timeout=30)
        if resp.status_code == 401:
            raise ToolExecutionError("Confluence authentication failed; check ATLASSIAN_API_TOKEN")
        if resp.status_code == 400:
            error_data = resp.json() if resp.text else {}
            detail = error_data.get("message", str(error_data))
            raise ToolExecutionError(f"Invalid update data: {detail}")
        resp.raise_for_status()

        result = resp.json()
        return json.dumps(
            {
                "success": True,
                "page_id": result.get("id", ""),
                "title": result.get("title", ""),
                "space_key": space_key,
                "version": (result.get("version") or {}).get("number", current_version + 1),
                "url": f"{wiki_url}{(result.get('_links') or {}).get('webui', '')}",
            }
        )


# --- Create Page Tool ---


class _ConfluenceCreatePageArgs(BaseModel):
    space_key: str = Field(..., description="Confluence space key (e.g., DOCS, IT)")
    title: str = Field(..., description="Page title")
    content: str = Field(..., description="Page content")
    content_format: str = Field(default="storage", description="Format: 'storage' (HTML) or 'markdown'")
    parent_page_id: str | None = Field(default=None, description="Parent page ID for hierarchy (optional)")
    labels: list[str] | None = Field(default=None, description="Labels to add to the page (optional)")

    @validator("labels", pre=True)
    def _parse_labels(cls, value: Any) -> list[str] | None:
        if value is None:
            return None
        if isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
        return value


class ConfluenceCreatePageTool(AtlasTool):
    name: ClassVar[str] = "confluence_create_page"
    description: ClassVar[str] = (
        "Create a new Confluence page in a space. Supports storage format (HTML) or markdown. "
        "[DESTRUCTIVE: This action modifies data]"
    )
    args_schema: ClassVar[type[_ConfluenceCreatePageArgs]] = _ConfluenceCreatePageArgs

    def _run(self, **kwargs: Any) -> str:
        args = self.args_schema(**kwargs)
        session, wiki_url = self._build_session()
        try:
            return self._create_page(session, wiki_url, args)
        except ToolExecutionError:
            raise
        except Exception as exc:
            raise self._handle_exception(exc)

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
        session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
        wiki = base.rstrip("/") + "/wiki"
        return session, wiki

    def _create_page(self, session: requests.Session, wiki_url: str, args: _ConfluenceCreatePageArgs) -> str:
        content = args.content
        if args.content_format == "markdown":
            content = _markdown_to_storage(args.content)

        payload: dict[str, Any] = {
            "type": "page",
            "title": args.title,
            "space": {"key": args.space_key},
            "body": {"storage": {"value": content, "representation": "storage"}},
        }
        if args.parent_page_id:
            payload["ancestors"] = [{"id": args.parent_page_id}]

        resp = session.post(f"{wiki_url}/rest/api/content", json=payload, timeout=30)
        if resp.status_code == 401:
            raise ToolExecutionError("Confluence authentication failed; check ATLASSIAN_API_TOKEN")
        if resp.status_code == 400:
            error_data = resp.json() if resp.text else {}
            detail = error_data.get("message", str(error_data))
            raise ToolExecutionError(f"Invalid page data: {detail}")
        resp.raise_for_status()

        result = resp.json()
        page_id = result.get("id", "")

        # Add labels if provided
        if args.labels and page_id:
            try:
                labels_url = f"{wiki_url}/rest/api/content/{page_id}/label"
                labels_payload = [{"name": label} for label in args.labels]
                session.post(labels_url, json=labels_payload, timeout=15)
            except Exception:
                pass  # Best effort labeling

        return json.dumps(
            {
                "success": True,
                "page_id": page_id,
                "title": result.get("title", ""),
                "space_key": (result.get("space") or {}).get("key", args.space_key),
                "version": (result.get("version") or {}).get("number", 1),
                "url": f"{wiki_url}{(result.get('_links') or {}).get('webui', '')}",
            }
        )


# --- Append to Page Tool ---


class _ConfluenceAppendToPageArgs(BaseModel):
    page_id: str = Field(..., description="Confluence page ID to append to")
    content: str = Field(..., description="Content to append")
    content_format: str = Field(default="storage", description="Format: 'storage' (HTML) or 'markdown'")
    position: str = Field(default="end", description="Where to add: 'end' (append) or 'start' (prepend)")
    version_comment: str | None = Field(default=None, description="Version comment for the change")

    @validator("position")
    def _validate_position(cls, value: str) -> str:
        if value not in ("end", "start"):
            raise ValueError("position must be 'end' or 'start'")
        return value


class ConfluenceAppendToPageTool(AtlasTool):
    name: ClassVar[str] = "confluence_append_to_page"
    description: ClassVar[str] = (
        "Append or prepend content to an existing Confluence page without replacing existing content. "
        "[DESTRUCTIVE: This action modifies data]"
    )
    args_schema: ClassVar[type[_ConfluenceAppendToPageArgs]] = _ConfluenceAppendToPageArgs

    def _run(self, **kwargs: Any) -> str:
        args = self.args_schema(**kwargs)
        session, wiki_url = self._build_session()
        try:
            return self._append_to_page(session, wiki_url, args)
        except ToolExecutionError:
            raise
        except Exception as exc:
            raise self._handle_exception(exc)

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
        session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
        wiki = base.rstrip("/") + "/wiki"
        return session, wiki

    def _append_to_page(self, session: requests.Session, wiki_url: str, args: _ConfluenceAppendToPageArgs) -> str:
        # Get current page content and version
        get_url = f"{wiki_url}/rest/api/content/{args.page_id}"
        resp = session.get(get_url, params={"expand": "body.storage,version,space"}, timeout=30)
        if resp.status_code == 404:
            raise ToolExecutionError(f"Page {args.page_id} not found")
        if resp.status_code == 401:
            raise ToolExecutionError("Confluence authentication failed; check ATLASSIAN_API_TOKEN")
        resp.raise_for_status()
        current = resp.json()

        current_version = (current.get("version") or {}).get("number", 0)
        current_title = current.get("title", "")
        space_key = (current.get("space") or {}).get("key", "")
        current_content = (current.get("body", {}).get("storage", {}) or {}).get("value", "")

        # Convert new content if markdown
        new_content = args.content
        if args.content_format == "markdown":
            new_content = _markdown_to_storage(args.content)

        # Combine content
        if args.position == "start":
            combined = new_content + "\n" + current_content
        else:
            combined = current_content + "\n" + new_content

        payload: dict[str, Any] = {
            "type": "page",
            "title": current_title,
            "version": {"number": current_version + 1, "minorEdit": False},
            "body": {"storage": {"value": combined, "representation": "storage"}},
        }
        if args.version_comment:
            payload["version"]["message"] = args.version_comment

        resp = session.put(f"{wiki_url}/rest/api/content/{args.page_id}", json=payload, timeout=30)
        if resp.status_code == 401:
            raise ToolExecutionError("Confluence authentication failed; check ATLASSIAN_API_TOKEN")
        if resp.status_code == 400:
            error_data = resp.json() if resp.text else {}
            detail = error_data.get("message", str(error_data))
            raise ToolExecutionError(f"Invalid update data: {detail}")
        resp.raise_for_status()

        result = resp.json()
        return json.dumps(
            {
                "success": True,
                "page_id": result.get("id", ""),
                "title": result.get("title", ""),
                "space_key": space_key,
                "version": (result.get("version") or {}).get("number", current_version + 1),
                "position": args.position,
                "url": f"{wiki_url}{(result.get('_links') or {}).get('webui', '')}",
            }
        )


# --- Convert Markdown to Storage Tool ---


class _ConfluenceConvertMarkdownArgs(BaseModel):
    markdown: str = Field(..., description="Markdown content to convert")


class ConfluenceConvertMarkdownTool(AtlasTool):
    name: ClassVar[str] = "confluence_convert_markdown_to_storage"
    description: ClassVar[str] = (
        "Convert markdown content to Confluence storage format (XHTML). "
        "Useful for previewing how markdown will look before creating/updating pages."
    )
    args_schema: ClassVar[type[_ConfluenceConvertMarkdownArgs]] = _ConfluenceConvertMarkdownArgs

    def _run(self, **kwargs: Any) -> str:
        args = self.args_schema(**kwargs)
        try:
            storage = _markdown_to_storage(args.markdown)
            return json.dumps({"success": True, "storage_format": storage})
        except Exception as exc:
            raise self._handle_exception(exc)


# --- Delete Page Tool ---


class _ConfluenceDeletePageArgs(BaseModel):
    page_id: str = Field(..., description="Confluence page ID to delete")


class ConfluenceDeletePageTool(AtlasTool):
    name: ClassVar[str] = "confluence_delete_page"
    description: ClassVar[str] = (
        "Delete a Confluence page by ID. This action is irreversible. "
        "[DESTRUCTIVE: This action modifies data] [REQUIRES CONFIRMATION]"
    )
    args_schema: ClassVar[type[_ConfluenceDeletePageArgs]] = _ConfluenceDeletePageArgs

    def _run(self, **kwargs: Any) -> str:
        args = self.args_schema(**kwargs)
        session, wiki_url = self._build_session()
        try:
            return self._delete_page(session, wiki_url, args.page_id)
        except ToolExecutionError:
            raise
        except Exception as exc:
            raise self._handle_exception(exc)

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

    def _delete_page(self, session: requests.Session, wiki_url: str, page_id: str) -> str:
        # First get page info for response
        get_url = f"{wiki_url}/rest/api/content/{page_id}"
        resp = session.get(get_url, params={"expand": "space"}, timeout=30)
        if resp.status_code == 404:
            raise ToolExecutionError(f"Page {page_id} not found")
        if resp.status_code == 401:
            raise ToolExecutionError("Confluence authentication failed; check ATLASSIAN_API_TOKEN")
        resp.raise_for_status()
        page_info = resp.json()
        title = page_info.get("title", "")
        space_key = (page_info.get("space") or {}).get("key", "")

        # Delete the page
        resp = session.delete(f"{wiki_url}/rest/api/content/{page_id}", timeout=30)
        if resp.status_code == 401:
            raise ToolExecutionError("Confluence authentication failed; check ATLASSIAN_API_TOKEN")
        if resp.status_code == 403:
            raise ToolExecutionError("Confluence permissions error: cannot delete this page")
        if resp.status_code == 404:
            raise ToolExecutionError(f"Page {page_id} not found")
        resp.raise_for_status()

        return json.dumps(
            {
                "success": True,
                "deleted_page_id": page_id,
                "deleted_title": title,
                "space_key": space_key,
            }
        )
