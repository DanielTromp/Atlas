"""Jira REST adapter with attachment upload support."""

from __future__ import annotations

import asyncio
import mimetypes
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import unquote, urlparse

import requests

from infrastructure_atlas.domain.integrations import JiraAttachment


class JiraError(Exception):
    """Base error for Jira client operations."""


class JiraConfigError(JiraError):
    """Invalid or missing configuration."""


class JiraAuthError(JiraError):
    """Authentication failed."""


class JiraAPIError(JiraError):
    """API request failed."""


@dataclass(slots=True)
class JiraClientConfig:
    """Configuration for Jira client."""

    base_url: str
    email: str
    api_token: str

    def api_root(self) -> str:
        """Return the REST API v3 root URL."""
        base = self.base_url.rstrip("/")
        return f"{base}/rest/api/3"


class JiraClient:
    """Client for Jira REST API operations including attachments."""

    def __init__(self, config: JiraClientConfig, *, timeout: float = 60.0) -> None:
        if not (config.base_url and config.email and config.api_token):
            raise JiraConfigError("Jira configuration is incomplete")
        self._config = config
        self._timeout = timeout
        self._session = requests.Session()
        self._session.auth = (config.email, config.api_token)
        self._session.headers.update({"Accept": "application/json"})

    def upload_attachment(
        self,
        *,
        issue_id_or_key: str,
        filename: str,
        data: bytes,
        content_type: str | None = None,
    ) -> JiraAttachment:
        """
        Upload an attachment to a Jira issue.

        Args:
            issue_id_or_key: The issue key (e.g., "ESD-40185") or ID
            filename: Name for the attachment file
            data: File content as bytes
            content_type: MIME type (auto-detected if not provided)

        Returns:
            JiraAttachment with metadata about the uploaded file

        Raises:
            JiraAuthError: If authentication fails
            JiraAPIError: If the API request fails
        """
        url = f"{self._config.api_root()}/issue/{issue_id_or_key}/attachments"

        # Auto-detect content type if not provided
        if not content_type:
            content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

        files = {"file": (filename, data, content_type)}

        try:
            response = self._session.post(
                url,
                headers={"X-Atlassian-Token": "no-check"},
                files=files,
                timeout=self._timeout,
            )

            if response.status_code == 401:
                raise JiraAuthError("Authentication failed: check email and API token")
            if response.status_code == 403:
                raise JiraAPIError(f"Forbidden: missing attachment permissions for issue {issue_id_or_key}")
            if response.status_code == 404:
                raise JiraAPIError(f"Issue not found: {issue_id_or_key}")

            response.raise_for_status()

            # Jira returns an array of attachments
            attachments = response.json()
            if not attachments or not isinstance(attachments, list):
                raise JiraAPIError("Unexpected response format: expected attachment array")

            return _parse_attachment_payload(attachments[0])

        except requests.HTTPError as ex:
            msg = getattr(ex.response, "text", str(ex))[:500]
            raise JiraAPIError(f"Failed to upload attachment: {msg}") from ex
        except requests.RequestException as ex:
            raise JiraAPIError(f"Request failed: {ex}") from ex

    def download_and_upload_attachment(
        self,
        *,
        issue_id_or_key: str,
        source_url: str,
        filename: str | None = None,
        download_timeout: float = 120.0,
    ) -> JiraAttachment:
        """
        Download a file from a URL and upload it as an attachment to a Jira issue.

        Args:
            issue_id_or_key: The issue key (e.g., "ESD-40185") or ID
            source_url: URL to download the file from
            filename: Optional filename override (auto-detected from URL/headers if not provided)
            download_timeout: Timeout for downloading the source file

        Returns:
            JiraAttachment with metadata about the uploaded file

        Raises:
            JiraAPIError: If download or upload fails
        """
        # Download the file with browser-like headers to avoid bot detection
        download_headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        try:
            download_response = requests.get(
                source_url,
                headers=download_headers,
                timeout=download_timeout,
                stream=True,
                allow_redirects=True,
            )
            if download_response.status_code == 403:
                raise JiraAPIError(
                    f"Access denied (403) downloading from {source_url[:100]}... "
                    "The URL may require authentication, have expired, or block automated access."
                )
            if download_response.status_code == 401:
                raise JiraAPIError(
                    f"Authentication required (401) for {source_url[:100]}... The URL requires login credentials."
                )
            download_response.raise_for_status()
        except JiraAPIError:
            raise
        except requests.RequestException as ex:
            raise JiraAPIError(f"Failed to download file from {source_url[:100]}...: {ex}") from ex

        # Determine filename
        resolved_filename = filename
        if not resolved_filename:
            resolved_filename = _extract_filename(download_response, source_url)

        # Get content type from download response
        content_type = download_response.headers.get("Content-Type")

        # Read the content
        data = download_response.content

        # Upload to Jira
        return self.upload_attachment(
            issue_id_or_key=issue_id_or_key,
            filename=resolved_filename,
            data=data,
            content_type=content_type,
        )

    async def upload_attachment_async(self, **kwargs: Any) -> JiraAttachment:
        """Async wrapper for upload_attachment."""
        return await asyncio.to_thread(self.upload_attachment, **kwargs)

    async def download_and_upload_attachment_async(self, **kwargs: Any) -> JiraAttachment:
        """Async wrapper for download_and_upload_attachment."""
        return await asyncio.to_thread(self.download_and_upload_attachment, **kwargs)

    def list_attachments(self, issue_id_or_key: str) -> list[JiraAttachment]:
        """
        List all attachments on an issue.

        Args:
            issue_id_or_key: The issue key or ID

        Returns:
            List of JiraAttachment objects
        """
        url = f"{self._config.api_root()}/issue/{issue_id_or_key}"
        params = {"fields": "attachment"}

        try:
            response = self._session.get(url, params=params, timeout=self._timeout)
            if response.status_code == 404:
                raise JiraAPIError(f"Issue not found: {issue_id_or_key}")
            response.raise_for_status()

            data = response.json()
            attachments = data.get("fields", {}).get("attachment", [])
            return [_parse_attachment_payload(a) for a in attachments if a]

        except requests.HTTPError as ex:
            msg = getattr(ex.response, "text", str(ex))[:500]
            raise JiraAPIError(f"Failed to list attachments: {msg}") from ex

    def delete_attachment(self, attachment_id: str) -> bool:
        """
        Delete an attachment by ID.

        Args:
            attachment_id: The attachment ID

        Returns:
            True if deleted successfully
        """
        url = f"{self._config.api_root()}/attachment/{attachment_id}"

        try:
            response = self._session.delete(url, timeout=self._timeout)
            if response.status_code == 404:
                raise JiraAPIError(f"Attachment not found: {attachment_id}")
            response.raise_for_status()
            return True

        except requests.HTTPError as ex:
            msg = getattr(ex.response, "text", str(ex))[:500]
            raise JiraAPIError(f"Failed to delete attachment: {msg}") from ex

    def close(self) -> None:
        """Close the session."""
        self._session.close()

    def __enter__(self) -> JiraClient:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def _extract_filename(response: requests.Response, url: str) -> str:
    """
    Extract filename from response headers or URL.

    Priority:
    1. Content-Disposition header
    2. URL path (last segment)
    3. Default fallback
    """
    # Try Content-Disposition header
    content_disposition = response.headers.get("Content-Disposition", "")
    if content_disposition:
        # Try filename*= (RFC 5987 encoding)
        match = re.search(r"filename\*=(?:UTF-8'')?([^;\s]+)", content_disposition, re.IGNORECASE)
        if match:
            return unquote(match.group(1))

        # Try filename="..." (quoted, may contain spaces)
        match = re.search(r'filename="([^"]+)"', content_disposition, re.IGNORECASE)
        if match:
            return unquote(match.group(1))

        # Try filename=... (unquoted, no spaces)
        match = re.search(r"filename=([^;\s]+)", content_disposition, re.IGNORECASE)
        if match:
            return unquote(match.group(1))

    # Fall back to URL path
    parsed = urlparse(url)
    path = parsed.path
    if path:
        # Get last path segment
        segments = [s for s in path.split("/") if s]
        if segments:
            filename = unquote(segments[-1])
            # Remove query params if accidentally included
            if "?" in filename:
                filename = filename.split("?")[0]
            if filename:
                return filename

    # Last resort: generate a name based on content type
    content_type = response.headers.get("Content-Type", "")
    ext = mimetypes.guess_extension(content_type.split(";")[0].strip()) or ".bin"
    return f"attachment{ext}"


