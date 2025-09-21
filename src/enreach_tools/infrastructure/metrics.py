"""Lightweight in-process metrics registry for exports and adapters."""
from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Tuple

_LabelKey = Tuple[Tuple[str, str], ...]


def _freeze_labels(**labels: str) -> _LabelKey:
    return tuple(sorted(labels.items()))


@dataclass
class CounterMetric:
    values: Dict[_LabelKey, float]
    lock: threading.Lock

    def inc(self, *, labels: Dict[str, str], amount: float = 1.0) -> None:
        key = _freeze_labels(**labels)
        with self.lock:
            self.values[key] = self.values.get(key, 0.0) + amount


@dataclass
class HistogramMetric:
    observations: Dict[_LabelKey, list[float]]
    lock: threading.Lock

    def observe(self, *, labels: Dict[str, str], value: float) -> None:
        key = _freeze_labels(**labels)
        with self.lock:
            self.observations.setdefault(key, []).append(value)


    def summary(self) -> Dict[_LabelKey, Dict[str, float]]:
        snapshot: Dict[_LabelKey, Dict[str, float]] = {}
        with self.lock:
            for key, values in self.observations.items():
                if not values:
                    continue
                total = float(sum(values))
                snapshot[key] = {"count": float(len(values)), "sum": total}
        return snapshot

class MetricsRegistry:
    def __init__(self) -> None:
        self.counters: Dict[str, CounterMetric] = {}
        self.histograms: Dict[str, HistogramMetric] = {}
        self._lock = threading.Lock()

    def counter(self, name: str) -> CounterMetric:
        with self._lock:
            metric = self.counters.get(name)
            if metric is None:
                metric = CounterMetric(values={}, lock=threading.Lock())
                self.counters[name] = metric
            return metric

    def histogram(self, name: str) -> HistogramMetric:
        with self._lock:
            metric = self.histograms.get(name)
            if metric is None:
                metric = HistogramMetric(observations=defaultdict(list), lock=threading.Lock())
                self.histograms[name] = metric
            return metric

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            counters = {
                name: [
                    {"labels": dict(labels), "value": value}
                    for labels, value in metric.values.items()
                ]
                for name, metric in self.counters.items()
            }
            histograms = {
                name: [
                    {"labels": dict(labels), "values": list(values)}
                    for labels, values in metric.observations.items()
                ]
                for name, metric in self.histograms.items()
            }
        return {"counters": counters, "histograms": histograms}


_REGISTRY = MetricsRegistry()


def record_netbox_export(duration_seconds: float | None, *, mode: str, force: bool, status: str) -> None:
    """Record metrics for a NetBox export run."""

    labels = {"mode": mode, "force": str(force).lower(), "status": status}
    _REGISTRY.counter("netbox_export_runs_total").inc(labels=labels)
    if duration_seconds is not None:
        hist_labels = {"mode": mode, "force": str(force).lower()}
        _REGISTRY.histogram("netbox_export_duration_seconds").observe(
            labels=hist_labels,
            value=duration_seconds,
        )


def record_http_request(duration_seconds: float, *, method: str, path_template: str, status_code: int) -> None:
    labels = {"method": method.upper(), "path_template": path_template, "status_code": str(status_code)}
    _REGISTRY.counter("http_requests_total").inc(labels=labels)
    _REGISTRY.histogram("http_request_duration_seconds").observe(
        labels={"method": method.upper(), "path_template": path_template},
        value=duration_seconds,
    )


def get_metrics_snapshot() -> Dict[str, Any]:
    return _REGISTRY.snapshot()






def reset_metrics() -> None:
    global _REGISTRY
    _REGISTRY = MetricsRegistry()


def _format_labels(labels: Dict[str, str]) -> str:
    if not labels:
        return ""
    parts: list[str] = []
    for key, value in labels.items():
        escaped = value.replace("\\", "\\\\").replace('"', '\"')
        parts.append(f'{key}="{escaped}"')
    return "{" + ",".join(parts) + "}"


def snapshot_to_prometheus(snapshot: Dict[str, Any] | None = None) -> str:
    data = snapshot or get_metrics_snapshot()
    lines: list[str] = []

    counters = data.get("counters", {})
    for name, samples in counters.items():
        lines.append(f"# TYPE {name} counter")
        for sample in samples:
            labels = _format_labels(sample.get("labels", {}))
            value = sample.get("value", 0.0)
            lines.append(f"{name}{labels} {value}")

    histograms = data.get("histograms", {})
    for name, samples in histograms.items():
        lines.append(f"# TYPE {name} summary")
        for sample in samples:
            labels = sample.get("labels", {})
            values = sample.get("values", [])
            count = float(len(values))
            total = float(sum(values) if values else 0.0)
            meta = _format_labels(labels)
            lines.append(f"{name}_count{meta} {count}")
            lines.append(f"{name}_sum{meta} {total}")

    if not lines:
        lines.append("# No metrics recorded")
    return "\n".join(lines) + "\n"


__all__ = [
    "MetricsRegistry",
    "get_metrics_snapshot",
    "record_http_request",
    "record_netbox_export",
    "reset_metrics",
    "snapshot_to_prometheus",
]
