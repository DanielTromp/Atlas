"""Global pytest configuration for performance options."""
from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("performance")
    group.addoption(
        "--perf",
        action="store_true",
        default=False,
        help="Run performance benchmark tests (disabled by default).",
    )
    group.addoption(
        "--perf-sample-size",
        type=int,
        default=500,
        help="Number of synthetic records to generate for NetBox performance benchmarks.",
    )
