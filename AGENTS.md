# Repository Guidelines

## Project Structure & Module Organization

- `src/infrastructure_atlas/`: primary package (Typer CLI, env loader, FastAPI app + static UI).
- `netbox-export/bin/`: task scripts invoked by the CLI (devices/vms export, merge, Confluence publish).
- `data/`: default output directory for CSV/Excel.
- `scripts/`: local utilities (e.g., `visit_app.py`).
- `pyproject.toml`: tooling config (setuptools, ruff, mypy, uv deps).

## Build, Test, and Development Commands

- Run CLI: `uv run atlas status` — quick API/token check.
- Export all: `uv run atlas export update --force` — devices → vms → merge.
- Serve API/UI: `uv run atlas api serve --host 127.0.0.1 --port 8000` then open `/app/`.
- Confluence: `uv run atlas confluence publish-cmdb` — publish CMDB Excel attachment.
- Confluence table: `uv run atlas confluence publish-devices-table` — refresh devices CSV as page table.
- Lint: `uv run ruff check .` • Format: `uv run ruff format .`.
- Types: `uv run mypy src`.
- Tests (when added): `uv run -m pytest`.

## Coding Style & Naming Conventions

- Python 3.11, 4‑space indent, line length 120 (ruff).
- Package/modules: snake_case (`infrastructure_atlas/...`).
- Functions/vars: snake_case; classes: PascalCase; constants: UPPER_SNAKE.
- CLI subcommands mirror directories (`export`, `api`, `confluence`).
- Use `rich.print` for user‑facing CLI messages.

## Testing Guidelines

- Framework: `pytest` (planned). Place tests in `tests/` as `test_*.py`.
- Prefer fast, isolated unit tests for `env`, CLI wiring, and API routes (mock I/O).
- Optional target: ≥80% coverage for changed code.

## Commit & Pull Request Guidelines

- Commits: imperative, concise, scoped (e.g., "export: handle force re-fetch").
- PRs must include: purpose, summary of changes, how to validate (commands), and screenshots for UI changes.
- Link related issues and note env vars impacting behavior.
- Language: Write commit messages and PR descriptions in English only.

## Security & Configuration Tips

- Secrets live in `.env` (never commit). Start from `.env.example`.
- Required for exports: `NETBOX_URL`, `NETBOX_TOKEN`; optional: `NETBOX_DATA_DIR`.
- Confluence publishing: set `ATLASSIAN_BASE_URL`, `ATLASSIAN_EMAIL`, `ATLASSIAN_API_TOKEN`, plus `CONFLUENCE_CMDB_PAGE_ID` and optional table pages (`CONFLUENCE_DEVICES_PAGE_ID`, `CONFLUENCE_VMS_PAGE_ID`) / macro flags (`CONFLUENCE_ENABLE_TABLE_FILTER`, `CONFLUENCE_ENABLE_TABLE_SORT`).
- Extra headers: `NETBOX_EXTRA_HEADERS="Key1=val;Key2=val"`.

## MCP Servers Configuration (Playwright, Context7, Puppeteer)

- Purpose: Enable MCP tooling for browser automation and up‑to‑date docs.
- Servers: Playwright (`@playwright/mcp`), Context7 (`@upstash/context7-mcp`), Puppeteer (`@modelcontextprotocol/server-puppeteer`).
- Scope: User‑level agent configuration via `~/.codex/config.toml`.

### Quick Setup

1) Create or edit `~/.codex/config.toml` and add:

```
[mcp_servers.playwright]
command = "npx"
args = ["@playwright/mcp@latest","--extension"]

[mcp_servers.context7]
args = ["-y", "@upstash/context7-mcp", "--api-key", "<YOUR_CONTEXT7_API_KEY>"]
command = "npx"

[mcp_servers.puppeteer-mcp]
command = "npx"
args    = ["-y", "@modelcontextprotocol/server-puppeteer"]
```

2) Security note: Store secrets in `.env` when possible; if you embed an API key in `~/.codex/config.toml`, treat that file as sensitive. Rotate `Context7` keys if leaked.

3) Install prerequisites:
- Node.js and `npx` available in `PATH`.
- Network egress allowed for the agent process.

### Validation

- Ask the agent to open a page with Playwright (e.g., "Open example.com and screenshot").
- Fetch docs with Context7 (e.g., "Resolve and fetch `/vercel/next.js` docs").
- Run a simple Puppeteer navigation (e.g., "Navigate to example.com and return the title").

If the agent reports the tools are available, the MCP servers are active. For VS Code users leveraging an MCP-enabled extension, ensure your extension points at the same `~/.codex/config.toml`.

### Atlassian MCP (Jira/Confluence)

- Package: `mcp-atlassian` (NPM)
- Auth: Atlassian Cloud email + API token
- Env vars (add to `.env`):
  - `ATLASSIAN_BASE_URL` (e.g., `https://your-domain.atlassian.net`)
  - `ATLASSIAN_EMAIL`
  - `ATLASSIAN_API_TOKEN`

Add this server to `~/.codex/config.toml`:

```
[mcp_servers.mcp-atlassian]
command = "npx"
args = ["-y", "mcp-atlassian"]

# Option A: inherit env from your shell/IDE (recommended)
# Ensure these are exported in your environment (e.g., via .env loader)

# Option B: set per-server env (if your MCP host supports it)
# env = {
#   ATLASSIAN_BASE_URL = "${ATLASSIAN_BASE_URL}",
#   ATLASSIAN_EMAIL = "${ATLASSIAN_EMAIL}",
#   ATLASSIAN_API_TOKEN = "${ATLASSIAN_API_TOKEN}"
# }
```

Validation ideas:
- Jira: "Get my current user" or search issues by JQL.
- Confluence: read a page, list spaces, or export a page as Markdown.

## Agent Behavior & Language Policy

- Code language: Write all code, identifiers, comments, and docs in English.
- Response language: Reply to the user in the language of their latest message; if detection is uncertain, fallback to English.
- Mixed content: Keep code snippets, API names, and CLI commands in English even when the surrounding explanation is in another language.
- Repository communication: Use English for commit messages, PR descriptions, issue titles/bodies, and code reviews.
- MCP/tool usage: Use MCP tools and available automations where helpful to complete tasks autonomously and reduce user intervention.
- Minimize intervention: Prefer executing safe, reversible steps (apply patches, run lint/tests) over asking; only prompt for destructive actions or missing context.
- Approvals/safety: Respect sandbox/approval settings; avoid irreversible commands unless explicitly requested or clearly required with safeguards.
- Style: Follow the Codex CLI response style (concise, bullet-first, headers when useful, wrap commands/paths in backticks).
