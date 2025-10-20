# Enreach Tools - Project Instructions

**Project Path**: `/Users/daniel/Documents/code/enreach-tools`  
**Purpose**: Personal infrastructure automation toolkit integrating NetBox, vCenter, Commvault, Zabbix, Atlassian, and other systems.  
**Development**: Local Mac with Claude Code (terminal), ChatGPT Codex (VS Code), Claude AI (web)  
**Version Control**: GitHub  
**Deployment**: Manual copy to production servers

---

## Quick Start

```bash
cd /Users/daniel/Documents/code/enreach-tools
cp .env.example .env
# Edit .env with credentials
uv run enreach --help
uv run pytest
uv run enreach api serve --host 127.0.0.1 --port 8443 --ssl-certfile certs/localhost.pem --ssl-keyfile certs/localhost-key.pem
```

---

## Development Environment

**Tools**:
- **Claude Code** (Terminal): Quick fixes, CLI tasks, debugging
- **ChatGPT Codex** (VS Code): In-editor code completion and explanations
- **Claude AI** (Web): Architecture decisions, documentation, complex refactoring

**Python**: 3.11+, `uv` package manager, `.venv/` virtual environment

**MCP Servers**: Filesystem, GitHub, Atlassian

---

## Project Structure

```
enreach-tools/
├── src/enreach_tools/     # Main source
│   ├── domain/            # Business entities (no dependencies)
│   ├── application/       # Services & use cases
│   ├── infrastructure/    # External adapters (clients, DB)
│   ├── interfaces/        # CLI & API routes
│   ├── api/               # Legacy FastAPI app
│   └── db/                # Legacy models
├── tests/                 # Test suite
├── data/                  # Runtime data, exports
├── docs/                  # Documentation
└── pyproject.toml         # Configuration
```

---

## Architecture

**Layered Architecture**:
```
Interfaces (CLI, API) → Application (Services) → Domain ← → Infrastructure
```

**Key Principles**:
1. Dependencies point inward
2. Domain has no external dependencies
3. Repository pattern for data access
4. Services contain business logic
5. DTOs (Pydantic) for API responses
6. Dependency injection

---

## Working with AI Tools

**When to Use Each**:
- **Claude Code**: CLI tasks, quick fixes, debugging
- **ChatGPT Codex**: In-editor code completion
- **Claude AI**: Architecture, complex refactoring, documentation

**Prompting Examples**:
```bash
# Claude Code
claude "refactor cli.py vcenter to use VCenterService, maintain --all flag"

# ChatGPT Codex (inline comment)
# TODO: Fetch VM from vCenter using pyVmomi, include disks and snapshots

# Claude AI
"Read PROJECT_INSTRUCTIONS.md and create plan for GitLab integration"
```

---

## Development Workflow

```bash
# Daily cycle
cd /Users/daniel/Documents/code/enreach-tools
uv sync
git checkout -b feature/my-feature  # optional
# ... make changes ...
uv run pytest -v
uv run ruff check . && uv run ruff format .
uv run enreach <command>  # manual test
git commit -m "feat: add feature"  # English only
git push origin main
```

**Environment** (`.env` - never commit):
```bash
NETBOX_URL=https://netbox.example.com
NETBOX_TOKEN=token
ENREACH_SECRET_KEY=fernet-key-base64==
ENREACH_API_TOKEN=bearer-token
LOG_LEVEL=debug
```

---

## Code Standards

**Language**: All code, comments, docs, commits in **English only**.

**Python Style**:
- Python 3.11+, 4 spaces, max 120 chars
- `snake_case`: functions/variables
- `PascalCase`: classes
- `UPPER_SNAKE`: constants
- Type hints required for public functions

**Code Examples**:
```python
# Imports: stdlib, third-party, local
import logging
import typer
from enreach_tools.domain.entities import Device

# Domain (no dependencies)
@dataclass(slots=True)
class Device:
    id: int
    name: str
    status: str

# Service
class DeviceService:
    def __init__(self, repo: DeviceRepository):
        self._repo = repo
    
    def get_active(self) -> list[Device]:
        return [d for d in self._repo.list_all() if d.status == "active"]

# DTO
class DeviceDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    
    def dict_clean(self) -> dict:
        return self.model_dump(exclude_none=True)
```

