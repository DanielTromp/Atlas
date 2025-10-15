# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Enreach Tools is a Python-based CLI and API platform for managing infrastructure across multiple systems (NetBox, vCenter, Commvault, Zabbix, Jira, Confluence). It provides:
- Unified CLI via Typer (`uv run enreach <command>`)
- FastAPI-based REST API and web UI
- Data export/caching workflows for CMDB management
- Multi-provider AI chat interface for infrastructure queries

## Essential Commands

### Development Setup
```bash
# Copy and configure environment
cp .env.example .env
# Edit .env with required credentials

# Run commands via uv (no installation needed)
uv run enreach --help
```

### API Server
```bash
# HTTP server
uv run enreach api serve --host 127.0.0.1 --port 8000

# HTTPS server (requires certs in certs/)
uv run enreach api serve --host 0.0.0.0 --port 8443 --ssl-certfile certs/localhost.pem --ssl-keyfile certs/localhost-key.pem --no-reload

# Access web UI at http://127.0.0.1:8000/app/ or https://127.0.0.1:8443/app/
```

### Testing
```bash
# Run all tests
uv run pytest

# Run specific test
uv run pytest tests/test_module.py::test_function

# Run performance benchmarks
uv run pytest --perf --benchmark-only -m perf --benchmark-autosave
```

#### Code Quality
```bash
# Lint with ruff (see pyproject.toml for rules)
uv run ruff check .

# Format with ruff
uv run ruff format .

# Type check with mypy
uv run mypy src/
```

### Coding Style
- Python 3.11, 4-space indentation, maximum line length 120 characters
- Package/modules: snake_case (`enreach_tools/...`)
- Functions/vars: snake_case; classes: PascalCase; constants: UPPER_SNAKE
- Use `rich.print` for user-facing CLI messages
- All code, identifiers, comments, and docs in English

### vCenter Operations
```bash
# Refresh all vCenter inventories
uv run enreach vcenter refresh --all --verbose

# Refresh single vCenter by ID
uv run enreach vcenter refresh --id <config-id>

# Refresh single VM (partial update, preserves other VMs in cache)
uv run enreach vcenter refresh --id <config-id> --vm <vm-id>

# View cached VMs
jq '.vms[] | {name, disks, snapshots}' data/vcenter/<config-id>.json
```

### Data Exports
```bash
# Full NetBox export workflow (devices → VMs → merge → Excel)
uv run enreach export update

# Refresh just the JSON cache (no CSV/Excel)
uv run enreach export cache

# Force re-fetch all data
uv run enreach export update --force

# Check cache statistics
uv run enreach cache-stats --json
```

## Architecture

The codebase follows a layered architecture:

```
src/enreach_tools/
├── domain/              # Business entities & value objects (dataclasses)
│   ├── entities.py      # User, Profile, VCenterConfig, etc.
│   ├── integrations/    # External system records (NetBox, vCenter, Commvault)
│   └── repositories.py  # Repository protocols (interfaces)
│
├── application/         # Use case orchestration
│   ├── services/        # Business logic services
│   │   ├── users.py     # User management
│   │   ├── vcenter.py   # vCenter inventory + caching
│   │   ├── netbox.py    # NetBox export orchestration
│   │   └── chat.py      # AI chat history
│   ├── dto/             # Data transfer objects (Pydantic)
│   └── orchestration/   # Async job runner
│
├── infrastructure/      # External adapters & implementations
│   ├── db/              # SQLAlchemy repositories
│   ├── external/        # API clients (NetBox, vCenter, Commvault, etc.)
│   ├── cache.py         # TTL cache with hit/miss metrics
│   ├── queues.py        # In-memory job queue
│   └── security/        # Secret store, password hashing
│
├── interfaces/          # Delivery mechanisms
│   ├── api/             # FastAPI routes & dependencies
│   └── cli/             # Typer commands (in cli.py)
│
├── api/                 # Legacy monolithic FastAPI app
│   └── static/          # Web UI (HTML/JS/CSS)
│
└── db/                  # Legacy SQLAlchemy models (being migrated)
```

### Key Design Principles

1. **Domain-First**: Domain entities are transport-agnostic dataclasses (`@dataclass(slots=True)`)
2. **DTOs for Transport**: Use Pydantic DTOs for API responses, not domain entities directly
3. **Repository Pattern**: Infrastructure adapters implement domain repository protocols
4. **Service Layer**: Application services coordinate domain logic and repository calls
5. **Dependency Injection**: FastAPI dependencies inject services; CLI uses factory functions

### vCenter Integration Specifics

The vCenter integration has unique architectural considerations:

