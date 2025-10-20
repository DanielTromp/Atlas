# Performance Benchmarking

This project uses [`pytest-benchmark`](https://pytest-benchmark.readthedocs.io/) to guard
the NetBox export pipeline against large performance regressions. Benchmarks run against
synthetic data in isolation – no external services are called.

## Quick start

```bash
# Run the benchmark suite (skips regular tests)
uv run pytest --perf --benchmark-only -m perf --benchmark-autosave
```

Running in this mode will:

- generate synthetic device / VM datasets (size controlled via `--perf-sample-size`)
- exercise the `NetboxExportService.export_all` flow end-to-end (CSV merge included, Excel skipped)
- store raw timing data under `.benchmarks/`

> **Tip:** `pytest-benchmark` prints a short table after each run. Combine it with
> `--benchmark-columns=min,mean,stddev,median,ops` for a compact report.

## Managing baselines

1. Capture a reference run: `uv run pytest --perf --benchmark-only -m perf --benchmark-save=baseline`
2. Commit (or archive) the generated `.benchmarks/*baseline.json` if you want the CI pipeline
   to compare against it later.
3. Compare two runs locally:

   ```bash
   uv run pytest-benchmark compare 0001 0002
   uv run pytest --perf --benchmark-only -m perf --benchmark-compare=0001 \
       --benchmark-compare-fail=min:5% --benchmark-compare-fail=mean:0.25
   ```

   The `--benchmark-compare-fail` expressions fail the suite when a metric regresses beyond
   the allowed threshold. Tune them to match acceptable drift for your environment.

## Customising dataset size

The benchmarks default to 500 devices and ~250 VMs – large enough to highlight meaningful
changes while keeping runtimes short. Override via:

```bash
uv run pytest --perf --benchmark-only -m perf --perf-sample-size=1000
```

## Output & storage

- Raw data lives in `.benchmarks/` (default `file://./.benchmarks`).
- `--benchmark-autosave` embeds commit hashes and timestamps in the file name; useful for
  tracking trends across branches.
- `pytest-benchmark compare --csv report.csv` produces a spreadsheet-ready summary.

## Adding new benchmarks

Benchmarks live in `tests/performance/` and are marked with `@pytest.mark.perf`.
Additions should:

1. Avoid external I/O (NetBox, Confluence, etc.) unless explicitly mocked.
2. Use deterministic synthetic data so results are comparable.
3. Document the scenario (what is measured and why) in this file.

For deeper scenarios (API latency, CLI end-to-end) consider adding Locust or
`pyperf` scripts under `scripts/perf/` and linking them here.