---

## Testing

```
tests/
├── unit/              # Fast, isolated
├── integration/       # With dependencies
└── performance/       # Benchmarks
```

**Examples**:
```python
# Unit test
def test_get_active():
    mock_repo = Mock()
    mock_repo.list_all.return_value = [Device(id=1, name="test", status="active")]
    assert len(DeviceService(mock_repo).get_active()) == 1

# Integration test
def test_api():
    response = TestClient(app).get("/api/devices/1")
    assert response.status_code == 200

# Benchmark
uv run pytest --perf --benchmark-only -m perf
```

---

## Deployment

**Current: Copy & Overwrite**
```bash
# 1. Backup
ssh prod "cp -r /path/app ../backup-$(date +%Y%m%d)"

# 2. Sync
rsync -av --exclude='.git' --exclude='.venv' --exclude='data/' \
  /Users/daniel/Documents/code/enreach-tools/ prod:/path/app/

# 3. Update
ssh prod "cd /path/app && uv sync && uv run alembic upgrade head"

# 4. Restart
ssh prod "systemctl restart enreach-api"
```

**Pre-Deployment Checklist**:
- [ ] Tests pass
- [ ] Ruff checks pass
- [ ] No secrets in code
- [ ] README updated
- [ ] Backup created

---

## Adding Features

**Example: GitLab Integration**

1. **Domain** (`domain/integrations/gitlab.py`):
```python
@dataclass(slots=True)
class GitLabPipeline:
    id: int
    project_id: int
    status: str
    ref: str
```

2. **Client** (`infrastructure/external/gitlab_client.py`):
```python
class GitLabClient:
    def __init__(self, base_url: str, token: str):
        self._base_url = base_url.rstrip("/")
        self._session = requests.Session()
        self._session.headers.update({"PRIVATE-TOKEN": token})
    
    def get_pipeline(self, project_id: int, pipeline_id: int) -> dict:
        url = f"{self._base_url}/api/v4/projects/{project_id}/pipelines/{pipeline_id}"
        resp = self._session.get(url)
        resp.raise_for_status()
        return resp.json()
```

3. **Service** (`application/services/gitlab.py`):
```python
class GitLabService:
    def __init__(self, client: GitLabClient):
        self._client = client
    
    def get_pipeline(self, project_id: int, pipeline_id: int) -> GitLabPipeline:
        data = self._client.get_pipeline(project_id, pipeline_id)
        return GitLabPipeline(
            id=data["id"],
            project_id=data["project_id"],
            status=data["status"],
            ref=data["ref"],
        )
```

4. **DTO** (`application/dto/gitlab.py`):
```python
class GitLabPipelineDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    status: str
    ref: str
```

5. **CLI** (`cli.py`):
```python
@app.command()
def pipeline(project_id: int, pipeline_id: int):
    """Get pipeline details."""
    client = GitLabClient(GITLAB_URL, GITLAB_TOKEN)
    service = GitLabService(client)
    pipeline = service.get_pipeline(project_id, pipeline_id)
    print(f"Pipeline {pipeline.id}: {pipeline.status}")
```

6. **API** (`interfaces/api/routes/gitlab.py`):
```python
@router.get("/projects/{project_id}/pipelines/{pipeline_id}")
def get_pipeline(
    project_id: int,
    pipeline_id: int,
    service: GitLabService = Depends(get_gitlab_service),
):
    pipeline = service.get_pipeline(project_id, pipeline_id)
    return gitlab_pipeline_to_dto(pipeline).dict_clean()
```

7. **Tests**: Add unit and integration tests

8. **Docs**: Update README and `.env.example`

9. **Commit**: `git commit -m "feat: add GitLab pipeline integration"`

---

## Common Tasks

### Adding a vCenter VM Field

1. Update `domain/integrations/vcenter.py`: Add field to `VCenterVM` dataclass
2. Update `infrastructure/external/vcenter_client.py`: Add fetch method
3. Update `application/services/vcenter.py`: Update build, serialize, deserialize methods
4. Update `application/dto/vcenter.py`: Add field to DTO
5. Update web UI: `api/static/app.js` and `api/static/vcenter/view.html`
6. Test: `uv run enreach vcenter refresh --id <id> --vm <vm-id>`

### Database Migration

