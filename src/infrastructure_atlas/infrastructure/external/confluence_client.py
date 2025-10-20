"""Confluence REST adapter with attachment helpers."""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

from infrastructure_atlas.domain.integrations import ConfluenceAttachment


@dataclass(slots=True)
class ConfluenceClientConfig:
    base_url: str
    email: str
    api_token: str

    def api_root(self) -> str:
        base = self.base_url.rstrip("/")
        return f"{base}/wiki/rest/api"


class ConfluenceClient:
    def __init__(self, config: ConfluenceClientConfig, *, timeout: float = 30.0) -> None:
        if not (config.base_url and config.email and config.api_token):
            raise ValueError("Confluence configuration is incomplete")
        self._config = config
        self._timeout = timeout
        self._session = requests.Session()
        self._session.auth = (config.email, config.api_token)
        self._session.headers.update({"Accept": "application/json"})

    def find_attachment(self, *, page_id: str, name: str) -> ConfluenceAttachment | None:
        url = f"{self._config.api_root()}/content/{page_id}/child/attachment"
        params = {"filename": name, "limit": 25}
        resp = self._session.get(url, params=params, timeout=self._timeout)
        resp.raise_for_status()
        data = resp.json()
        for item in data.get("results", []):
            attachment = _parse_attachment_payload(item)
            if attachment and attachment.title == name:
                return attachment
        return None

    def upload_attachment(
        self,
        *,
        page_id: str,
        name: str,
        data: bytes,
        content_type: str | None = None,
        comment: str | None = None,
    ) -> ConfluenceAttachment:
        url = f"{self._config.api_root()}/content/{page_id}/child/attachment"
        return self._push_attachment(url=url, name=name, data=data, content_type=content_type, comment=comment)

    def replace_attachment(
        self,
        *,
        page_id: str,
        attachment_id: str,
        name: str,
        data: bytes,
        content_type: str | None = None,
        comment: str | None = None,
    ) -> ConfluenceAttachment:
        url = f"{self._config.api_root()}/content/{page_id}/child/attachment/{attachment_id}/data"
        return self._push_attachment(url=url, name=name, data=data, content_type=content_type, comment=comment)

    async def upload_attachment_async(self, **kwargs: Any) -> ConfluenceAttachment:
        return await asyncio.to_thread(self.upload_attachment, **kwargs)

    def _push_attachment(
        self,
        *,
        url: str,
        name: str,
        data: bytes,
        content_type: str | None,
        comment: str | None,
    ) -> ConfluenceAttachment:
        files = {"file": (name, data, content_type or "application/octet-stream")}
        payload = {"minorEdit": "true"}
        if comment:
            payload["comment"] = comment
        response = self._session.post(
            url,
            headers={"X-Atlassian-Token": "nocheck"},
            files=files,
            data=payload,
            timeout=self._timeout,
        )
        response.raise_for_status()
        attachment = _parse_attachment_payload(response.json())
        if attachment is None:
            raise RuntimeError("Confluence response did not contain attachment metadata")
        return attachment

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> ConfluenceClient:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def _parse_attachment_payload(data: Mapping[str, Any] | None) -> ConfluenceAttachment | None:
    if not data:
        return None
    if "results" in data and isinstance(data["results"], list):
        for item in data["results"]:
            parsed = _parse_attachment_payload(item)
            if parsed:
                return parsed
        return None
    attachment_id = str(data.get("id")) if data.get("id") is not None else None
    title = data.get("title") or data.get("filename")
    version_block = data.get("version") if isinstance(data.get("version"), Mapping) else {}
    version = version_block.get("number") if isinstance(version_block, Mapping) else data.get("version")
    links = data.get("_links") if isinstance(data.get("_links"), Mapping) else {}
    base = links.get("base") if isinstance(links, Mapping) else None
    download_url = links.get("download") if isinstance(links, Mapping) else None
    webui = links.get("webui") if isinstance(links, Mapping) else None
    download_href = f"{base}{download_url}" if base and download_url else download_url
    web_href = f"{base}{webui}" if base and webui else webui
    created_at = _parse_date(data.get("created"))
    updated_at = _parse_date(data.get("_updateDate")) or _parse_date(data.get("lastModified"))
    media_type = None
    metadata = data.get("metadata")
    if isinstance(metadata, Mapping):
        media_type = metadata.get("mediaType") or metadata.get("media-type")
    if not attachment_id or not title:
        return None
    version_num = int(version) if version not in (None, "") else None
    return ConfluenceAttachment(
        id=attachment_id,
        title=str(title),
        version=version_num,
        download_url=str(download_href) if download_href else None,
        web_url=str(web_href) if web_href else None,
        media_type=str(media_type) if media_type else None,
        created_at=created_at,
        updated_at=updated_at,
    )


def _parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


__all__ = ["ConfluenceClient", "ConfluenceClientConfig"]
