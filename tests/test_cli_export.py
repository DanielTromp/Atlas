from __future__ import annotations

from typer.testing import CliRunner

from enreach_tools.cli import app
from enreach_tools.domain.tasks import JobPriority, JobSpec
from enreach_tools.infrastructure.metrics import get_metrics_snapshot, reset_metrics

runner = CliRunner()


def test_export_update_runs_legacy_scripts(monkeypatch):
    calls: list[tuple[str, tuple[str, ...]]] = []

    def fake_run_script(path: str, *args: str) -> int:
        calls.append((path, args))
        return 0

    monkeypatch.setattr("enreach_tools.cli._run_script", fake_run_script)
    reset_metrics()

    result = runner.invoke(
        app,
        ["export", "update"],
        env={"NETBOX_URL": "https://netbox.local", "NETBOX_TOKEN": "token"},
    )
    assert result.exit_code == 0
    assert any(path == "netbox-export/bin/netbox_update.py" for path, _ in calls)
    snapshot = get_metrics_snapshot()
    counters = snapshot["counters"].get("netbox_export_runs_total", [])
    entry = next(item for item in counters if item["labels"] == {"mode": "legacy", "force": "false", "status": "success"})
    assert entry["value"] == 1


def test_export_update_queue_path(monkeypatch):
    class StubService:
        JOB_NAME = "netbox.export.update"

        def __init__(self) -> None:
            self.job_specs: list[JobSpec] = []
            self.handled = False

        def build_job_spec(
            self,
            *,
            force: bool = False,
            verbose: bool = False,
            priority: JobPriority | None = None,
        ) -> JobSpec:
            chosen = priority or JobPriority.NORMAL
            spec = JobSpec(name=self.JOB_NAME, payload={"force": force, "verbose": verbose}, priority=chosen)
            self.job_specs.append(spec)
            return spec

        def job_handler(self):
            async def _handler(record):
                self.handled = True
                return {}

            return _handler

    stub = StubService()

    from enreach_tools.application.services import netbox as netbox_module

    def fake_from_env(cls):
        return stub

    monkeypatch.setattr(netbox_module.NetboxExportService, "from_env", classmethod(fake_from_env))
    reset_metrics()

    result = runner.invoke(
        app,
        ["export", "update", "--queue"],
        env={"NETBOX_URL": "https://netbox.local", "NETBOX_TOKEN": "token"},
    )
    assert result.exit_code == 0
    assert stub.job_specs, "job spec should be enqueued"
    assert stub.job_specs[0].payload.get("force") is False
    assert stub.handled is True