```bash
# Create migration
uv run alembic revision --autogenerate -m "add new table"

# Review generated migration
cat alembic/versions/xxx_add_new_table.py

# Apply migration
uv run alembic upgrade head

# Rollback if needed
uv run alembic downgrade -1
```

### Cache Management

```bash
# View statistics
uv run enreach cache-stats
uv run enreach cache-stats --json

# In code
from enreach_tools.infrastructure.cache import get_cache
cache = get_cache("netbox.devices", ttl_seconds=300)
cache.clear()  # Invalidate all
cache.invalidate("key")  # Invalidate specific key
```

---

## Troubleshooting

**Module not found**: `uv sync`  
**Tests failing**: `uv run pytest -vv`  
**API won't start**: `lsof -i :8000`, check logs, enable debug: `LOG_LEVEL=debug uv run enreach api serve`  
**vCenter issues**: `ENREACH_LOG_LEVEL=debug uv run enreach vcenter refresh --id <id> --verbose`  
**Database issues**: `sqlite3 data/enreach.db`, `.tables`, `SELECT * FROM table;`

### Debug Logging

```bash
# API
LOG_LEVEL=debug uv run enreach api serve

# CLI
ENREACH_LOG_LEVEL=debug ENREACH_LOG_STRUCTURED=1 uv run enreach <command>
```

---

## Quick Reference

### Common Commands

```bash
# Development
uv run enreach --help
uv run enreach api serve
uv run pytest
uv run ruff check . && uv run ruff format .

# NetBox Export
uv run enreach export update
uv run enreach export cache

# vCenter
uv run enreach vcenter refresh --all
uv run enreach vcenter refresh --id <config-id>

# Commvault
uv run enreach commvault backups
uv run enreach commvault storage list

# Zabbix
uv run enreach zabbix problems
uv run enreach zabbix dashboard

# Atlassian
uv run enreach jira search --q "text"
uv run enreach confluence search --q "text"
uv run enreach confluence publish-cmdb

# Cache & Database
uv run enreach cache-stats
uv run alembic upgrade head
```

### Environment Variables

**Required**:
```bash
NETBOX_URL=https://netbox.example.com
NETBOX_TOKEN=your-token
ENREACH_SECRET_KEY=your-fernet-key-base64==
```

**API Auth**:
```bash
ENREACH_API_TOKEN=bearer-token
ENREACH_UI_PASSWORD=password
```

**Logging**:
```bash
LOG_LEVEL=warning
ENREACH_LOG_LEVEL=info
ENREACH_LOG_STRUCTURED=1
```

**External Systems**:
```bash
# Commvault
COMMVAULT_BASE_URL=https://commvault.example.com
COMMVAULT_API_TOKEN=token

# Zabbix
ZABBIX_URL=https://zabbix.example.com
ZABBIX_USER=username
ZABBIX_PASSWORD=password

# Atlassian
ATLASSIAN_BASE_URL=https://site.atlassian.net
ATLASSIAN_EMAIL=email@example.com
ATLASSIAN_API_TOKEN=token
```

### API Endpoints

**Health**: `GET /health`

**NetBox**:
- `GET /api/devices` - List devices
- `GET /api/vms` - List VMs
- `GET /api/all` - Merged data

**vCenter**:
- `GET /api/vcenter/configs` - List configs
- `POST /api/vcenter/configs/{id}/refresh` - Refresh inventory

**Commvault**:
- `GET /api/commvault/backups` - List backups

**Zabbix**:
- `GET /api/zabbix/problems` - List problems
- `POST /api/zabbix/problems/acknowledge` - Acknowledge

**Logs**: `GET /api/logs/tail?n=200`

### Performance Baselines

| Operation | Duration | Notes |
|-----------|----------|-------|
| NetBox devices | ~15s | 2000 devices |
| NetBox VMs | ~10s | 1000 VMs |
| vCenter single VM | ~5s | With disks/snapshots |
| vCenter full refresh | ~4min | 410 VMs |
| Commvault cache | ~60s | 35MB JSON |

### File Locations

| Purpose | Path |
|---------|------|
| Config | `.env` |
| CLI | `src/enreach_tools/cli.py` |
| API | `src/enreach_tools/api/app.py` |
| Domain | `src/enreach_tools/domain/` |
| Services | `src/enreach_tools/application/services/` |
| Clients | `src/enreach_tools/infrastructure/external/` |
| Exports | `data/` |
| Database | `data/enreach.db` |
| Logs | `logs/` |

