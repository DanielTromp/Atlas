from __future__ import annotations

import types

import pytest

from enreach_tools.infrastructure.caching import get_cache_registry
from enreach_tools.infrastructure.external.confluence_client import ConfluenceClient, ConfluenceClientConfig
from enreach_tools.infrastructure.external.netbox_client import NetboxClient, NetboxClientConfig
from enreach_tools.infrastructure.external.zabbix_client import ZabbixClient, ZabbixClientConfig


class _StubRecord:
    def __init__(self, data: dict[str, object]) -> None:
        self._data = data

    def serialize(self) -> dict[str, object]:
        return self._data


class _StubEndpoint:
    def __init__(self, items: list[_StubRecord]) -> None:
        self._items = items
        self.calls = 0

    def all(self):
        self.calls += 1
        yield from self._items

    def get(self, pk):
        self.calls += 1
        for item in self._items:
            if item.serialize().get("id") == pk:
                return item
        return None


class _StubNetboxAPI:
    def __init__(self) -> None:
        device_data = _StubRecord(
            {
                "id": 1,
                "name": "device-1",
                "status": {"value": "active", "label": "Active"},
                "role": {"name": "core"},
                "tags": [],
                "last_updated": "2024-01-01T00:00:00Z",
                "custom_fields": {},
            }
        )
        vm_data = _StubRecord(
            {
                "id": 101,
                "name": "vm-1",
                "status": {"value": "active", "label": "Active"},
                "tags": [],
                "last_updated": "2024-01-02T00:00:00Z",
                "custom_fields": {},
            }
        )
        self.devices_endpoint = _StubEndpoint([device_data])
        self.vms_endpoint = _StubEndpoint([vm_data])
        self.dcim = types.SimpleNamespace(devices=self.devices_endpoint)
        self.virtualization = types.SimpleNamespace(virtual_machines=self.vms_endpoint)


@pytest.fixture
def stub_netbox(monkeypatch):
    api = _StubNetboxAPI()

    def fake_api(url: str, token: str):
        return api

    import enreach_tools.infrastructure.external.netbox_client as netbox_module

    monkeypatch.setattr(netbox_module, "pynetbox", types.SimpleNamespace(api=fake_api))
    yield api
    registry = get_cache_registry()
    registry.unregister("netbox.devices")
    registry.unregister("netbox.vms")


class _StubResponse:
    def __init__(self, status_code: int = 200, json_data: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = json_data or {}
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}: {self.text}")

    def json(self) -> dict:
        return self._payload


class _StubConfluenceSession:
    def __init__(self) -> None:
        self.auth = None
        self.headers = {}
        self._attachments: dict[str, dict] = {}

    def get(self, url: str, params: dict | None = None, timeout: float | None = None) -> _StubResponse:
        filename = (params or {}).get("filename")
        results = [att for att in self._attachments.values() if filename is None or att["title"] == filename]
        return _StubResponse(200, {"results": results})

    def post(self, url: str, headers=None, files=None, data=None, timeout=None):
        title = files["file"][0]
        comment = (data or {}).get("comment")
        parts = url.rstrip("/").split("/")
        attachment_id = parts[-2] if parts and parts[-1] == "data" else None
        if attachment_id and attachment_id in self._attachments:
            att = self._attachments[attachment_id]
            version = att.get("version", {"number": 1}).get("number", 1) + 1
        else:
            attachment_id = str(len(self._attachments) + 1)
            version = 1
        record = {
            "id": attachment_id,
            "title": title,
            "version": {"number": version},
            "_links": {
                "base": "https://confluence.example",
                "download": f"/download/{attachment_id}",
                "webui": f"/spaces/SPACE/pages/{attachment_id}",
            },
            "comment": comment,
        }
        self._attachments[attachment_id] = record
        return _StubResponse(200, record)

    def close(self) -> None:  # pragma: no cover - nothing to release
        pass


@pytest.fixture
def stub_requests_session(monkeypatch):
    session = _StubConfluenceSession()

    class _Factory:
        def __call__(self):
            return session

    monkeypatch.setattr("requests.Session", _Factory())
    return session


class _StubZabbixSession:
    def __init__(self) -> None:
        self.requests: list[dict] = []

    def post(self, url: str, headers=None, json=None, timeout=None):
        method = json.get("method")
        self.requests.append(json)
        if method == "hostgroup.get":
            result = [{"groupid": "10", "name": "Prod"}, {"groupid": "11", "name": "Prod/Sub"}]
        elif method == "problem.get":
            result = [
                {
                    "eventid": "123",
                    "name": "Disk full",
                    "severity": "3",
                    "opdata": "",
                    "clock": 1_700_000_000,
                    "acknowledged": "0",
                    "r_eventid": "0",
                    "suppressed": "0",
                    "tags": [],
                    "hosts": [{"hostid": "200", "name": "srv01"}],
                    "objectid": "900",
                }
            ]
        elif method == "trigger.get":
            result = [{"triggerid": "900", "hosts": [{"hostid": "200", "name": "srv01"}]}]
        elif method == "event.acknowledge":
            result = {"eventids": json["params"]["eventids"]}
        else:
            result = {}
        payload = {"jsonrpc": "2.0", "result": result, "id": json.get("id", 1)}
        return _StubResponse(200, payload)


@pytest.fixture
def stub_zabbix(monkeypatch):
    session = _StubZabbixSession()

    class _Factory:
        def __call__(self):
            return session

    monkeypatch.setattr("requests.Session", _Factory())
    return session


def test_netbox_client_cache_metrics(monkeypatch, stub_netbox):
    client = NetboxClient(NetboxClientConfig(url="https://netbox.example", token="abc", cache_ttl_seconds=60))

    devices_first = client.list_devices()
    devices_second = client.list_devices()
    assert devices_first == devices_second
    client.list_vms()
    client.list_vms()

    metrics = client.cache_metrics()
    assert metrics["devices"].misses == 1
    assert metrics["devices"].hits == 1
    assert metrics["vms"].misses == 1
    assert metrics["vms"].hits == 1

    client.invalidate_cache()
    client.list_devices()
    assert stub_netbox.devices_endpoint.calls == 2
    client.list_vms()
    assert stub_netbox.vms_endpoint.calls == 2

    registry = get_cache_registry()
    registry.unregister("netbox.devices")
    registry.unregister("netbox.vms")


def test_confluence_client_upload_and_replace(stub_requests_session):
    client = ConfluenceClient(ConfluenceClientConfig(base_url="https://confluence.example", email="u", api_token="t"))

    uploaded = client.upload_attachment(page_id="123", name="report.txt", data=b"abc")
    assert uploaded.title == "report.txt"
    found = client.find_attachment(page_id="123", name="report.txt")
    assert found is not None
    replaced = client.replace_attachment(page_id="123", attachment_id=uploaded.id, name="report.txt", data=b"def")
    assert replaced.version == 2

    client.close()


def test_zabbix_client_problem_flow(monkeypatch, stub_zabbix):
    client = ZabbixClient(ZabbixClientConfig(api_url="https://zabbix.example/api_jsonrpc.php", api_token="tok"))

    expanded = client.expand_groupids([10])
    assert expanded == (10, 11)

    problems = client.get_problems(severities=[3], limit=5)
    assert problems.count == 1
    problem = problems.items[0]
    assert problem.host_name == "srv01"
    assert problem.severity == 3

    ack = client.acknowledge(["123"], message="ok")
    assert ack.succeeded == ("123",)
