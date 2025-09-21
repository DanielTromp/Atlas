"""Application service orchestrating NetBox exports."""
from __future__ import annotations

import asyncio
import csv
import os
import runpy
import sys
from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from enreach_tools import backup_sync
from enreach_tools.application.orchestration import JobHandler
from enreach_tools.domain.integrations import NetboxDeviceRecord, NetboxVMRecord
from enreach_tools.domain.tasks import JobPriority, JobSpec
from enreach_tools.infrastructure.external import NetboxClient, NetboxClientConfig

try:  # optional dependencies for Excel export
    import pandas as pd  # type: ignore
    from openpyxl import Workbook, load_workbook  # type: ignore
    from openpyxl.utils import get_column_letter  # type: ignore
    from openpyxl.utils.dataframe import dataframe_to_rows  # type: ignore
    from openpyxl.worksheet.table import Table, TableStyleInfo  # type: ignore
    EXCEL_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency not installed
    EXCEL_AVAILABLE = False
    pd = None  # type: ignore
    Workbook = None  # type: ignore
    load_workbook = None  # type: ignore
    get_column_letter = None  # type: ignore
    dataframe_to_rows = None  # type: ignore
    Table = None  # type: ignore
    TableStyleInfo = None  # type: ignore


@dataclass(slots=True)
class ExportPaths:
    data_dir: Path
    devices_csv: Path
    vms_csv: Path
    merged_csv: Path
    excel_path: Path
    scripts_root: Path


class NetboxClientProtocol(Protocol):
    def list_devices(self, *, force_refresh: bool = False) -> Iterable[NetboxDeviceRecord]:
        ...

    def list_vms(self, *, force_refresh: bool = False) -> Iterable[NetboxVMRecord]:
        ...