---

## Version Control

### Git Workflow

**Main branch**: `main` (production-ready)

**Feature branches** (optional):
```bash
git checkout -b feature/my-feature
git commit -m "feat: add feature"
git push origin feature/my-feature
# Create PR on GitHub
```

### Commit Messages

Format: `<type>: <subject>`

**Types**: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`

**Examples**:
```bash
git commit -m "feat: add GitLab pipeline support"
git commit -m "fix: correct vCenter cache key"
git commit -m "refactor: migrate Zabbix to service layer"
```

**English only** for all commits.

---

## Integration Points

**NetBox**: CMDB (devices, VMs, IPs) - Token auth  
**vCenter**: VM inventory, disks, snapshots - Encrypted password, REST + pyVmomi  
**Commvault**: Backup jobs, storage - Token auth  
**Zabbix**: Monitoring problems, hosts - User/pass or token  
**Jira/Confluence**: Issues, docs - Email + token (read-only from CLI/UI)  
**GitHub**: Code repository - Personal access token, GitHub MCP

---

## Security

### Secrets Management

**Never commit**: API tokens, passwords, private keys, `.env` file

**Encrypted store**:
```python
from enreach_tools.infrastructure.security.secrets import SecretStore
store = SecretStore()
store.set("key", "value")
value = store.get("key")
```

### Authentication

**API** (Bearer token):
```bash
curl -H "Authorization: Bearer $ENREACH_API_TOKEN" \
  http://localhost:8000/api/devices
```

**Web UI** (Session): Login at `/auth/login`

### HTTPS

```bash
# Generate self-signed cert
mkdir -p certs
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout certs/localhost-key.pem \
  -out certs/localhost.pem \
  -subj "/CN=localhost"

# Run with HTTPS
uv run enreach api serve --port 8443 \
  --ssl-certfile certs/localhost.pem \
  --ssl-keyfile certs/localhost-key.pem
```

---

## Resources

### Project Documentation

- `README.md` - User guide
- `CLAUDE.md` - Claude Code guidance
- `AGENTS.md` - Agent behavior
- `docs/architecture_overview.md` - Architecture details
- `docs/vcenter_disk_information.md` - vCenter disk feature
- `docs/performance_benchmarks.md` - Performance baselines
- `docs/refactor_plan.md` - Migration roadmap

### External Documentation

- [uv](https://github.com/astral-sh/uv) - Package manager
- [FastAPI](https://fastapi.tiangolo.com/) - Web framework
- [Typer](https://typer.tiangolo.com/) - CLI framework
- [Pydantic](https://docs.pydantic.dev/) - Data validation
- [SQLAlchemy](https://docs.sqlalchemy.org/) - Database ORM
- [pyVmomi](https://github.com/vmware/pyvmomi) - vCenter SDK
- [pynetbox](https://pynetbox.readthedocs.io/) - NetBox client

---

## Future Improvements

### Planned Features

1. **GitLab Integration**: CI/CD pipelines, repository browsing, merge requests
2. **CI/CD Pipeline**: GitHub Actions, automated tests, Docker build/push
3. **Containerization**: Production Docker image, Docker Compose, health checks
4. **Monitoring**: Prometheus metrics, Grafana dashboards, alerting
5. **Web UI**: Real-time updates (WebSocket), advanced filtering, bulk operations

### Technical Debt

1. **Complete Architecture Migration**: Zabbix to service layer, refactor legacy routes
2. **Increase Test Coverage**: More integration tests, mock external APIs consistently
3. **Documentation**: OpenAPI/Swagger documentation, architecture diagrams

---

## Document Information

**Version**: 1.0  
**Date**: October 17, 2025  
**Maintained By**: Daniel Tromp  
**Project**: Enreach Tools

**Purpose**: Comprehensive project instructions for development, deployment, and maintenance. This document serves as the primary reference for all AI coding assistants (Claude Code, ChatGPT Codex, Claude AI) and human developers.

**Update when**: Adding features, changing architecture, updating workflow, modifying deployment, discovering best practices.

---

*End of Project Instructions*
