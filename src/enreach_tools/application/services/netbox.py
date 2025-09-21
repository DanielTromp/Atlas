"""Application service orchestrating NetBox exports."""
from __future__ import annotations

import asyncio
import csv
import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from time import monotonic
from typing import Protocol

from enreach_tools import backup_sync
from enreach_tools.application.exporter.netbox import (
    ExportArtifacts,
    ExportPaths,
    LegacyScriptNetboxExporter,
    NativeNetboxExporter,
)
from enreach_tools.application.orchestration import JobHandler
from enreach_tools.domain.integrations import NetboxDeviceRecord, NetboxVMRecord
from enreach_tools.domain.tasks import JobPriority, JobSpec
from enreach_tools.infrastructure.external import NetboxClient, NetboxClientConfig
from enreach_tools.infrastructure.logging import get_logger, logging_context
from enreach_tools.infrastructure.metrics import record_netbox_export
from enreach_tools.infrastructure.tracing import span

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
        self._logger = get_logger(__name__)
        use_legacy = os.getenv("ENREACH_LEGACY_EXPORTER", "").strip().lower() in {"1", "true", "yes", "on"}
        if use_legacy:
            self._exporter = LegacyScriptNetboxExporter(paths)
        else:
            self._exporter = NativeNetboxExporter(client, paths, logger=self._logger)

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
            manifest_path=data_dir / "netbox_export_manifest.json",
        )
        client = NetboxClient(NetboxClientConfig(url=url, token=token))
        return cls(client=client, paths=paths)

    def export_all(self, *, force: bool = False, verbose: bool = False) -> None:
        with logging_context(job=self.JOB_NAME, force=force, verbose=verbose), span(
            "netbox.export", job=self.JOB_NAME, force=force, verbose=verbose
        ):
            start = monotonic()
            status = "success"
            if verbose:
                self._logger.info("NetBox export started (verbose mode)")
            else:
                self._logger.info("NetBox export started")
            try:
                artifacts: ExportArtifacts = self._exporter.export(force=force, verbose=verbose)
                self._merge_csv()
                self._create_excel()
                cache_invalidate = getattr(self._client, "invalidate_cache", None)
                if callable(cache_invalidate):
                    cache_invalidate()
            except Exception:
                status = "failure"
                duration = monotonic() - start
                record_netbox_export(duration_seconds=duration, mode="service", force=force, status=status)
                self._logger.exception(
                    "NetBox export failed",
                    extra={"duration_ms": int(duration * 1000)},
                )
                raise
            else:
                duration = monotonic() - start
                record_netbox_export(duration_seconds=duration, mode="service", force=force, status=status)
                self._logger.info(
                    "NetBox export completed",
                    extra={
                        "duration_ms": int(duration * 1000),
                        "devices_csv": self._paths.devices_csv.as_posix(),
                        "vms_csv": self._paths.vms_csv.as_posix(),
                        "merged_csv": self._paths.merged_csv.as_posix(),
                    },
                )

    async def export_all_async(self, *, force: bool = False, verbose: bool = False) -> None:
        await asyncio.to_thread(self.export_all, force=force, verbose=verbose)

    def build_job_spec(
        self,
        *,
        verbose: bool = False,
        force: bool = False,
        priority: JobPriority | None = None,
    ) -> JobSpec:
        """Create a `JobSpec` for scheduling a NetBox export run."""

        chosen_priority = priority or (JobPriority.HIGH if force else JobPriority.NORMAL)
        payload: Mapping[str, bool] = {"force": force, "verbose": verbose}
        return JobSpec(name=self.JOB_NAME, payload=payload, priority=chosen_priority)

    def job_handler(self) -> JobHandler:
        """Return an async handler suitable for an `AsyncJobRunner`."""

        async def _handler(record) -> Mapping[str, str | bool]:
            force_flag = bool(record.payload.get("force", False))
            verbose_flag = bool(record.payload.get("verbose", False))
            await self.export_all_async(force=force_flag, verbose=verbose_flag)
            return {
                "force": force_flag,
                "verbose": verbose_flag,
                "data_dir": self._paths.data_dir.as_posix(),
            }

        return _handler

    def _write_devices_csv(self, devices: Iterable[NetboxDeviceRecord]) -> None:
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

    def _merge_csv(self) -> None:
        devices_file = self._paths.devices_csv
        vms_file = self._paths.vms_csv
        output_file = self._paths.merged_csv

        if not devices_file.exists():
            raise FileNotFoundError(f"Devices CSV not found: {devices_file}")
        if not vms_file.exists():
            raise FileNotFoundError(f"VMs CSV not found: {vms_file}")

        self._logger.info(
            "Merging NetBox CSVs",
            extra={
                "devices_csv": devices_file.as_posix(),
                "vms_csv": vms_file.as_posix(),
                "output_csv": output_file.as_posix(),
            },
        )

        with devices_file.open(encoding="utf-8") as fh:
            devices_reader = csv.reader(fh)
            devices_headers = next(devices_reader)
        with vms_file.open(encoding="utf-8") as fh:
            vms_reader = csv.reader(fh)
            vms_headers = next(vms_reader)

        merged_headers = devices_headers.copy()
        for header in vms_headers:
            if header not in merged_headers:
                merged_headers.append(header)
        merged_headers.append("netbox_type")
        header_positions = {header: idx for idx, header in enumerate(merged_headers)}

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

        total = devices_count + vms_count
        self._logger.info(
            "NetBox CSV merge completed",
            extra={
                "devices_processed": devices_count,
                "vms_processed": vms_count,
                "total_records": total,
            },
        )
        if output_file.exists():
            size = output_file.stat().st_size
            self._logger.debug(
                "Merged CSV size",
                extra={"bytes": size, "megabytes": round(size / 1024 / 1024, 2)},
            )

        try:
            backup_sync.sync_paths([output_file], note="netbox_merge_csv")
        except Exception:  # pragma: no cover - best-effort logging
            pass

    def _create_excel(self) -> None:
        if not EXCEL_AVAILABLE or pd is None or Workbook is None or dataframe_to_rows is None:
            self._logger.info("Skipping Excel export - required libraries not available")
            return
        csv_file = self._paths.merged_csv
        if not csv_file.exists():
            self._logger.info("Skipping Excel export - merged CSV not found", extra={"merged_csv": csv_file.as_posix()})
            return

        excel_file = self._paths.excel_path
        self._logger.info("Creating Excel export", extra={"excel_file": excel_file.as_posix()})
        df = pd.read_csv(csv_file)

        order_candidates = [
            os.getenv("NETBOX_XLSX_ORDER_FILE"),
            str(self._paths.scripts_root / "netbox-export" / "etc" / "column_order.xlsx"),
            str(self._paths.data_dir / "netbox_merged_export.xlsx"),
        ]
        order_file = next((p for p in order_candidates if p and os.path.exists(p)), None)
        if order_file:
            self._logger.info("Applying column order", extra={"order_file": order_file})
            desired_order = self._load_column_order_from_xlsx(Path(order_file))
            if desired_order:
                ordered_cols = [c for c in desired_order if c in df.columns]
                tail_cols = [c for c in df.columns if c not in ordered_cols]
                df = df[ordered_cols + tail_cols]
            else:
                self._logger.warning("Column order file did not yield headers; keeping CSV order", extra={"order_file": order_file})
        else:
            self._logger.debug("No column order template found; keeping CSV order")

        wb = Workbook()
        ws = wb.active
        ws.title = "NetBox Inventory"

        for row in dataframe_to_rows(df, index=False, header=True):
            ws.append(row)

        num_cols = len(df.columns)
        end_col = get_column_letter(num_cols)
        if len(df) > 0:
            table_range = f"A1:{end_col}{len(df) + 1}"
            self._logger.debug("Creating Excel table", extra={"range": table_range})
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
            self._logger.info("No data rows; skipping Excel table creation")

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
            self._logger.info(
                "Excel export completed",
                extra={
                    "excel_file": excel_file.as_posix(),
                    "bytes": size,
                    "megabytes": round(size / 1024 / 1024, 2),
                },
            )

        try:
            backup_sync.sync_paths([excel_file], note="netbox_merge_excel")
        except Exception:  # pragma: no cover
            pass

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


__all__ = ["ExportPaths", "NetboxClientProtocol", "NetboxExportService"]
