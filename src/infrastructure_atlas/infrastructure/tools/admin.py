"""LangChain tools for administrative insights."""

from __future__ import annotations

import json
import os
from typing import Any, ClassVar

from pydantic.v1 import BaseModel, Field

from infrastructure_atlas.env import load_env

from .base import AtlasTool

__all__ = ["AdminBackupStatusTool", "AdminConfigSurveyTool"]


_CONFIG_FIELDS: tuple[dict[str, Any], ...] = (
    {"key": "NETBOX_URL", "label": "NetBox URL", "secret": False},
    {"key": "NETBOX_TOKEN", "label": "NetBox API Token", "secret": True},
    {"key": "ZABBIX_API_URL", "label": "Zabbix API URL", "secret": False},
    {"key": "ZABBIX_API_TOKEN", "label": "Zabbix API Token", "secret": True},
    {"key": "ATLASSIAN_BASE_URL", "label": "Atlassian Base URL", "secret": False},
    {"key": "ATLASSIAN_EMAIL", "label": "Atlassian Email", "secret": False},
    {"key": "ATLASSIAN_API_TOKEN", "label": "Atlassian API Token", "secret": True},
    {"key": "ATLAS_DEFAULT_ADMIN_USERNAME", "label": "Default Admin User", "secret": False},
    {"key": "ATLAS_DEFAULT_ADMIN_PASSWORD", "label": "Default Admin Password", "secret": True},
)


class _AdminConfigArgs(BaseModel):
    include_values: bool = Field(
        default=False,
        description="Include raw values for non-secret fields",
    )


class AdminConfigSurveyTool(AtlasTool):
    name: ClassVar[str] = "admin_config_overview"
    description: ClassVar[str] = "Summarise key configuration environment variables and their status."
    args_schema: ClassVar[type[_AdminConfigArgs]] = _AdminConfigArgs

    def _run(self, **kwargs: Any) -> str:
        load_env()
        args = self.args_schema(**kwargs)
        rows: list[dict[str, Any]] = []
        for field in _CONFIG_FIELDS:
            key = field["key"]
            secret = bool(field.get("secret"))
            value = os.getenv(key, "")
            configured = bool(value)
            payload = {
                "key": key,
                "label": field.get("label", key),
                "configured": configured,
            }
            if args.include_values and not secret:
                payload["value"] = value
            elif secret and configured:
                payload["value"] = "••••••"
            rows.append(payload)
        return json.dumps({"settings": rows, "count": len(rows)})


class AdminBackupStatusTool(AtlasTool):
    name: ClassVar[str] = "admin_backup_status"
    description: ClassVar[str] = "Report the configured backup transport and completeness."

    def _run(self, **kwargs: Any) -> str:
        load_env()
        enabled = os.getenv("BACKUP_ENABLE", "1").strip().lower() not in {"0", "false", "no", "off"}
        btype = os.getenv("BACKUP_TYPE", "local").strip().lower() or "local"
        configured = False
        target = ""
        if btype == "local":
            path = os.getenv("BACKUP_LOCAL_PATH", "backups").strip()
            configured = bool(path)
            target = path
        elif btype in {"sftp", "scp"}:
            host = os.getenv("BACKUP_HOST", "").strip()
            username = os.getenv("BACKUP_USERNAME", "").strip()
            password = os.getenv("BACKUP_PASSWORD", "").strip()
            private_key = os.getenv("BACKUP_PRIVATE_KEY_PATH", "").strip()
            remote_path = os.getenv("BACKUP_REMOTE_PATH", "").strip()
            configured = bool(host and username and (password or private_key))
            if host and username:
                target = f"{username}@{host}"
                if remote_path:
                    target += f":{remote_path}"
        else:
            target = ""
        payload = {
            "enabled": enabled,
            "type": btype,
            "configured": configured,
            "target": target or None,
        }
        return json.dumps(payload)
