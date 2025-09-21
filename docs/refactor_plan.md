# Enreach Tools Refactor Plan

## Roadmap
- [x] PR1: Foundation scaffolding and package layout
  - [x] Document architecture objectives and coding conventions in repo
  - [x] Introduce layered package skeleton (`domain`, `application`, `infrastructure`, `interfaces`)
  - [x] Add logging/config scaffolding shared across layers
  - [x] Provide adapter/service interface stubs (no behaviour changes)
  - [x] Backfill pytest/lint/type baseline configuration for new layout docs
- [ ] PR2: Domain and persistence restructuring
  - [x] Define domain entities/value objects with Pydantic models and dataclasses
  - [x] Create repository interfaces and SQLAlchemy implementations
  - [x] Normalize database schema and generate Alembic migration `20250101_0003`
  - [x] Backfill data, update seeds, and document changes
  - [x] Add domain-layer unit tests
- [ ] PR3: API and CLI integration
  - [x] Split FastAPI routers per feature, wire services through dependency injection
  - [x] Align request/response DTOs, pagination/filter conventions, error mapping
  - [x] Refactor Typer CLI commands to use application services
  - [x] Add contract tests for API endpoints and CLI smoke tests
    - [x] Added auth/profile router tests in `tests/test_api_*_router.py`
    - [x] Added admin router tests in `tests/test_api_admin_router.py`
    - [x] Added CLI user admin smoke test via `tests/test_cli_users.py`
- [ ] PR4: External system adapters and caching
    - [x] Introduced adapter scaffolding for NetBox/Confluence/backups with TTL cache utility
  - [ ] Wrap NetBox/Confluence/Zabbix/backup logic with typed adapters and clients
  - [ ] Introduce async orchestration and job queue primitives
  - [ ] Add caching strategies with invalidation hooks and instrumentation
  - [ ] Provide integration tests with mocked providers
- [ ] PR5: Observability and performance enhancements
  - [ ] Implement structured logging, metrics, and tracing middleware
  - [ ] Optimize export/data flows (batching, streaming, concurrency)
  - [ ] Establish performance regression benchmarks and docs
- [ ] PR6: Testing, docs, and hardening
  - [ ] Expand pytest coverage (application/infrastructure/observability)
  - [ ] Finalize ADRs, README updates, architecture diagrams
  - [ ] Run full QA checklist and prepare release notes/rollback strategy

## Supporting Workstreams
- [ ] Migrations sequence (`20250101_0003` to `20250104_0006`) drafted and validated
- [ ] Observability stack decision (metrics/logging/tracing) documented
- [ ] Risk register maintained with mitigation/rollback steps

### Migration Notes
- 20250101_0003 adds supporting indexes only; no data copy required.
- Seed data unchanged; apply migration via `uv run enreach db init` and verify index presence with `sqlite_schema`.
