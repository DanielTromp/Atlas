"""Lightweight client for Foreman REST API."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import TracebackType
from typing import Any

import requests
from requests import Session

from infrastructure_atlas.infrastructure.caching import CacheMetrics, TTLCache

logger = logging.getLogger(__name__)


class ForemanClientError(RuntimeError):
    """Base error raised for Foreman client failures."""


class ForemanAuthError(ForemanClientError):
    """Raised when authentication against Foreman fails."""


class ForemanAPIError(ForemanClientError):
    """Raised when Foreman returns an unexpected response."""


@dataclass(slots=True)
class ForemanClientConfig:
    """Connection parameters for the Foreman API client."""

    base_url: str
    username: str
    token: str  # Personal Access Token
    verify_ssl: bool = True
    timeout: int = 30
    cache_ttl_seconds: float = 300.0  # 5 minutes default cache


class ForemanClient:
    """REST client for Foreman API interactions with caching."""

    _API_VERSION = "/api/v2"
    _HOSTS_ENDPOINT = "/api/v2/hosts"
    _STATUS_ENDPOINT = "/api/v2/status"
    _PER_PAGE = 1000  # Foreman API max per_page

    def __init__(self, config: ForemanClientConfig) -> None:
        self._config = config
        self._base_url = config.base_url.rstrip("/")
        self._timeout = max(int(config.timeout or 30), 1)
        self._session: Session = requests.Session()
        self._session.verify = bool(config.verify_ssl)
        # Foreman 1.24.3 uses HTTP Basic Auth with username:token
        self._session.auth = (config.username, config.token)
        self._session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )
        # Set up caching
        self._hosts_cache = TTLCache[str, list[Mapping[str, Any]]](
            ttl_seconds=config.cache_ttl_seconds,
            name=f"foreman.hosts.{config.base_url}",
        )
        self._host_details_cache = TTLCache[str, Mapping[str, Any]](
            ttl_seconds=config.cache_ttl_seconds,
            name=f"foreman.host_details.{config.base_url}",
        )
        self._puppet_classes_cache = TTLCache[str, list[Mapping[str, Any]]](
            ttl_seconds=config.cache_ttl_seconds,
            name=f"foreman.puppet_classes.{config.base_url}",
        )
        self._puppet_parameters_cache = TTLCache[str, list[Mapping[str, Any]]](
            ttl_seconds=config.cache_ttl_seconds,
            name=f"foreman.puppet_parameters.{config.base_url}",
        )
        self._puppet_facts_cache = TTLCache[str, Mapping[str, Any]](
            ttl_seconds=config.cache_ttl_seconds,
            name=f"foreman.puppet_facts.{config.base_url}",
        )
        if not config.verify_ssl:
            try:  # optional dependency
                from urllib3 import disable_warnings
                from urllib3.exceptions import InsecureRequestWarning

                disable_warnings(InsecureRequestWarning)
            except Exception:  # pragma: no cover - urllib3 optional
                logger.debug("Unable to disable urllib3 warnings", exc_info=True)

    def __enter__(self) -> ForemanClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the HTTP session."""
        self._session.close()

    def invalidate_cache(self) -> None:
        """Invalidate all cached data."""
        self._hosts_cache.invalidate()
        self._host_details_cache.invalidate()
        self._puppet_classes_cache.invalidate()
        self._puppet_parameters_cache.invalidate()
        self._puppet_facts_cache.invalidate()

    def cache_metrics(self) -> Mapping[str, CacheMetrics]:
        """Get cache performance metrics."""
        return {
            "hosts": self._hosts_cache.snapshot_metrics(),
            "host_details": self._host_details_cache.snapshot_metrics(),
            "puppet_classes": self._puppet_classes_cache.snapshot_metrics(),
            "puppet_parameters": self._puppet_parameters_cache.snapshot_metrics(),
            "puppet_facts": self._puppet_facts_cache.snapshot_metrics(),
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        ok_status: Sequence[int] | None = None,
        null_status: Sequence[int] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Make an HTTP request to the Foreman API."""
        url = f"{self._base_url}{path}"
        ok_codes = tuple(ok_status or (200,))
        null_codes = tuple(null_status or ())
        try:
            response = self._session.request(method, url, timeout=self._timeout, **kwargs)
        except requests.RequestException as exc:  # pragma: no cover - network error
            raise ForemanClientError(f"Error communicating with Foreman: {exc}") from exc

        if response.status_code in (401, 403):
            raise ForemanAuthError("Foreman rejected the supplied token")

        if response.status_code in null_codes:
            return None

        if response.status_code not in ok_codes:
            message = self._extract_error_message(response)
            raise ForemanAPIError(f"Foreman returned status {response.status_code}: {message}")

        if not response.content:
            return None

        try:
            return response.json()
        except ValueError:
            return None

    @staticmethod
    def _extract_error_message(response: requests.Response) -> str:
        """Extract error message from API response."""
        if not response.content:
            return "no response body"
        try:
            payload = response.json()
        except ValueError:
            return response.text.strip()
        if isinstance(payload, Mapping):
            error = payload.get("error") or payload.get("message") or payload.get("errors")
            if isinstance(error, str):
                return error
            if isinstance(error, Mapping):
                message = error.get("message") or error.get("full_messages")
                if isinstance(message, str):
                    return message
                if isinstance(message, Sequence):
                    parts = [str(item) for item in message]
                    if parts:
                        return "; ".join(parts)
        return response.text.strip() or "unknown error"

    def test_connection(self) -> bool:
        """Test connectivity to Foreman API.

        Returns:
            True if connection successful, raises exception otherwise.
        """
        try:
            self._request("GET", self._STATUS_ENDPOINT)
            return True
        except ForemanAuthError:
            raise
        except ForemanClientError:
            raise
        except Exception as exc:
            raise ForemanClientError(f"Failed to connect to Foreman: {exc}") from exc

    def list_hosts(self, *, search: str | None = None, force_refresh: bool = False) -> list[Mapping[str, Any]]:
        """List all hosts from Foreman with pagination support.

        Args:
            search: Optional search query string.
            force_refresh: If True, bypass cache and fetch fresh data.

        Returns:
            List of all host records (fetches all pages automatically).
        """
        cache_key = f"hosts:{search or 'all'}"

        if force_refresh:
            self._hosts_cache.invalidate(cache_key)

        return self._hosts_cache.get(cache_key, lambda: self._fetch_all_hosts(search))

    def _fetch_all_hosts(self, search: str | None = None) -> list[Mapping[str, Any]]:
        """Fetch all hosts by paginating through all pages."""
        all_hosts: list[Mapping[str, Any]] = []
        page = 1
        per_page = self._PER_PAGE

        while True:
            params: dict[str, Any] = {"page": page, "per_page": per_page}
            if search:
                params["search"] = search

            payload = self._request("GET", self._HOSTS_ENDPOINT, params=params)
            if not isinstance(payload, Mapping):
                break

            results = payload.get("results") or []
            if isinstance(results, list):
                all_hosts.extend(item for item in results if isinstance(item, Mapping))

            # Check if we've fetched all pages
            total = payload.get("total") or payload.get("subtotal")
            if isinstance(total, int) and len(all_hosts) >= total:
                break
            if not results or len(results) < per_page:
                break

            page += 1

        return all_hosts

    def get_host(self, host_id: int | str) -> Mapping[str, Any] | None:
        """Get a specific host by ID (alias for get_host_detail for backward compatibility).

        Args:
            host_id: Host ID or name.

        Returns:
            Host record or None if not found.
        """
        return self.get_host_detail(host_id)

    def get_host_detail(self, host_id: int | str, *, force_refresh: bool = False) -> Mapping[str, Any] | None:
        """Get detailed host information including Puppet configuration.

        Args:
            host_id: Host ID or name.
            force_refresh: If True, bypass cache and fetch fresh data.

        Returns:
            Detailed host record or None if not found.
        """
        cache_key = f"host:{host_id}"
        if force_refresh:
            self._host_details_cache.invalidate(cache_key)

        def _fetch() -> Mapping[str, Any] | None:
            payload = self._request(
                "GET",
                f"{self._HOSTS_ENDPOINT}/{host_id}",
                null_status=(404,),
            )
            return payload if isinstance(payload, Mapping) else None

        return self._host_details_cache.get(cache_key, _fetch)

    def get_host_puppet_classes(self, host_id: int | str, *, force_refresh: bool = False) -> list[Mapping[str, Any]]:
        """Get Puppet classes assigned to a host.

        Args:
            host_id: Host ID or name.
            force_refresh: If True, bypass cache and fetch fresh data.

        Returns:
            List of Puppet class records.
        """
        cache_key = f"puppet_classes:{host_id}"
        if force_refresh:
            self._puppet_classes_cache.invalidate(cache_key)

        def _fetch() -> list[Mapping[str, Any]]:
            payload = self._request(
                "GET",
                f"{self._HOSTS_ENDPOINT}/{host_id}/puppetclasses",
                null_status=(404,),
            )
            if not isinstance(payload, Mapping):
                return []
            results = payload.get("results")
            if isinstance(results, Mapping):
                # Results is a dict keyed by class name, convert to list
                classes = []
                for class_name, class_list in results.items():
                    if isinstance(class_list, list):
                        classes.extend(class_list)
                    elif isinstance(class_list, Mapping):
                        classes.append(class_list)
                return classes
            if isinstance(results, list):
                return [item for item in results if isinstance(item, Mapping)]
            return []

        return self._puppet_classes_cache.get(cache_key, _fetch)

    def get_host_puppet_parameters(self, host_id: int | str, *, force_refresh: bool = False) -> list[Mapping[str, Any]]:
        """Get Puppet parameters (user configs) for a host.

        Args:
            host_id: Host ID or name.
            force_refresh: If True, bypass cache and fetch fresh data.

        Returns:
            List of parameter records.
        """
        cache_key = f"puppet_parameters:{host_id}"
        if force_refresh:
            self._puppet_parameters_cache.invalidate(cache_key)

        def _fetch() -> list[Mapping[str, Any]]:
            payload = self._request(
                "GET",
                f"{self._HOSTS_ENDPOINT}/{host_id}/parameters",
                null_status=(404,),
            )
            if not isinstance(payload, Mapping):
                return []
            results = payload.get("results") or []
            if isinstance(results, list):
                return [item for item in results if isinstance(item, Mapping)]
            return []

        return self._puppet_parameters_cache.get(cache_key, _fetch)

    def get_host_puppet_facts(self, host_id: int | str, *, force_refresh: bool = False) -> Mapping[str, Any]:
        """Get Puppet facts for a host.

        Args:
            host_id: Host ID or name.
            force_refresh: If True, bypass cache and fetch fresh data.

        Returns:
            Dictionary of fact name -> fact value.
        """
        cache_key = f"puppet_facts:{host_id}"
        if force_refresh:
            self._puppet_facts_cache.invalidate(cache_key)

        def _fetch() -> Mapping[str, Any]:
            payload = self._request(
                "GET",
                f"{self._HOSTS_ENDPOINT}/{host_id}/facts",
                null_status=(404,),
            )
            if not isinstance(payload, Mapping):
                return {}
            results = payload.get("results") or {}
            if isinstance(results, Mapping):
                # Facts are nested by hostname, get the first host's facts
                for hostname, facts in results.items():
                    if isinstance(facts, Mapping):
                        return facts
            return {}

        return self._puppet_facts_cache.get(cache_key, _fetch)

    def get_host_puppet_status(self, host_id: int | str) -> Mapping[str, Any] | None:
        """Get Puppet status and proxy information for a host.

        Args:
            host_id: Host ID or name.

        Returns:
            Dictionary with puppet_status, puppet_proxy_name, puppet_ca_proxy_name, etc.
        """
        host_detail = self.get_host_detail(host_id)
        if not host_detail:
            return None

        return {
            "puppet_status": host_detail.get("puppet_status"),
            "puppet_proxy_name": host_detail.get("puppet_proxy_name"),
            "puppet_ca_proxy_name": host_detail.get("puppet_ca_proxy_name"),
            "puppet_proxy_id": host_detail.get("puppet_proxy_id"),
            "puppet_ca_proxy_id": host_detail.get("puppet_ca_proxy_id"),
            "configuration_status": host_detail.get("configuration_status"),
            "configuration_status_label": host_detail.get("configuration_status_label"),
        }


__all__ = ["ForemanClient", "ForemanClientConfig", "ForemanClientError", "ForemanAuthError", "ForemanAPIError"]
