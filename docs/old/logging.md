# Logging Guide

The Enreach tooling ships with a single logging pipeline that covers the CLI, FastAPI
backend, background jobs, and the web UI. Logs help answer three questions:

1. **What ran?** → every CLI command and API request is annotated with relevant metadata.
2. **Who triggered it?** → log context carries the actor (CLI user or authenticated UI user).
3. **What happened?** → output, duration, and token usage for AI calls are all captured.

This document explains where logs live, how they are structured, and how to tune them.

## Locations & Files

- Default file: `logs/enreach.log`
- Override directory: `ENREACH_LOG_DIR=/custom/path`
- Override filename: `ENREACH_LOG_FILE=enreach.log`
- Rotation:
  - `ENREACH_LOG_MAX_BYTES` (default `5 * 1024 * 1024` → ~5 MB)
  - `ENREACH_LOG_BACKUP_COUNT` (default `5` rotated archives)
- Legacy export scripts continue to write to `export.log`; the observability layer does
  not change this behaviour.

All file paths are resolved relative to the project root and created on demand. When the
API boots, we re-apply the logging configuration after Alembic initialises to ensure the
file handler remains active.

## CLI Logging

- `src/enreach_tools/cli.py` registers a logger per command and wraps execution in a
  `logging_context` block.
- Every command line run (e.g. `uv run enreach status`) emits a log entry with:
  - `command_path` (Typer command path)
  - Raw argv (`raw_command`)
  - `actor` (current shell user; override via `ENREACH_LOG_ACTOR`)
  - Working directory (`cwd`)
- Legacy scripts run via `_run_script(...)` produce start/finish entries (including exit
  code) so that long-running operations can be correlated.

## API Request Logging

- `ObservabilityMiddleware` wraps every FastAPI request. It enriches log context with:
  - `request_id` (reused across downstream spans/metrics)
  - HTTP method & path
  - Matched route template
  - Authenticated user (`actor`) when available
  - Client IP
- Successful requests log a single `Request completed` entry. Errors emit
  `Request failed` with a stack trace.
- High-frequency polling endpoints (`/logs/tail`) are suppressed to avoid flooding the
  log file; everything else is recorded.
- Metrics integration (`record_http_request`) uses the same timing information; toggle
  via `ENREACH_METRICS_ENABLED`.

## Task Logging

Long-running operations use `task_logging(...)` (see
`src/enreach_tools/api/app.py:task_logging`). It adds structured context and prints:

```text
INFO … Task started … task=<name>
INFO … Task completed … duration_ms=<ms> prompt_tokens=… completion_tokens=…
```

If an exception bubbles out, the handler emits `Task failed` with the same context.

### AI Token Usage

- Chat providers (`/chat/complete`, `/chat/stream`) return a `ChatProviderResult` that
  contains both the reply text and normalised usage fields.
- `task_logging` captures these values (`prompt_tokens`, `completion_tokens`,
  `total_tokens`) so that every AI call is auditable in `enreach.log`.
- The assistant reply stored in the database carries an embedded `[[TOKENS {...}]]`
  marker; the API strips the marker before returning the message and exposes the tokens
  as `usage`.
- The chat UI renders the token summary under each assistant message and preserves it
  across refreshes.

## Structured Context

Logging relies on a global `ContextVar` to attach extra key/value pairs. Examples:

- CLI commands: `actor`, `command_path`, `raw_command`
- API: `request_id`, `actor`, `client_ip`
- Tasks: `task`, `provider`, `model`, duration & tokens

Because context is additive, nested operations (e.g. a chat completion triggered via
`/chat/stream`) automatically inherit the request metadata.

## Runtime Tips

- Tail the log: `tail -f logs/enreach.log`
- Use `rg prompt_tokens logs/enreach.log` to inspect token usage.
- Suppress console noise by setting `LOG_LEVEL`/`ENREACH_LOG_LEVEL` (values accepted by
  `logging.getLevelName`, e.g. `DEBUG`, `INFO`, `WARNING`).
- Set `ENREACH_LOG_STRUCTURED=1` to enable JSON logging when `structlog` is installed.

## FAQ

**Why only “Request completed” logs?**

`flow` debugging still works because each entry carries the start timestamp via
`duration_ms`. Eliminating `Request started` halves the noise while keeping high
resolution timing.

**Why skip `/logs/tail`?**

The web UI polls this endpoint every ~1 s while the export log panel is open. Suppressing
it prevents hundreds of duplicate entries without losing meaningful data.

**How do I audit AI costs?**

Every AI call now surfaces its token counts in three places: the chat bubble, the
persisted message (`usage` field), and `logs/enreach.log`. Aggregators (e.g. a future
report) can consume whichever source suits them best.

