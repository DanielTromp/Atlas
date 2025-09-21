from __future__ import annotations

import asyncio
import types
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from enreach_tools.application.orchestration import AsyncJobRunner
from enreach_tools.application.services.netbox import ExportPaths, NetboxExportService
from enreach_tools.domain.integrations import NetboxDeviceRecord, NetboxVMRecord
from enreach_tools.domain.tasks import JobStatus
from enreach_tools.infrastructure.queues import InMemoryJobQueue


class _FakeNetboxClient:
    def __init__(self):
        self.calls: dict[str, int] = {"devices": 0, "vms": 0}

    def list_devices(self, *, force_refresh: bool = False):
        self.calls["devices"] += 1
        now = datetime.fromisoformat("2024-01-01T00:00:00+00:00")
        return [
            NetboxDeviceRecord(
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
        ]

    def list_vms(self, *, force_refresh: bool = False):
        self.calls["vms"] += 1
        now = datetime.fromisoformat("2024-01-02T00:00:00+00:00")
        return [
            NetboxVMRecord(
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
        ]


def test_export_service_writes_minimal_csv():
    with TemporaryDirectory() as tmp:
        paths = ExportPaths(
            data_dir=Path(tmp),
            devices_csv=Path(tmp) / "devices.csv",
            vms_csv=Path(tmp) / "vms.csv",
            merged_csv=Path(tmp) / "merged.csv",
            excel_path=Path(tmp) / "cmdb.xlsx",
            scripts_root=Path(tmp),
        )
        service = NetboxExportService(client=_FakeNetboxClient(), paths=paths)
        service._write_devices_csv(service._client.list_devices())
        service._write_vms_csv(service._client.list_vms())

        assert paths.devices_csv.exists()
        assert paths.vms_csv.exists()
        assert paths.devices_csv.read_text().count("device-1") == 1
        assert paths.vms_csv.read_text().count("vm-1") == 1


def test_merge_csv_combines_devices_and_vms():
    with TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        paths = ExportPaths(
            data_dir=tmp_path,
            devices_csv=tmp_path / "devices.csv",
            vms_csv=tmp_path / "vms.csv",
            merged_csv=tmp_path / "merged.csv",
            excel_path=tmp_path / "cmdb.xlsx",
            scripts_root=tmp_path,
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
    paths = ExportPaths(
        data_dir=tmp_path,
        devices_csv=tmp_path / "devices.csv",
        vms_csv=tmp_path / "vms.csv",
        merged_csv=tmp_path / "merged.csv",
        excel_path=tmp_path / "cmdb.xlsx",
        scripts_root=tmp_path,
    )
    service = NetboxExportService(client=_FakeNetboxClient(), paths=paths)

    async def _fake_export_all_async(self, *, force: bool = False) -> None:
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
