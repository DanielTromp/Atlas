# Repository Guidelines

## Project Structure & Module Organization
- `src/enreach_tools/`: primary package (Typer CLI, env loader, FastAPI app + static UI).
- `netbox-export/bin/`: task scripts invoked by the CLI (devices/vms export, merge, SharePoint).
- `netbox-export/data/`: default output directory for CSV/Excel.
- `scripts/`: local utilities (e.g., `visit_app.py`).
- `pyproject.toml`: tooling config (setuptools, ruff, mypy, uv deps).

## Build, Test, and Development Commands
- Run CLI: `uv run enreach status` — quick API/token check.
- Export all: `uv run enreach export update --force` — devices → vms → merge.
- Serve API/UI: `uv run enreach api serve --host 127.0.0.1 --port 8000` then open `/app/`.
- SharePoint: `uv run enreach sharepoint publish-cmdb` — publish CMDB Excel.
- Lint: `uv run ruff check .` • Format: `uv run ruff format .`.
- Types: `uv run mypy src`.
- Tests (when added): `uv run -m pytest`.

## Coding Style & Naming Conventions
- Python 3.11, 4‑space indent, line length 120 (ruff).
- Package/modules: snake_case (`enreach_tools/...`).
- Functions/vars: snake_case; classes: PascalCase; constants: UPPER_SNAKE.
- CLI subcommands mirror directories (`export`, `api`, `sharepoint`).
- Use `rich.print` for user‑facing CLI messages.

## Testing Guidelines
- Framework: `pytest` (planned). Place tests in `tests/` as `test_*.py`.
- Prefer fast, isolated unit tests for `env`, CLI wiring, and API routes (mock I/O).
- Optional target: ≥80% coverage for changed code.

## Commit & Pull Request Guidelines
- Commits: imperative, concise, scoped (e.g., "export: handle force re-fetch").
- PRs must include: purpose, summary of changes, how to validate (commands), and screenshots for UI changes.
- Link related issues and note env vars impacting behavior.

## Security & Configuration Tips
- Secrets live in `.env` (never commit). Start from `.env.example`.
- Required for exports: `NETBOX_URL`, `NETBOX_TOKEN`; optional: `NETBOX_DATA_DIR`.
- SharePoint: set `SPO_SITE_URL` and either `SPO_USERNAME`/`SPO_PASSWORD` or app creds (`SPO_TENANT_ID`, `SPO_CLIENT_ID`, `SPO_CLIENT_SECRET`).
- Extra headers: `NETBOX_EXTRA_HEADERS="Key1=val;Key2=val"`.
