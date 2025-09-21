# NetBox Export Optimization Plan (PR5)

## Objectives
- Reduce the end-to-end runtime of `enreach export update` (service + queued mode) by removing redundant work and HTTP chatter.
- Avoid reprocessing unchanged data (CSV/Excel) whenever possible.
- Lay groundwork for future concurrency/streaming improvements while maintaining the legacy CSV format and external CLI compatibility.

## Pain Points Observed
1. **Legacy scripts** perform per-device/VM API calls and run as subprocesses, negating the in-process caching benefits.
2. **Contacts/roles lookups** issue multiple API calls per device (content types + contact assignments + detail fetches).
3. **CSV/Excel regeneration** rewrites entire files even when the data is unchanged.
4. **Sequential execution**: devices → VMs → merge → Excel runs serially without leveraging asynchronous I/O or concurrency.

## Optimization Phases

### Phase 1 — In-Process Exporter (Replace Scripts)
- Implement `NetboxExporter` inside the service layer to fetch devices/VMs via the cached `NetboxClient` without shelling out.
- Port the transformation logic (`get_full_device_data`, `get_full_vm_data`) into reusable functions that avoid redundant API round-trips (use bulk endpoints / pre-fetch related objects).
- Write CSVs/merge in-process using streaming writers to reduce memory foot print.
- Provide a CLI flag to fall back to legacy scripts until confidence is built (default to new flow once validated).

### Phase 2 — Bulk API Fetching & Caching Improvements
- Use NetBox endpoints with `?limit=0` plus `prefetch_related` to pull related objects (contacts, roles) in fewer requests.
- Preload lookup tables (contact roles, content types) once per run instead of per device.
- Cache HTTP session headers (e.g., `apply_extra_headers`) within the client.

### Phase 3 — Incremental CSV/Excel Output
- Skip rewriting CSV if digests of existing files match new data (e.g., hash rows in-memory before writing).
- For Excel, support a minimal mode: rebuild only when the merged CSV changed; optionally offer `--skip-excel` flag for faster CLI runs.
- Consider streaming Excel generation or using `xlsxwriter` for faster table creation.

### Phase 4 — Parallelism / Async
- Fetch devices/VMs concurrently (asyncio + thread pool for HTTP requests) where NetBox API limits allow.
- Explore background workers that can process exports concurrently with other CLI actions (bounded concurrency to avoid NetBox overload).

## Metrics & Validation
- Use the existing `netbox_export_duration_seconds` histogram to compare before/after runs.
- Add counters for API calls or HTTP retries (future: integrate `requests` instrumentation).
- Track cache hit/miss ratios after the scripts are replaced.

## Deliverables
- New exporter module (`application/services/netbox_exporter.py` or similar) with unit tests.
- Updated CLI/service pipeline using the in-process flow by default (legacy fallback optional).
- Documentation updates (README + architecture) describing the optimized path and new flags.
- Benchmarks (append to docs) summarizing runtime improvements on sample data sets.

## Rollout Strategy
1. Implement the in-process exporter and keep legacy scripts as a fallback (`--legacy` flag).
2. Run benchmarks in staging/env and tune caching/bulk fetch.
3. Deprecate the legacy scripts once parity is confirmed.
4. Iteratively refine concurrency and incremental updates.