def _parse_attachment_payload(data: Mapping[str, Any]) -> JiraAttachment:
    """
    Parse Jira attachment API response into JiraAttachment.

    Example response:
    {
        "self": "https://your-domain.atlassian.net/rest/api/3/attachment/10000",
        "id": "10000",
        "filename": "Power Report.xlsx",
        "author": {"displayName": "John Doe", ...},
        "created": "2026-01-12T00:00:00.000+0000",
        "size": 12345,
        "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "content": "https://your-domain.atlassian.net/secure/attachment/10000/Power+Report.xlsx"
    }
    """
    attachment_id = str(data.get("id", ""))
    filename = str(data.get("filename", ""))
    size = int(data.get("size", 0))
    mime_type = data.get("mimeType")
    content_url = data.get("content")
    self_url = data.get("self")

    # Author info
    author = data.get("author")
    author_display_name = None
    if isinstance(author, Mapping):
        author_display_name = author.get("displayName")

    # Parse created timestamp
    created_at = None
    created_str = data.get("created")
    if created_str:
        try:
            # Handle Jira's format: 2026-01-12T00:00:00.000+0000
            created_at = datetime.fromisoformat(str(created_str).replace("+0000", "+00:00").replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass

    return JiraAttachment(
        id=attachment_id,
        filename=filename,
        size=size,
        mime_type=mime_type,
        content_url=content_url,
        self_url=self_url,
        author_display_name=author_display_name,
        created_at=created_at,
    )


def create_jira_client_from_env() -> JiraClient:
    """
    Create a JiraClient from environment variables.

    Uses: ATLASSIAN_BASE_URL, ATLASSIAN_EMAIL, ATLASSIAN_API_TOKEN
    Falls back to: JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN
    """
    base_url = os.getenv("ATLASSIAN_BASE_URL", "").strip() or os.getenv("JIRA_BASE_URL", "").strip()
    email = os.getenv("ATLASSIAN_EMAIL", "").strip() or os.getenv("JIRA_EMAIL", "").strip()
    api_token = os.getenv("ATLASSIAN_API_TOKEN", "").strip() or os.getenv("JIRA_API_TOKEN", "").strip()

    if not (base_url and email and api_token):
        raise JiraConfigError(
            "Missing Jira configuration. Set ATLASSIAN_BASE_URL, ATLASSIAN_EMAIL, "
            "ATLASSIAN_API_TOKEN environment variables."
        )

    config = JiraClientConfig(base_url=base_url, email=email, api_token=api_token)
    return JiraClient(config)


__all__ = [
    "JiraAPIError",
    "JiraAuthError",
    "JiraClient",
    "JiraClientConfig",
    "JiraConfigError",
    "JiraError",
    "create_jira_client_from_env",
]
