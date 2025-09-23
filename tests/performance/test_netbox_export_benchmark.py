"""Performance regression benchmarks for NetBox export flows."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from enreach_tools.application.exporter.netbox import ExportPaths
from enreach_tools.application.services.netbox import NetboxExportService
from enreach_tools.domain.integrations.netbox import NetboxDeviceRecord, NetboxVMRecord

REPO_ROOT = Path(__file__).resolve().parents[2]


class FakeNetboxClient:
    """Lightweight NetBox client substitute for deterministic benchmarks."""

    def __init__(self, devices: Iterable[NetboxDeviceRecord], vms: Iterable[NetboxVMRecord]) -> None:
        self._devices = list(devices)
        self._device_map = {str(device.id): device for device in self._devices}
        self._vms = list(vms)
        self._vm_map = {int(vm.id): vm for vm in self._vms}
        self.api = None  # contact lookups disabled during benchmarks

    # NativeNetboxExporter contract -------------------------------------------------
    def list_devices(self, *, force_refresh: bool = False) -> Iterable[NetboxDeviceRecord]:
        return self._devices

    def list_vms(self, *, force_refresh: bool = False) -> Iterable[NetboxVMRecord]:
        return self._vms

    def get_device(self, device_id: str | int) -> NetboxDeviceRecord:
        return self._device_map[str(device_id)]

    def get_vm(self, vm_id: str | int) -> NetboxVMRecord:
        return self._vm_map[int(vm_id)]

    def invalidate_cache(self) -> None:  # pragma: no cover - interface compatibility
        return None


def _make_device_records(count: int) -> list[NetboxDeviceRecord]:
    base_time = datetime(2024, 1, 1, tzinfo=UTC)
    records: list[NetboxDeviceRecord] = []
    for idx in range(count):
        updated = base_time + timedelta(seconds=idx)
        record = NetboxDeviceRecord(
            id=idx + 1,
            name=f"device-{idx:04d}",
            status="active",
            status_label="Active",
            role="server",
            tenant="tenant-a",
            tenant_group="group-a",
            site="ams",
            location=f"rack-{idx % 10}",
            tags=("production", f"cluster-{idx % 5}"),
            last_updated=updated,
            primary_ip=f"192.0.2.{(idx % 250) + 1}",
            primary_ip4=f"192.0.2.{(idx % 250) + 1}",
            primary_ip6=None,
            oob_ip=f"198.51.100.{(idx % 200) + 1}",
            custom_fields={
                "Server Group": f"sg-{idx % 3}",
                "DTAP state": "prod",
                "CPU": str(8 + (idx % 8)),
                "Memory": f"{32 + (idx % 16)} GB",
            },
            raw={
                "id": idx + 1,
                "comments": "",
                "device_bay_count": 0,
                "interface_count": 4,
            },
            source=None,
            manufacturer="Enreach",
            model="GenX",
            rack=f"rack-{idx % 20}",
            rack_unit=str((idx % 42) + 1),
            serial=f"SN-{idx:06d}",
            asset_tag=f"AT-{idx:06d}",
            cluster=f"cluster-{idx % 5}",
            site_group="emea",
            region="eu",
            description="Synthetic benchmark device",
        )
        records.append(record)
    return records


def _make_vm_records(count: int) -> list[NetboxVMRecord]:
    base_time = datetime(2024, 1, 1, tzinfo=UTC)
    records: list[NetboxVMRecord] = []
    for idx in range(count):
        updated = base_time + timedelta(seconds=idx)
        record = NetboxVMRecord(
            id=idx + 5000,
            name=f"vm-{idx:04d}",
            status="active",
            status_label="Active",
            role="application",
            tenant="tenant-a",
            tenant_group="group-a",
            site="ams",
            location="",
            tags=("production",),
            last_updated=updated,
            primary_ip=f"10.0.{idx % 24}.{(idx % 200) + 10}",
            primary_ip4=f"10.0.{idx % 24}.{(idx % 200) + 10}",
            primary_ip6=None,
            oob_ip=None,
            custom_fields={
                "Backup": "enabled",
                "DTAP_state": "prod",
            },
            raw={
                "id": idx + 5000,
                "description": "Synthetic benchmark VM",
                "interface_count": 2,
            },
            source=None,
            cluster=f"cluster-{idx % 3}",
            role_detail="app",
            platform="linux",
            description="Synthetic benchmark virtual machine",
        )
        records.append(record)
    return records


def _export_paths(root: Path) -> ExportPaths:
    data_dir = root / "data"
    return ExportPaths(
        data_dir=data_dir,
        devices_csv=data_dir / "netbox_devices_export.csv",
        vms_csv=data_dir / "netbox_vms_export.csv",
        merged_csv=data_dir / "netbox_merged_export.csv",
        excel_path=data_dir / "Systems CMDB.xlsx",
        scripts_root=REPO_ROOT,
        manifest_path=data_dir / "netbox_export_manifest.json",
    )


@pytest.mark.perf
@pytest.mark.benchmark(group="netbox-export")
def test_netbox_export_service_benchmark(
    benchmark,
    tmp_path_factory,
    monkeypatch,
    perf_sample_size: int,
):
    """Benchmark the synthetic NetBox export pipeline end-to-end."""

    monkeypatch.setattr("enreach_tools.backup_sync.sync_paths", lambda *args, **kwargs: None)
    monkeypatch.setattr(NetboxExportService, "_create_excel", lambda self: None)

    def setup():
        run_root = tmp_path_factory.mktemp("netbox-bench")
        paths = _export_paths(run_root)
        devices = _make_device_records(perf_sample_size)
        vms = _make_vm_records(max(1, perf_sample_size // 2))
        client = FakeNetboxClient(devices, vms)
        service = NetboxExportService(client=client, paths=paths)
        return (service,), {}

    def target(service: NetboxExportService) -> None:
        service.export_all(force=True, verbose=False)

    benchmark.pedantic(target, setup=setup, rounds=3, iterations=1)
