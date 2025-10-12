"""Lightweight client for VMware vCenter REST APIs."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import TracebackType
from typing import Any

import requests
from requests import Session

logger = logging.getLogger(__name__)


class VCenterClientError(RuntimeError):
    """Base error raised for vCenter client failures."""


class VCenterAuthError(VCenterClientError):
    """Raised when authentication against vCenter fails."""


class VCenterAPIError(VCenterClientError):
    """Raised when vCenter returns an unexpected response."""


@dataclass(slots=True)
class VCenterClientConfig:
    """Connection parameters for the vCenter API client."""

    base_url: str
    username: str
    password: str
    verify_ssl: bool = True
    timeout: int = 30


class VCenterClient:
    """Minimal REST wrapper for the vCenter inventory endpoints."""

    _SESSION_ENDPOINT = "/rest/com/vmware/cis/session"
    _VM_LIST_ENDPOINT = "/rest/vcenter/vm"
    _VM_GUEST_INTERFACES_ENDPOINT = "/rest/vcenter/vm/{vm}/guest/networking/interfaces"
    _DATACENTER_LIST_ENDPOINT = "/rest/vcenter/datacenter"
    _CLUSTER_LIST_ENDPOINT = "/rest/vcenter/cluster"
    _HOST_LIST_ENDPOINT = "/rest/vcenter/host"
    _RESOURCE_POOL_LIST_ENDPOINT = "/rest/vcenter/resource-pool"
    _FOLDER_LIST_ENDPOINT = "/rest/vcenter/folder"
    _VM_CUSTOM_ATTRIBUTES_ENDPOINT = "/rest/vcenter/vm/{vm}/custom-attributes"
    _VM_GUEST_IDENTITY_ENDPOINT = "/rest/vcenter/vm/{vm}/guest/identity"
    _VM_TOOLS_ENDPOINT = "/rest/vcenter/vm/{vm}/tools"
    _TAG_LIST_ENDPOINT = "/rest/com/vmware/cis/tagging/tag-association?~action=list-attached-tags"
    _TAG_INFO_ENDPOINT = "/rest/com/vmware/cis/tagging/tag/id:{tag_id}"

    def __init__(self, config: VCenterClientConfig) -> None:
        self._config = config
        self._base_url = config.base_url.rstrip("/")
        self._timeout = max(int(config.timeout or 30), 1)
        self._session: Session = requests.Session()
        self._session.verify = bool(config.verify_ssl)
        self._session.headers.update({"Accept": "application/json"})
        self._authenticated = False
        self._token: str | None = None
        self._tag_cache: dict[str, str] = {}
        self._server_guid: str | None = None
        if not config.verify_ssl:
            try:  # optional dependency
                from urllib3 import disable_warnings
                from urllib3.exceptions import InsecureRequestWarning

                disable_warnings(InsecureRequestWarning)
            except Exception:  # pragma: no cover - urllib3 optional
                logger.debug("Unable to disable urllib3 warnings", exc_info=True)

    def __enter__(self) -> VCenterClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._session.close()

    # Authentication -----------------------------------------------------------------
    def _login(self) -> None:
        url = f"{self._base_url}{self._SESSION_ENDPOINT}"
        try:
            response = self._session.post(
                url,
                auth=(self._config.username, self._config.password),
                timeout=self._timeout,
            )
        except requests.RequestException as exc:  # pragma: no cover - network error
            raise VCenterClientError("Failed to connect to vCenter session endpoint") from exc

        if response.status_code in (401, 403):
            raise VCenterAuthError("vCenter rejected the supplied credentials")

        if response.status_code not in (200, 201):
            raise VCenterClientError(
                f"Unexpected status {response.status_code} while establishing vCenter session",
            )

        token: str | None = None
        if response.content:
            try:
                data = response.json()
            except ValueError:
                data = {}
            token = data.get("value") if isinstance(data, Mapping) else None
        if not token:
            token = response.headers.get("vmware-api-session-id")
        if not token:
            raise VCenterClientError("vCenter session response did not include a session token")

        self._token = token
        self._session.headers["vmware-api-session-id"] = token
        self._authenticated = True

    def _ensure_session(self) -> None:
        if not self._authenticated:
            self._login()

    # Low-level HTTP helpers ---------------------------------------------------------
    def _request(
        self,
        method: str,
        path: str,
        *,
        ok_status: Sequence[int] | None = None,
        null_status: Sequence[int] | None = None,
        **kwargs: Any,
    ) -> Any:
        self._ensure_session()
        url = f"{self._base_url}{path}"
        ok_codes = tuple(ok_status or (200,))
        null_codes = tuple(null_status or ())
        try:
            response = self._session.request(method, url, timeout=self._timeout, **kwargs)
        except requests.RequestException as exc:  # pragma: no cover - network error
            raise VCenterClientError(f"Error communicating with vCenter: {exc}") from exc

        if response.status_code in (401, 403):
            self._authenticated = False
            raise VCenterAuthError("vCenter session expired or credentials invalid")

        if response.status_code in null_codes:
            return None

        if response.status_code not in ok_codes:
            message = self._extract_error_message(response)
            raise VCenterAPIError(
                f"vCenter returned status {response.status_code}: {message}",
            )

        if not response.content:
            return None

        try:
            return response.json()
        except ValueError:
            return None

    @staticmethod
    def _extract_error_message(response: requests.Response) -> str:
        if not response.content:
            return "no response body"
        try:
            payload = response.json()
        except ValueError:
            return response.text.strip()
        detail = payload.get("value") if isinstance(payload, Mapping) else None
        if isinstance(detail, Mapping):
            message = detail.get("messages") or detail.get("message")
            if isinstance(message, str):
                return message
            if isinstance(message, Sequence):
                parts = [str(item) for item in message]
                if parts:
                    return "; ".join(parts)
        return response.text.strip() or "unknown error"

    # Public API ---------------------------------------------------------------------
    def list_vms(self) -> list[Mapping[str, Any]]:
        payload = self._request("GET", self._VM_LIST_ENDPOINT)
        if not isinstance(payload, Mapping):
            return []
        values = payload.get("value")
        if isinstance(values, list):
            return [item for item in values if isinstance(item, Mapping)]
        return []

    def get_vm(self, vm_id: str) -> Mapping[str, Any] | None:
        if not vm_id:
            return None
        payload = self._request(
            "GET",
            f"{self._VM_LIST_ENDPOINT}/{vm_id}",
            null_status=(404,),
        )
        if not isinstance(payload, Mapping):
            return None
        value = payload.get("value")
        return value if isinstance(value, Mapping) else None

    def get_vm_guest_interfaces(self, vm_id: str) -> list[Mapping[str, Any]]:
        if not vm_id:
            return []
        payload = self._request(
            "GET",
            self._VM_GUEST_INTERFACES_ENDPOINT.format(vm=vm_id),
            null_status=(401, 403, 404, 500, 501, 503),
        )
        if not isinstance(payload, Mapping):
            return []
        value = payload.get("value")
        if isinstance(value, list):
            return [item for item in value if isinstance(item, Mapping)]
        return []

    def list_vm_custom_attributes(self, vm_id: str) -> dict[str, str]:
        if not vm_id:
            return {}
        payload = self._request(
            "GET",
            self._VM_CUSTOM_ATTRIBUTES_ENDPOINT.format(vm=vm_id),
            null_status=(404, 500, 501, 503),
        )
        if not isinstance(payload, Mapping):
            return {}
        values = payload.get("value")
        if not isinstance(values, list):
            return {}
        result: dict[str, str] = {}
        for item in values:
            if not isinstance(item, Mapping):
                continue
            key = item.get("name") or item.get("key")
            value = item.get("value")
            if isinstance(key, str) and key.strip():
                result[key.strip()] = str(value).strip() if value is not None else ""
        return result

    def get_vm_guest_identity(self, vm_id: str) -> Mapping[str, Any] | None:
        if not vm_id:
            return None
        payload = self._request(
            "GET",
            self._VM_GUEST_IDENTITY_ENDPOINT.format(vm=vm_id),
            null_status=(401, 403, 404, 500, 501, 503),
        )
        if not isinstance(payload, Mapping):
            return None
        identity = payload.get("value")
        return identity if isinstance(identity, Mapping) else None

    def get_vm_tools(self, vm_id: str) -> Mapping[str, Any] | None:
        if not vm_id:
            return None
        payload = self._request(
            "GET",
            self._VM_TOOLS_ENDPOINT.format(vm=vm_id),
            null_status=(401, 403, 404, 500, 501, 503),
        )
        if not isinstance(payload, Mapping):
            return None
        tools = payload.get("value")
        return tools if isinstance(tools, Mapping) else None

    def _get_tag_name(self, tag_id: str) -> str | None:
        cached = self._tag_cache.get(tag_id)
        if cached:
            return cached
        payload = self._request(
            "GET",
            self._TAG_INFO_ENDPOINT.format(tag_id=tag_id),
            null_status=(404, 500, 501, 503),
        )
        if not isinstance(payload, Mapping):
            return None
        tag = payload.get("value")
        if isinstance(tag, Mapping):
            name = tag.get("name")
            if isinstance(name, str) and name.strip():
                cleaned = name.strip()
                self._tag_cache[tag_id] = cleaned
                return cleaned
        return None

    def list_vm_tags(self, vm_id: str) -> tuple[str, ...]:
        if not vm_id:
            return ()
        payload = self._request(
            "POST",
            self._TAG_LIST_ENDPOINT,
            json={"object_id": {"id": vm_id, "type": "VirtualMachine"}},
            ok_status=(200,),
            null_status=(400, 401, 403, 404, 500, 501, 503),
        )
        if not isinstance(payload, Mapping):
            return ()
        tag_ids = payload.get("value")
        if not isinstance(tag_ids, list):
            return ()
        names: list[str] = []
        for tag_id in tag_ids:
            if not isinstance(tag_id, str):
                continue
            name = self._get_tag_name(tag_id)
            if name:
                names.append(name)
        return tuple(names)

    def get_server_guid(self) -> str | None:
        cached = self._server_guid
        if cached:
            return cached

        self._ensure_session()
        url = f"{self._base_url}/sdk"
        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "Accept": "text/xml",
            "SOAPAction": "urn:vim25/ServiceInstance/RetrieveServiceContent",
        }
        envelope = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:vim25="urn:vim25">'
            "<soapenv:Body>"
            '<vim25:RetrieveServiceContent>'
            '<vim25:_this type="ServiceInstance">ServiceInstance</vim25:_this>'
            "</vim25:RetrieveServiceContent>"
            "</soapenv:Body>"
            "</soapenv:Envelope>"
        )

        server_guid: str | None = None

        try:
            response = self._session.post(url, data=envelope, headers=headers, timeout=self._timeout)
        except requests.RequestException:  # pragma: no cover - network error
            logger.debug("Failed to retrieve vCenter service content", exc_info=True)
        else:
            if response.status_code != 200:
                logger.debug(
                    "Unexpected status %s retrieving service content: %s",
                    response.status_code,
                    response.text.strip(),
                )
            else:
                content = response.text
                marker_start = "<instanceUuid>"
                marker_end = "</instanceUuid>"
                start = content.find(marker_start)
                if start != -1:
                    start += len(marker_start)
                    end = content.find(marker_end, start)
                    if end != -1:
                        candidate = content[start:end].strip()
                        if candidate:
                            server_guid = candidate

        if not server_guid:
            return None

        self._server_guid = server_guid
        return server_guid

    def _list_named_resources(self, path: str, identifier_key: str) -> dict[str, str]:
        payload = self._request("GET", path)
        if not isinstance(payload, Mapping):
            return {}
        values = payload.get("value")
        if not isinstance(values, list):
            return {}
        mapping: dict[str, str] = {}
        for item in values:
            if not isinstance(item, Mapping):
                continue
            identifier = item.get(identifier_key)
            name = item.get("name") or item.get("display_name")
            if isinstance(identifier, str):
                ident = identifier.strip()
                if not ident:
                    continue
                if isinstance(name, str) and name.strip():
                    mapping[ident] = name.strip()
                else:
                    mapping.setdefault(ident, ident)
        return mapping

    def list_datacenters(self) -> dict[str, str]:
        return self._list_named_resources(self._DATACENTER_LIST_ENDPOINT, "datacenter")

    def list_clusters(self) -> dict[str, str]:
        return self._list_named_resources(self._CLUSTER_LIST_ENDPOINT, "cluster")

    def list_hosts(self) -> dict[str, str]:
        return self._list_named_resources(self._HOST_LIST_ENDPOINT, "host")

    def list_resource_pools(self) -> dict[str, str]:
        return self._list_named_resources(self._RESOURCE_POOL_LIST_ENDPOINT, "resource_pool")

    def list_folders(self) -> dict[str, str]:
        return self._list_named_resources(self._FOLDER_LIST_ENDPOINT, "folder")
