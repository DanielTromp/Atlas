"""LangChain tool wrappers for Jira search."""

from __future__ import annotations

import json
import os
from typing import Any, ClassVar

import requests
from pydantic.v1 import BaseModel, Field, validator

from infrastructure_atlas.env import load_env

from .base import AtlasTool, ToolConfigurationError, ToolExecutionError

__all__ = ["JiraSearchTool"]


class _JiraSearchArgs(BaseModel):
    q: str | None = Field(default=None, description="Free-text clause (text ~)")
    jql: str | None = Field(default=None, description="Explicit JQL expression")
    project: str | None = Field(default=None)
    status: str | None = Field(default=None)
    assignee: str | None = Field(default=None)
    priority: str | None = Field(default=None)
    issuetype: str | None = Field(default=None)
    updated: str | None = Field(default=None)
    team: str | None = Field(default=None, description="Service desk team (cf[10575])")
    only_open: bool = Field(default=True, description="Exclude issues in Done status category")
    max_results: int = Field(default=50, description="Maximum issues to return (1-200)")

    @validator("q", "jql", "project", "status", "assignee", "priority", "issuetype", "updated", "team")
    def _trim(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @validator("max_results")
    def _validate_max_results(cls, value: int) -> int:
        ivalue = int(value)
        if not 1 <= ivalue <= 200:
            raise ValueError("max_results must be between 1 and 200")
        return ivalue


class JiraSearchTool(AtlasTool):
    name: ClassVar[str] = "jira_issue_search"
    description: ClassVar[str] = "Query Jira Cloud issues using JQL-aware filters."
    args_schema: ClassVar[type[_JiraSearchArgs]] = _JiraSearchArgs

    def _run(self, **kwargs: Any) -> str:
        args = self.args_schema(**kwargs)
        session, base_url = self._build_session()
        jql = args.jql or self._build_jql(args)
        try:
            payload = self._execute_search(session, base_url, jql, args.max_results)
        except ToolExecutionError:
            raise
        except Exception as exc:  # pragma: no cover - network/runtime errors
            raise self._handle_exception(exc)
        payload["jql"] = jql
        return json.dumps(payload)

    def _build_session(self) -> tuple[requests.Session, str]:
        load_env()
        base = os.getenv("ATLASSIAN_BASE_URL", "").strip() or os.getenv("JIRA_BASE_URL", "").strip()
        email = os.getenv("ATLASSIAN_EMAIL", "").strip() or os.getenv("JIRA_EMAIL", "").strip()
        token = os.getenv("ATLASSIAN_API_TOKEN", "").strip() or os.getenv("JIRA_API_TOKEN", "").strip()
        if not (base and email and token):
            raise ToolConfigurationError(
                "Jira credentials missing: set ATLASSIAN_BASE_URL, ATLASSIAN_EMAIL, ATLASSIAN_API_TOKEN"
            )
        session = requests.Session()
        session.auth = (email, token)
        session.headers.update({"Accept": "application/json"})
        return session, base.rstrip("/")

    def _build_jql(self, args: _JiraSearchArgs) -> str:
        parts: list[str] = []
        if args.only_open:
            parts.append("statusCategory != Done")
        if args.project:
            project = args.project
            if any(ch.isspace() for ch in project) or not project.isalnum():
                parts.append(f'project = "{project}"')
            else:
                parts.append(f"project = {project}")
        if args.status:
            if "," in args.status:
                vals = ",".join(f'"{v.strip()}"' for v in args.status.split(",") if v.strip())
                if vals:
                    parts.append(f"status in ({vals})")
            else:
                parts.append(f'status = "{args.status}"')
        if args.assignee:
            parts.append(f'assignee = "{args.assignee}"')
        if args.priority:
            if "," in args.priority:
                vals = ",".join(f'"{v.strip()}"' for v in args.priority.split(",") if v.strip())
                if vals:
                    parts.append(f"priority in ({vals})")
            else:
                parts.append(f'priority = "{args.priority}"')
        if args.issuetype:
            parts.append(f'issuetype = "{args.issuetype}"')
        if args.team:
            if "," in args.team:
                vals = ",".join(f'"{v.strip()}"' for v in args.team.split(",") if v.strip())
                if vals:
                    parts.append(f"cf[10575] in ({vals})")
            else:
                parts.append(f'cf[10575] = "{args.team}"')
        if args.updated:
            parts.append(f"updated >= {args.updated}")
        if not any(
            [
                args.project,
                args.status,
                args.assignee,
                args.priority,
                args.issuetype,
                args.team,
                args.updated,
                args.q,
            ]
        ):
            parts.append("updated >= -30d")
        if args.q:
            text = args.q.replace('"', '\\"')
            parts.append(f'text ~ "{text}"')
        jql = " AND ".join(parts) if parts else "order by updated desc"
        if "order by" not in jql.lower():
            jql += " ORDER BY updated DESC"
        return jql

    def _execute_search(
        self,
        session: requests.Session,
        base_url: str,
        jql: str,
        max_results: int,
    ) -> dict[str, Any]:
        url = f"{base_url}/rest/api/3/search/jql"
        params = {
            "jql": jql,
            "startAt": 0,
            "maxResults": int(max_results),
            "fields": "key,summary,status,assignee,priority,updated,created,issuetype,project",
        }
        resp = session.get(url, params=params, timeout=60)
        if resp.status_code == 401:
            raise ToolExecutionError("Jira authentication failed; check ATLASSIAN_API_TOKEN")
        if resp.status_code == 403:
            raise ToolExecutionError("Jira permissions error: access forbidden")
        if resp.status_code == 400:
            raise ToolExecutionError(resp.text or "Bad request to Jira search API")
        resp.raise_for_status()
        data = resp.json()
        issues = []
        if isinstance(data, dict):
            if isinstance(data.get("issues"), list):
                issues = data["issues"]
            elif isinstance(data.get("results"), list) and data["results"]:
                first = data["results"][0]
                if isinstance(first, dict) and isinstance(first.get("issues"), list):
                    issues = first["issues"]
        rows: list[dict[str, Any]] = []
        for issue in issues or []:
            try:
                key = issue.get("key") or ""
                fields = issue.get("fields") or {}
                if not isinstance(fields, dict):
                    fields = {}
                rows.append(
                    {
                        "key": key,
                        "summary": fields.get("summary") or "",
                        "status": ((fields.get("status") or {}).get("name") or ""),
                        "assignee": ((fields.get("assignee") or {}).get("displayName") or ""),
                        "priority": ((fields.get("priority") or {}).get("name") or ""),
                        "issuetype": ((fields.get("issuetype") or {}).get("name") or ""),
                        "project": (
                            (fields.get("project") or {}).get("key")
                            or ((fields.get("project") or {}).get("name") or "")
                        ),
                        "updated": fields.get("updated") or "",
                        "created": fields.get("created") or "",
                        "url": f"{base_url}/browse/{key}" if key else "",
                    }
                )
            except Exception as exc:  # pragma: no cover - defensive sanitiser
                self.logger.debug(
                    "Skipped malformed Jira issue entry",
                    exc_info=exc,
                    extra={"tool": self.name},
                )
                continue
        total = 0
        if isinstance(data, dict):
            total = int(data.get("total", 0) or 0)
            if not total and isinstance(data.get("isLast"), bool):
                total = len(rows)
            if not total and isinstance(data.get("results"), list) and data["results"]:
                first = data["results"][0]
                if isinstance(first, dict):
                    total = int(first.get("total", 0) or 0) or len(rows)
        if not total:
            total = len(rows)
        return {"total": total, "issues": rows}
