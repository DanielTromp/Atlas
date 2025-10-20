from __future__ import annotations

import asyncio
import json
import types
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from infrastructure_atlas.application.exporter.netbox import ExportPaths, NativeNetboxExporter
from infrastructure_atlas.application.orchestration import AsyncJobRunner
from infrastructure_atlas.application.services.netbox import NetboxExportService
from infrastructure_atlas.domain.integrations import NetboxDeviceRecord, NetboxVMRecord
from infrastructure_atlas.domain.tasks import JobStatus
from infrastructure_atlas.infrastructure.metrics import reset_metrics
from infrastructure_atlas.infrastructure.queues import InMemoryJobQueue


class _FakeNetboxClient:
    def __init__(self):
        self.calls: dict[str, int] = {"devices": 0, "vms": 0}
        self.api = None

    def list_devices(self, *, force_refresh: bool = False):
        self.calls["devices"] += 1
        now = datetime.fromisoformat("2024-01-01T00:00:00+00:00")
        return [self._device_record(now)]

    def list_device_metadata(self):
        entries = {}
        for record in self.list_devices():
            last = record.last_updated.isoformat().replace("+00:00", "Z") if record.last_updated else ""
            entries[str(record.id)] = last
        return entries

    def _device_record(self, now):
        return NetboxDeviceRecord(
                id=1,
                name="device-1",
                status="active",
                status_label="Active",
                role=None,
                tenant=None,
                tenant_group=None,
                site=None,
                location=None,
                tags=(),
                last_updated=now,
                primary_ip=None,
                primary_ip4=None,
                primary_ip6=None,
                oob_ip=None,
                custom_fields={},
                raw={"id": 1, "name": "device-1"},
                manufacturer=None,
                model=None,
                rack=None,
                rack_unit=None,
                serial=None,
                asset_tag=None,
                cluster=None,
                site_group=None,
                region=None,
                description=None,
            )

    def list_vms(self, *, force_refresh: bool = False):
        self.calls["vms"] += 1
        now = datetime.fromisoformat("2024-01-02T00:00:00+00:00")
        return [self._vm_record(now)]

    def list_vm_metadata(self):
        entries = {}
        for record in self.list_vms():
            last = record.last_updated.isoformat().replace("+00:00", "Z") if record.last_updated else ""
            entries[str(record.id)] = last
        return entries

    def _vm_record(self, now):
        return NetboxVMRecord(
                id=2,
                name="vm-1",
                status="active",
                status_label="Active",
                role=None,
                tenant=None,
                tenant_group=None,
                site=None,
                location=None,
                tags=(),
                last_updated=now,
                primary_ip=None,
                primary_ip4=None,
                primary_ip6=None,
                oob_ip=None,
                custom_fields={},
                raw={"id": 2, "name": "vm-1"},
                cluster=None,
                role_detail=None,
                platform=None,
                description=None,
            )

    def get_device(self, device_id):
        return self._device_record(datetime.fromisoformat("2024-01-01T00:00:00+00:00"))

    def get_devices_by_ids(self, identifiers):
        return [self.get_device(identifier) for identifier in identifiers]

    def get_vm(self, vm_id):
        return self._vm_record(datetime.fromisoformat("2024-01-02T00:00:00+00:00"))

    def get_vms_by_ids(self, identifiers):
        return [self.get_vm(identifier) for identifier in identifiers]


def test_export_service_writes_minimal_csv():
    reset_metrics()
    with TemporaryDirectory() as tmp:
        paths = ExportPaths(
            data_dir=Path(tmp),
            devices_csv=Path(tmp) / "devices.csv",
            vms_csv=Path(tmp) / "vms.csv",
            merged_csv=Path(tmp) / "merged.csv",
            excel_path=Path(tmp) / "cmdb.xlsx",
            scripts_root=Path(tmp),
            manifest_path=Path(tmp) / "manifest.json",
            cache_json=Path(tmp) / "cache.json",
        )
        service = NetboxExportService(client=_FakeNetboxClient(), paths=paths)
        service._write_devices_csv(service._client.list_devices())
        service._write_vms_csv(service._client.list_vms())

        assert paths.devices_csv.exists()
        assert paths.vms_csv.exists()
        assert paths.devices_csv.read_text().count("device-1") == 1
        assert paths.vms_csv.read_text().count("vm-1") == 1


def test_merge_csv_combines_devices_and_vms():
    reset_metrics()
    with TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        paths = ExportPaths(
            data_dir=tmp_path,
            devices_csv=tmp_path / "devices.csv",
            vms_csv=tmp_path / "vms.csv",
            merged_csv=tmp_path / "merged.csv",
            excel_path=tmp_path / "cmdb.xlsx",
            scripts_root=tmp_path,
            manifest_path=tmp_path / "manifest.json",
            cache_json=tmp_path / "cache.json",
        )
        service = NetboxExportService(client=_FakeNetboxClient(), paths=paths)

        paths.devices_csv.write_text("ID,Name\n1,Device A\n")
        paths.vms_csv.write_text("ID,Name\n2,VM B\n")

        service._merge_csv()

        merged = paths.merged_csv.read_text().strip().splitlines()
        assert merged[0].startswith("ID,Name")
        assert any("devices" in line for line in merged[1:])
        assert any("vms" in line for line in merged[1:])


