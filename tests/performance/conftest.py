"""Configuration helpers for performance benchmark suite."""
from __future__ import annotations

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("perf"):
        return
    skip_perf = pytest.mark.skip(reason="use --perf to run performance benchmarks")
    for item in items:
        if "perf" in item.keywords:
            item.add_marker(skip_perf)


@pytest.fixture(scope="session")
def perf_sample_size(pytestconfig: pytest.Config) -> int:
    """Return the configured sample size for synthetic benchmark payloads."""

    value = pytestconfig.getoption("perf_sample_size")
    return int(value) if value and value > 0 else 500
