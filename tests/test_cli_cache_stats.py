from __future__ import annotations

import json

from typer.testing import CliRunner

from infrastructure_atlas.cli import app
from infrastructure_atlas.infrastructure.caching import TTLCache, get_cache_registry

runner = CliRunner()


def _extract_json(output: str):
    lines = output.strip().splitlines()
    start = None
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            start = idx
            break
    if start is None:
        raise AssertionError(f"No JSON found in output:\n{output}")
    json_str = "\n".join(lines[start:])
    return json.loads(json_str)


def test_cli_cache_stats_json():
    registry = get_cache_registry()
    cache_name = "tests.cache.cli"
    cache = TTLCache[str, int](ttl_seconds=5, name=cache_name)
    cache.get("alpha", lambda: 42)

    try:
        result = runner.invoke(app, ["cache-stats", "--json"])
        assert result.exit_code == 0
        payload = _extract_json(result.stdout)
        assert cache_name in payload
        entry = payload[cache_name]
        assert entry["size"] == 1
        assert entry["metrics"]["loads"] >= 1
    finally:
        registry.unregister(cache_name)
