"""Confluence REST adapter with attachment helpers."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import requests


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

    def upload_attachment(
        self,
        *,
        page_id: str,
        name: str,
        data: bytes,
        comment: str | None = None,
    ) -> dict[str, Any]:
        params = {"minorEdit": "true"}
        if comment:
            params["comment"] = comment
        url = f"{self._config.api_root()}/content/{page_id}/child/attachment"
        response = self._session.post(
            url,
            headers={"X-Atlassian-Token": "nocheck"},
            files={"file": (name, data)},
            data=params,
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response.json()

    async def upload_attachment_async(self, **kwargs: Any) -> dict[str, Any]:
        return await asyncio.to_thread(self.upload_attachment, **kwargs)

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "ConfluenceClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


__all__ = ["ConfluenceClient", "ConfluenceClientConfig"]
