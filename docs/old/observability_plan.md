# Observability Plan (PR5)

## Goals
- Provide consistent, structured logs for CLI, background jobs, and API requests.
- Capture key metrics for exports, API latency, cache hit/miss ratios, and external adapter activity.
- Enable distributed tracing hooks so long-running flows (e.g. NetBox export + Confluence upload) can be followed across components when tracing backends are available.

## Logging
- **Library**: continue using stdlib `logging`, with opt-in structlog JSON renderer.
- **Format**: timestamp, level, module, message plus context fields.
- **Context**:
  - Export jobs: `job_id`, `job_name`, `force`, `duration_ms`, cache invalidation results.
  - API requests: request id, method, path, status_code, duration_ms, user (if present).
  - External adapters: `system` (netbox/confluence/zabbix/backup), `operation`, `status`, `elapsed_ms`.
- **Implementation**:
  - Introduce a lightweight context helper (`logging_context`) to attach fields within async/job flows.
  - Replace `print` statements in scripts/services with logger calls (`logger.info`, `logger.warning`).
  - Add FastAPI observability middleware for structured request logging, metrics, and tracing spans.
  - Ensure CLI (Typer) initialises logging with optional `--log-level`/`--log-structured` flags.

## Metrics
- **Library**: `prometheus_client` (in-process), conditionally enabled.
- **Exports**:
  - Counters: `netbox_export_runs_total`, `netbox_export_failures_total` (labels: `force`, `mode=legacy|service`).
  - Histogram: `netbox_export_duration_seconds`.
- **Caches**:
  - Gauges: `cache_entries` (labels: `name`), `cache_hits_total`, `cache_misses_total`, `cache_evictions_total`.
- **API**:
  - Histogram: `http_request_duration_seconds` (labels: `method`, `path_template`, `status_code`).
- **Adapter calls**:
  - Counter: `external_requests_total` (labels: `system`, `operation`, `status`).
- **Exposure**:
  - API: `/metrics` endpoint enabled via `ENREACH_METRICS_ENABLED` with optional bearer token guard (`ENREACH_METRICS_TOKEN`).
  - CLI: optional `--metrics-port` to expose a registry when long-running.

## Tracing
- **Library**: OpenTelemetry SDK (optional dependency).
- **Strategy**:
  - Create spans for export orchestration (`NetboxExportService`), Confluence uploads, and Zabbix RPC calls when tracing is enabled.
  - Integrate FastAPI with `FastAPIInstrumentor` for request spans.
  - Provide configuration via env (`OTEL_EXPORTER_OTLP_ENDPOINT`, `ENREACH_TRACING_ENABLED`).

## Roll-out Steps
1. Implement structured logging context helpers and replace print statements (PR5 step 3).
2. Add Prometheus metric registry, export instrumentation, cache gauges.
3. Expose `/metrics` in API and optional CLI flag.
4. Add OpenTelemetry hooks behind env guard. ✅
5. Update documentation (`README`, architecture) with logging/metrics/tracing usage instructions.