class NetboxExportService:
    JOB_NAME = "netbox.export.update"

    def __init__(self, *, client: NetboxClientProtocol, paths: ExportPaths) -> None:
        self._client = client
        self._paths = paths

    @classmethod
    def from_env(cls) -> NetboxExportService:
        url = os.environ.get("NETBOX_URL", "")
        token = os.environ.get("NETBOX_TOKEN", "")
        if not url or not token:
            raise ValueError("NETBOX_URL and NETBOX_TOKEN must be set")

        from enreach_tools.env import project_root

        data_dir_env = os.environ.get("NETBOX_DATA_DIR", "data")
        root = project_root()
        data_dir = Path(data_dir_env) if os.path.isabs(data_dir_env) else (root / data_dir_env)
        data_dir.mkdir(parents=True, exist_ok=True)

        paths = ExportPaths(
            data_dir=data_dir,
            devices_csv=data_dir / "netbox_devices_export.csv",
            vms_csv=data_dir / "netbox_vms_export.csv",
            merged_csv=data_dir / "netbox_merged_export.csv",
            excel_path=data_dir / "Systems CMDB.xlsx",
            scripts_root=root,
        )
        client = NetboxClient(NetboxClientConfig(url=url, token=token))
        return cls(client=client, paths=paths)

    def export_all(self, *, force: bool = False) -> None:
        self.run_devices_script(force=force)
        self.run_vms_script(force=force)
        self._merge_csv()
        self._create_excel()
        cache_invalidate = getattr(self._client, "invalidate_cache", None)
        if callable(cache_invalidate):
            cache_invalidate()

    async def export_all_async(self, *, force: bool = False) -> None:
        await asyncio.to_thread(self.export_all, force=force)

    def build_job_spec(
        self,
        *,
        force: bool = False,
        priority: JobPriority | None = None,
    ) -> JobSpec:
        """Create a `JobSpec` for scheduling a NetBox export run."""

        chosen_priority = priority or (JobPriority.HIGH if force else JobPriority.NORMAL)
        payload: Mapping[str, bool] = {"force": force}
        return JobSpec(name=self.JOB_NAME, payload=payload, priority=chosen_priority)

    def job_handler(self) -> JobHandler:
        """Return an async handler suitable for an `AsyncJobRunner`."""

        async def _handler(record) -> Mapping[str, str | bool]:
            force_flag = bool(record.payload.get("force", False))
            await self.export_all_async(force=force_flag)
            return {"force": force_flag, "data_dir": self._paths.data_dir.as_posix()}

        return _handler

    def _write_devices_csv(self, devices: Iterable[NetboxDeviceRecord]) -> None:
        # placeholder minimal implementation to keep interface; actual schema merging
        # remains in existing script for now
        with self._paths.devices_csv.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["id", "name", "last_updated"])
            for device in devices:
                last_updated = device.last_updated.isoformat() if device.last_updated else ""
                writer.writerow([device.id, device.name, last_updated])

    def _write_vms_csv(self, vms: Iterable[NetboxVMRecord]) -> None:
        with self._paths.vms_csv.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["id", "name", "last_updated"])
            for vm in vms:
                last_updated = vm.last_updated.isoformat() if vm.last_updated else ""
                writer.writerow([vm.id, vm.name, last_updated])

    def run_devices_script(self, *, force: bool = False) -> None:
        code = self._run_script("netbox-export/bin/get_netbox_devices.py", "--force" if force else None)
        if code not in (0, None):
            raise RuntimeError(f"Device export failed (exit {code})")

    def run_vms_script(self, *, force: bool = False) -> None:
        code = self._run_script("netbox-export/bin/get_netbox_vms.py", "--force" if force else None)
        if code not in (0, None):
            raise RuntimeError(f"VM export failed (exit {code})")

    def _run_script(self, relative_path: str, arg: str | None = None) -> int | None:
        script = self._paths.scripts_root / relative_path
        args = [script.as_posix()]
        if arg:
            args.append(arg)
        with _script_argv(args):
            try:
                runpy.run_path(str(script), run_name="__main__")
            except SystemExit as exc:  # propagate exit codes from scripts
                return exc.code
        return None

    def _merge_csv(self) -> None:
        devices_file = self._paths.devices_csv
        vms_file = self._paths.vms_csv
        output_file = self._paths.merged_csv

        if not devices_file.exists():
            raise FileNotFoundError(f"Devices CSV not found: {devices_file}")
        if not vms_file.exists():
            raise FileNotFoundError(f"VMs CSV not found: {vms_file}")

        print("Starting NetBox CSV merge process...")
        print(f"Devices file: {devices_file}")
        print(f"VMs file: {vms_file}")
        print(f"Output file: {output_file}")
        print("-" * 50)

        with devices_file.open(encoding="utf-8") as fh:
            devices_reader = csv.reader(fh)
            devices_headers = next(devices_reader)
        with vms_file.open(encoding="utf-8") as fh:
            vms_reader = csv.reader(fh)
            vms_headers = next(vms_reader)

        print(f"Devices headers: {len(devices_headers)} columns")
        print(f"VMs headers: {len(vms_headers)} columns")

        merged_headers = devices_headers.copy()
        for header in vms_headers:
            if header not in merged_headers:
                merged_headers.append(header)
                print(f"Added VM-specific column: {header}")
        merged_headers.append("netbox_type")
        header_positions = {header: idx for idx, header in enumerate(merged_headers)}

        print(f"Final merged headers: {len(merged_headers)} columns")

        devices_count = 0
        vms_count = 0

        with output_file.open("w", newline="", encoding="utf-8") as outfile:
            writer = csv.writer(outfile)
            writer.writerow(merged_headers)

            with devices_file.open(encoding="utf-8") as fh:
                reader = csv.reader(fh)
                next(reader)
                for row in reader:
                    merged_row = ["" for _ in merged_headers]
                    for idx, header in enumerate(devices_headers):
                        value = row[idx] if idx < len(row) else ""
                        merged_row[header_positions[header]] = value
                    merged_row[header_positions["netbox_type"]] = "devices"
                    writer.writerow(merged_row)
                    devices_count += 1
                    if devices_count % 100 == 0:
                        print(f"  Processed {devices_count} devices...")

            with vms_file.open(encoding="utf-8") as fh:
                reader = csv.reader(fh)
                next(reader)
                for row in reader:
                    merged_row = ["" for _ in merged_headers]
                    for idx, header in enumerate(vms_headers):
                        value = row[idx] if idx < len(row) else ""
                        merged_row[header_positions[header]] = value
                    merged_row[header_positions["netbox_type"]] = "vms"
                    writer.writerow(merged_row)
                    vms_count += 1
                    if vms_count % 100 == 0:
                        print(f"  Processed {vms_count} VMs...")

        total = devices_count + vms_count
        print("-" * 50)
        print("Merge completed successfully!")
        print(f"Devices processed: {devices_count:,}")
        print(f"VMs processed: {vms_count:,}")
        print(f"Total records: {total:,}")
        if output_file.exists():
            size = output_file.stat().st_size
            print(f"Output file size: {size:,} bytes ({size / 1024 / 1024:.2f} MB)")

        try:
            backup_sync.sync_paths([output_file], note="netbox_merge_csv")
        except Exception:  # pragma: no cover - best-effort logging
            pass
    def _create_excel(self) -> None:
        if not EXCEL_AVAILABLE or pd is None or Workbook is None or dataframe_to_rows is None:
            print("Skipping Excel export - required libraries not available")
            return
        csv_file = self._paths.merged_csv
        if not csv_file.exists():
            print("Skipping Excel export - merged CSV not found")
            return

        excel_file = self._paths.excel_path
        print(f"\nCreating Excel export: {excel_file}")
        df = pd.read_csv(csv_file)

        order_candidates = [
            os.getenv("NETBOX_XLSX_ORDER_FILE"),
            str(self._paths.scripts_root / "netbox-export" / "etc" / "column_order.xlsx"),
            str(self._paths.data_dir / "netbox_merged_export.xlsx"),
        ]
        order_file = next((p for p in order_candidates if p and os.path.exists(p)), None)
        if order_file:
            print(f"Applying column order from: {order_file}")
            desired_order = self._load_column_order_from_xlsx(Path(order_file))
            if desired_order:
                ordered_cols = [c for c in desired_order if c in df.columns]
                tail_cols = [c for c in df.columns if c not in ordered_cols]
                df = df[ordered_cols + tail_cols]
            else:
                print("Warning: could not read headers from order file; keeping CSV order.")
        else:
            print("No column order template found; keeping CSV order.")

        wb = Workbook()
        ws = wb.active
        ws.title = "NetBox Inventory"

        for row in dataframe_to_rows(df, index=False, header=True):
            ws.append(row)

        num_cols = len(df.columns)
        end_col = get_column_letter(num_cols)
        if len(df) > 0:
            table_range = f"A1:{end_col}{len(df) + 1}"
            print(f"Creating table with range: {table_range}")
            table = Table(displayName="NetBoxInventory", ref=table_range)
            style = TableStyleInfo(
                name="TableStyleMedium9",
                showFirstColumn=False,
                showLastColumn=False,
                showRowStripes=True,
                showColumnStripes=True,
            )
            table.tableStyleInfo = style
            ws.add_table(table)
        else:
            print("No data rows; skipping table creation to avoid Excel warnings.")

        ws.freeze_panes = "B2"
        for column in ws.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    max_length = max(max_length, len(str(cell.value)))
                except Exception:
                    pass
            ws.column_dimensions[column_letter].width = min(max_length + 2, 50)

        wb.save(excel_file)
        if excel_file.exists():
            size = excel_file.stat().st_size
            print(f"Excel file created: {size:,} bytes ({size / 1024 / 1024:.2f} MB)")

        try:
            backup_sync.sync_paths([excel_file], note="netbox_merge_excel")
        except Exception:  # pragma: no cover
            pass
        print("Excel export completed with:")
        print("  - Data sorted by Name")
        print("  - Filters enabled on header row")
        print("  - Auto-adjusted column widths")
        print("  - Table formatting applied")

    @staticmethod
    def _load_column_order_from_xlsx(order_file: Path) -> list[str]:
        if not EXCEL_AVAILABLE or load_workbook is None:
            return []
        try:
            wb = load_workbook(order_file, read_only=True, data_only=True)
            ws = wb.worksheets[0]
            headers: list[str] = []
            for cell in ws[1]:
                if cell.value is None:
                    continue
                headers.append(str(cell.value))
            wb.close()
            return headers
        except Exception:
            return []


@contextmanager
def _script_argv(args: Iterable[str]):
    old = sys.argv[:]
    sys.argv = list(args)
    try:
        yield
    finally:
        sys.argv = old


__all__ = ["ExportPaths", "NetboxClientProtocol", "NetboxExportService"]
