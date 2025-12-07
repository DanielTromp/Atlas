# Foreman Integration Proposal for Atlas

## Overview

This document proposes integrating Foreman (https://foreman.service.ispworks.net) into Atlas, following the established patterns used for vCenter and other integrations. The integration will store service account credentials securely in the database and provide API endpoints and CLI commands for managing Foreman configurations.

## Architecture

### 1. Database Model

Create a `ForemanConfig` table similar to `VCenterConfig`:

```python
class ForemanConfig(Base):
    __tablename__ = "foreman_configs"
    __table_args__ = (UniqueConstraint("name", name="uq_foreman_config_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    token_secret: Mapped[str] = mapped_column(String(128), nullable=False)  # Reference to SecretStore
    verify_ssl: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)
```

**Key Points:**
- Service account token stored encrypted via `SecretStore` (similar to vCenter passwords)
- Unique constraint on `name` to prevent duplicates
- `verify_ssl` flag for self-signed certificates

### 2. Module System

Create `ForemanModule` extending `BaseModule`:

- **Location**: `src/infrastructure_atlas/infrastructure/modules/foreman.py`
- **Pattern**: Follow `VCenterModule` structure
- **Health Check**: Verify database configs exist and can connect to Foreman API
- **Metadata**: Display name, description, version, category

### 3. Client Implementation

Create `ForemanClient` for API interactions:

- **Location**: `src/infrastructure_atlas/infrastructure/external/foreman_client.py`
- **Pattern**: Similar to `NetboxClient` or `VCenterClient`
- **Authentication**: Use token in `Authorization` header: `Authorization: Bearer <token>`
- **Endpoints**: Start with basic connectivity and host/hypervisor listing
- **Caching**: Optional TTL cache for API responses

**Foreman API Authentication:**
```python
headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/json",
    "Content-Type": "application/json"
}
```

### 4. Service Layer

Create `ForemanService` for configuration management:

- **Location**: `src/infrastructure_atlas/application/services/foreman.py`
- **Pattern**: Follow `VCenterService` structure
- **Methods**:
  - `list_configs()` - List all Foreman configurations
  - `get_config(config_id)` - Get specific configuration
  - `create_config(name, base_url, token, verify_ssl)` - Create new config
  - `update_config(config_id, ...)` - Update existing config
  - `delete_config(config_id)` - Delete configuration
  - `test_connection(config_id)` - Test API connectivity

### 5. Domain Models

Create domain entities and DTOs:

- **Entity**: `src/infrastructure_atlas/domain/entities.py` - `ForemanConfigEntity`
- **DTO**: `src/infrastructure_atlas/application/dto/foreman.py` - `ForemanConfigDTO`
- **Repository**: `src/infrastructure_atlas/infrastructure/db/repositories.py` - `SqlAlchemyForemanConfigRepository`
- **Mapper**: `src/infrastructure_atlas/infrastructure/db/mappers.py` - `foreman_config_to_entity`

### 6. API Routes

Create REST API endpoints:

- **Location**: `src/infrastructure_atlas/interfaces/api/routes/foreman.py`
- **Endpoints**:
  - `GET /foreman/configs` - List all configurations (admin only)
  - `POST /foreman/configs` - Create new configuration (admin only)
  - `PUT /foreman/configs/{config_id}` - Update configuration (admin only)
  - `DELETE /foreman/configs/{config_id}` - Delete configuration (admin only)
  - `GET /foreman/configs/{config_id}/test` - Test connection (admin only)
  - `GET /foreman/hosts` - List hosts from Foreman (authenticated users)
  - `GET /foreman/hypervisors` - List hypervisors (authenticated users)

### 7. CLI Commands

Create CLI commands:

- **Location**: `src/infrastructure_atlas/interfaces/cli/foreman.py`
- **Commands**:
  - `atlas foreman list` - List configurations
  - `atlas foreman create <name> <url> <token>` - Create configuration
  - `atlas foreman update <config_id>` - Update configuration
  - `atlas foreman delete <config_id>` - Delete configuration
  - `atlas foreman test <config_id>` - Test connection
  - `atlas foreman hosts <config_id>` - List hosts

### 8. Schema Definitions

Create API schemas:

- **Location**: `src/infrastructure_atlas/interfaces/api/schemas/foreman.py`
- **Schemas**:
  - `ForemanConfigCreate` - For POST requests
  - `ForemanConfigUpdate` - For PUT requests
  - `ForemanConfigResponse` - For GET responses

## Implementation Steps

### Phase 1: Database & Core Models
1. Create Alembic migration for `foreman_configs` table
2. Add `ForemanConfig` model to `db/models.py`
3. Create domain entity `ForemanConfigEntity`
4. Create repository and mapper

### Phase 2: Client & Service Layer
1. Implement `ForemanClient` with basic API methods
2. Implement `ForemanService` for configuration management
3. Add secret store integration for token encryption

### Phase 3: Module System
1. Create `ForemanModule` extending `BaseModule`
2. Register module in `loader.py`
3. Implement health check

### Phase 4: API & CLI
1. Create API routes and schemas
2. Create CLI commands
3. Register routes in main API app
4. Register CLI commands in main CLI app

### Phase 5: Testing & Documentation
1. Test API connectivity
2. Test CRUD operations
3. Update documentation

## Security Considerations

1. **Token Storage**: Service account tokens encrypted via `SecretStore` using `ATLAS_SECRET_KEY`
2. **Access Control**: Configuration management restricted to admin users
3. **SSL Verification**: Configurable `verify_ssl` flag for self-signed certificates
4. **API Security**: All API requests use HTTPS with Bearer token authentication

## Example Usage

### Creating a Configuration (CLI)
```bash
uv run atlas foreman create \
  --name "ISPWorks Foreman" \
  --url "https://foreman.service.ispworks.net" \
  --token "<service_account_token>" \
  --verify-ssl true
```

### Creating a Configuration (API)
```bash
curl -X POST http://localhost:8000/api/foreman/configs \
  -H "Authorization: Bearer <atlas_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "ISPWorks Foreman",
    "base_url": "https://foreman.service.ispworks.net",
    "token": "<service_account_token>",
    "verify_ssl": true
  }'
```

### Listing Hosts
```bash
uv run atlas foreman hosts <config_id>
```

## Files to Create/Modify

### New Files
- `alembic/versions/YYYYMMDD_HHMMSS_add_foreman_configs.py`
- `src/infrastructure_atlas/infrastructure/modules/foreman.py`
- `src/infrastructure_atlas/infrastructure/external/foreman_client.py`
- `src/infrastructure_atlas/application/services/foreman.py`
- `src/infrastructure_atlas/application/dto/foreman.py`
- `src/infrastructure_atlas/interfaces/api/routes/foreman.py`
- `src/infrastructure_atlas/interfaces/api/schemas/foreman.py`
- `src/infrastructure_atlas/interfaces/cli/foreman.py`

### Modified Files
- `src/infrastructure_atlas/db/models.py` - Add `ForemanConfig` model
- `src/infrastructure_atlas/domain/entities.py` - Add `ForemanConfigEntity`
- `src/infrastructure_atlas/infrastructure/db/repositories.py` - Add repository
- `src/infrastructure_atlas/infrastructure/db/mappers.py` - Add mapper
- `src/infrastructure_atlas/infrastructure/modules/loader.py` - Register module
- `src/infrastructure_atlas/interfaces/api/routes/__init__.py` - Register router
- `src/infrastructure_atlas/interfaces/cli/__init__.py` - Register CLI app
- `src/infrastructure_atlas/application/services/__init__.py` - Export service

## Dependencies

No new external dependencies required. Foreman API uses standard REST/JSON, so `requests` (already in use) is sufficient.

## Future Enhancements

1. **Host Inventory Export**: Export Foreman hosts to CSV/Excel (similar to Netbox export)
2. **Synchronization**: Sync Foreman hosts with Atlas device inventory
3. **Provisioning**: Trigger Foreman provisioning from Atlas
4. **Monitoring Integration**: Link Foreman hosts with monitoring systems
5. **Search Tool**: Add Foreman search tool for agent queries

## Questions to Resolve

1. What specific Foreman API endpoints should we prioritize? (hosts, hypervisors, facts, etc.)
2. Should we support multiple Foreman instances (like vCenter) or single instance?
3. What data should be exported/synced from Foreman?
4. Should we implement caching for Foreman API responses?