- **pyVmomi Required**: Disk and snapshot data require pyVmomi (SOAP API), not just REST API
- **Cache Strategy**: Full inventory cached at `data/vcenter/{config_id}.json`
- **Partial Updates**: Use `--vm` flag to update single VM without rewriting entire cache (merges with existing)
- **Credential Flow**: Passwords stored encrypted via `SecretStore`, resolved at runtime
- **Data Fetched Per VM**:
  - Summary (name, power state, CPU, memory)
  - Placement (datacenter, cluster, host, resource pool, folder)
  - Guest identity, tools status, custom attributes, tags
  - Network interfaces (via REST + pyVmomi fallback)
  - **Snapshots**: Size calculated from delta disk files (`-000001.vmdk` pattern)
  - **Disks**: Always use pyVmomi (`get_vm_disks_vim`) since REST API returns minimal data

**Important**: When adding VM fields, update ALL layers:
1. `domain/integrations/vcenter.py` - VCenterVM dataclass
2. `application/services/vcenter.py` - `_build_vm()`, `_serialize_vm()`, `_deserialize_vm()`
3. `application/dto/vcenter.py` - VCenterVMDTO and mapper
4. `infrastructure/external/vcenter_client.py` - Client methods (if fetching new data)
5. Web UI: `api/static/app.js` (formatters), `api/static/vcenter/view.html` (display)

## Security & Configuration

**Important**: Secrets live in `.env` (never commit). Start from `.env.example`.

### Environment Variables (.env)

Required for basic operation:
- `NETBOX_URL`, `NETBOX_TOKEN` - NetBox API access
- `ENREACH_SECRET_KEY` - Fernet key for encrypted secret store (32 bytes base64)
- `ENREACH_API_TOKEN` - Bearer token for API authentication
- `ENREACH_UI_PASSWORD` - Web UI login password

vCenter:
- Credentials stored in database via secret store, configured through web UI

Commvault:
- `COMMVAULT_BASE_URL`, `COMMVAULT_API_TOKEN`
- `COMMVAULT_JOB_CACHE_TTL` - Cache TTL in seconds (default 600)

Atlassian (Jira/Confluence):
- `ATLASSIAN_BASE_URL`, `ATLASSIAN_EMAIL`, `ATLASSIAN_API_TOKEN`
- `CONFLUENCE_CMDB_PAGE_ID`, `CONFLUENCE_DEVICES_PAGE_ID`, `CONFLUENCE_VMS_PAGE_ID`
- `CONFLUENCE_ENABLE_TABLE_FILTER`, `CONFLUENCE_ENABLE_TABLE_SORT` - Enable table macros

Optional:
- `LOG_LEVEL` - API logging level (default: warning)
- `ENREACH_LOG_LEVEL`, `ENREACH_LOG_STRUCTURED` - CLI logging
- `NETBOX_DATA_DIR` - Export directory (default: `data/`)
- `NETBOX_EXTRA_HEADERS` - Additional headers (format: `"Key1=val;Key2=val"`)

### Database

SQLite database at `data/enreach.db` (auto-created via Alembic migrations):
```bash
# Migrations run automatically on API startup
# Manual migration: uv run alembic upgrade head
```

## Common Development Tasks

### Adding a New vCenter VM Field

1. **Update Domain Model** (`domain/integrations/vcenter.py`):
   ```python
   @dataclass(slots=True)
   class VCenterVM:
       new_field: str | None = None
   ```

2. **Fetch Data** (`infrastructure/external/vcenter_client.py`):
   ```python
   def get_vm_new_data_vim(self, instance_uuid: str):
       # Use pyVmomi to fetch data
   ```

3. **Update Service** (`application/services/vcenter.py`):
   - Fetch in `_fetch_inventory_live()` (add to vm_payloads tuple)
   - Process in `_build_vm()` (accept new parameter, add to VCenterVM constructor)
   - Serialize in `_serialize_vm()` (add to dict)
   - Deserialize in `_deserialize_vm()` (parse from dict, add to VCenterVM constructor)

4. **Update DTO** (`application/dto/vcenter.py`):
   ```python
   class VCenterVMDTO(DomainModel):
       new_field: str | None = None

   def vcenter_vm_to_dto(record: VCenterVM) -> VCenterVMDTO:
       return VCenterVMDTO(..., new_field=record.new_field)
   ```

5. **Update Web UI**:
   - Add formatter in `api/static/app.js`
   - Add column to `BASE_VCENTER_COLUMNS`
   - Add detail view section in `api/static/vcenter/view.html`

6. **Test**: `uv run enreach vcenter refresh --id <config-id> --vm <vm-id>`

