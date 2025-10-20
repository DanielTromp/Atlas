from __future__ import annotations

from infrastructure_atlas.infrastructure.metrics import (
    get_metrics_snapshot,
    record_netbox_export,
    reset_metrics,
)


def test_record_netbox_export_success_and_failure():
    reset_metrics()
    record_netbox_export(1.5, mode="service", force=True, status="success")
    record_netbox_export(2.0, mode="service", force=True, status="success")
    record_netbox_export(3.0, mode="service", force=False, status="failure")

    snapshot = get_metrics_snapshot()
    counters = snapshot["counters"]["netbox_export_runs_total"]
    success = next(item for item in counters if item["labels"] == {"mode": "service", "force": "true", "status": "success"})
    failure = next(item for item in counters if item["labels"] == {"mode": "service", "force": "false", "status": "failure"})
    assert success["value"] == 2
    assert failure["value"] == 1

    histograms = snapshot["histograms"]["netbox_export_duration_seconds"]
    duration_entry = next(item for item in histograms if item["labels"] == {"mode": "service", "force": "true"})
    assert any(abs(v - 1.5) < 1e-6 for v in duration_entry["values"])
    assert any(abs(v - 2.0) < 1e-6 for v in duration_entry["values"])