def test_netbox_export_job_handler_completes(tmp_path):
    reset_metrics()
    paths = ExportPaths(
        data_dir=tmp_path,
        devices_csv=tmp_path / "devices.csv",
        vms_csv=tmp_path / "vms.csv",
        merged_csv=tmp_path / "merged.csv",
        excel_path=tmp_path / "cmdb.xlsx",
        scripts_root=tmp_path,
        manifest_path=tmp_path / "manifest.json",
        cache_json=tmp_path / "cache.json",
    )
    service = NetboxExportService(client=_FakeNetboxClient(), paths=paths)

    async def _fake_export_all_async(
        self,
        *,
        force: bool = False,
        verbose: bool = False,
        refresh_cache: bool = True,
    ) -> None:
        await asyncio.sleep(0)

    service.export_all_async = types.MethodType(_fake_export_all_async, service)  # type: ignore[assignment]

    queue = InMemoryJobQueue()
    runner = AsyncJobRunner(queue)
    runner.register_handler(service.JOB_NAME, service.job_handler())

    async def _run() -> JobStatus:
        await runner.start()
        try:
            job = await queue.enqueue(service.build_job_spec(force=True))
            status = JobStatus.PENDING
            for _ in range(50):
                current = await queue.get_job(job.job_id)
                if current and current.status in {JobStatus.COMPLETED, JobStatus.FAILED}:
                    status = current.status
                    break
                await asyncio.sleep(0.05)
            assert status == JobStatus.COMPLETED
            return status
        finally:
            await runner.stop()

    asyncio.run(_run())


def test_native_exporter_persists_manifest(tmp_path, monkeypatch):
    client = _FakeNetboxClient()
    paths = ExportPaths(
        data_dir=tmp_path,
        devices_csv=tmp_path / "devices.csv",
        vms_csv=tmp_path / "vms.csv",
        merged_csv=tmp_path / "merged.csv",
        excel_path=tmp_path / "cmdb.xlsx",
        scripts_root=tmp_path,
        manifest_path=tmp_path / "manifest.json",
        cache_json=tmp_path / "cache.json",
    )
    monkeypatch.setattr("infrastructure_atlas.backup_sync.sync_paths", lambda *args, **kwargs: None)
    exporter = NativeNetboxExporter(client, paths)

    exporter.export(force=False, verbose=False)

    assert paths.manifest_path.exists()
    manifest = json.loads(paths.manifest_path.read_text())
    assert manifest.get("devices", {}).get("1")
    assert manifest.get("vms", {}).get("2")


def test_refresh_cache_updates_json_and_diff(tmp_path):
    client = _FakeNetboxClient()
    paths = ExportPaths(
        data_dir=tmp_path,
        devices_csv=tmp_path / "devices.csv",
        vms_csv=tmp_path / "vms.csv",
        merged_csv=tmp_path / "merged.csv",
        excel_path=tmp_path / "cmdb.xlsx",
        scripts_root=tmp_path,
        manifest_path=tmp_path / "manifest.json",
        cache_json=tmp_path / "cache.json",
    )
    service = NetboxExportService(client=client, paths=paths)

    first = service.refresh_cache(force=False, verbose=False)
    assert paths.cache_json.exists()
    snapshot = json.loads(paths.cache_json.read_text())
    assert snapshot["resources"]["devices"]["count"] == 1
    assert snapshot["resources"]["vms"]["count"] == 1
    assert first.summaries["devices"].added == 1
    assert first.summaries["vms"].added == 1

    second = service.refresh_cache(force=False, verbose=False)
    assert second.summaries["devices"].added == 0
    assert second.summaries["devices"].updated == 0
    assert second.summaries["vms"].added == 0
    cached = service.load_cache()
    assert cached is not None
    assert len(cached.devices) == 1
    assert len(cached.vms) == 1

    changed_device = replace(
        client._device_record(datetime.fromisoformat("2024-01-01T00:00:00+00:00")),
        name="device-1-renamed",
        last_updated=datetime.fromisoformat("2024-01-03T00:00:00+00:00"),
        raw={"id": 1, "name": "device-1-renamed"},
    )

    def _changed_devices(*, force_refresh: bool = False):
        return [changed_device]

    client.list_devices = _changed_devices  # type: ignore[assignment]
    client.list_device_metadata = lambda: {"1": changed_device.last_updated.isoformat().replace("+00:00", "Z")}  # type: ignore[assignment]
    client.get_device = lambda device_id: changed_device  # type: ignore[assignment]
    client.get_devices_by_ids = lambda identifiers: [changed_device]  # type: ignore[assignment]

    third = service.refresh_cache(force=False, verbose=False)
    assert third.summaries["devices"].updated == 1
    data = json.loads(paths.cache_json.read_text())
    devices = data["resources"]["devices"]["items"]
    assert devices[0]["name"] == "device-1-renamed"