### Adding a New API Endpoint

1. **Create Route** (`interfaces/api/routes/yourfeature.py`):
   ```python
   from fastapi import APIRouter, Depends
   from enreach_tools.interfaces.api.dependencies import get_your_service

   router = APIRouter(prefix="/yourfeature", tags=["yourfeature"])

   @router.get("/items")
   def list_items(service: YourServiceDep):
       items = service.list_items()
       return [dto.dict_clean() for dto in items]
   ```

2. **Register Router** (`api/app.py`):
   ```python
   from enreach_tools.interfaces.api.routes import yourfeature
   app.include_router(yourfeature.router, prefix="/api")
   ```

3. **Create Service** if needed (`application/services/yourfeature.py`)
4. **Add Dependency** (`interfaces/api/dependencies.py`)

### Working with Caching

Named TTL caches are registered globally:
```python
from enreach_tools.infrastructure.cache import get_cache

cache = get_cache("my_feature.data", ttl_seconds=300)
value = cache.get(key)
if value is None:
    value = fetch_expensive_data()
    cache.set(key, value)

# Invalidate when data changes
cache.invalidate(key)  # Single key
cache.clear()          # All keys

# View stats
uv run enreach cache-stats
```

## Testing Patterns

### Service Tests
```python
from enreach_tools.application.services import VCenterService
from enreach_tools.infrastructure.persistence.database import get_session

with get_session() as session:
    service = VCenterService(session)
    config, vms, meta = service.get_inventory(config_id)
```

### API Tests
```python
from fastapi.testclient import TestClient
from enreach_tools.api.app import app

client = TestClient(app)
response = client.get("/api/vcenter/configs", headers={"Authorization": f"Bearer {token}"})
```

## Debugging

### Enable Debug Logging
```bash
# API
LOG_LEVEL=debug uv run enreach api serve

# CLI
ENREACH_LOG_LEVEL=debug ENREACH_LOG_STRUCTURED=1 uv run enreach vcenter refresh --id <id>
```

### Inspect Cache Files
```bash
# vCenter cache
jq '.vms | length' data/vcenter/<config-id>.json
jq '.vms[] | select(.vm_id == "vm-123")' data/vcenter/<config-id>.json

# NetBox cache
jq '.devices | length' data/netbox_cache.json
```

### Check Database
```bash
sqlite3 data/enreach.db "SELECT * FROM vcenter_configs;"
```

## Migration Notes

The codebase is transitioning from legacy monolithic structure to layered architecture:
- **Legacy**: `api/app.py` monolith, `db/models.py` direct SQLAlchemy access
- **New**: Layered domain/application/infrastructure/interfaces

When working on existing features:
1. Prefer using application services over direct DB/client access
2. Return DTOs from services, not domain entities or dicts
3. Add new business logic to application services, not API routes
4. See `docs/refactor_plan.md` for migration roadmap

## Key Files

- `cli.py` - Main CLI entry point (Typer commands)
- `api/app.py` - Legacy monolithic FastAPI app
- `env.py` - Environment variable loader
- `infrastructure/external/vcenter_client.py` - vCenter API client (REST + pyVmomi)
- `application/services/vcenter.py` - vCenter inventory service (caching, serialization)
- `api/static/app.js` - Web UI JavaScript
- `docs/vcenter_disk_information.md` - vCenter disk feature documentation

## Performance

- vCenter full refresh: ~4 minutes for 410 VMs (with disks, snapshots, all metadata)
- vCenter single VM refresh: ~5 seconds (partial cache update)
- NetBox export: ~30 seconds for 2000 devices + 1000 VMs
- Commvault cache: 35MB JSON, ~60 seconds to refresh

See `docs/performance_benchmarks.md` for detailed benchmarks.

## Commit & Pull Request Guidelines

- **Commits**: Imperative, concise, scoped (e.g., "export: handle force re-fetch")
- **PRs must include**:
  - Purpose and summary of changes
  - How to validate (commands to run)
  - Screenshots for UI changes
  - Link related issues
  - Note env vars impacting behavior
- **Language**: Write commit messages and PR descriptions in English only

## Additional Documentation

- `AGENTS.md` - Agent behavior, MCP server configuration, language policy
- `docs/architecture_overview.md` - Layered architecture and refactor plan
- `docs/vcenter_disk_information.md` - vCenter disk feature documentation
- `docs/performance_benchmarks.md` - Performance baselines and tuning
- `docs/logging.md` - Logging pipeline configuration
- `docs/refactor_plan.md` - Migration roadmap from legacy to layered architecture
