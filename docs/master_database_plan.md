# Master Database Implementation Plan

## Vision

Create a comprehensive shadow NetBox system that aggregates data from all infrastructure services, enabling:
- Centralized data validation and verification before updating production NetBox
- AI-powered issue resolution and knowledge base maintenance
- Unified interface for querying infrastructure state across all systems
- Historical tracking and analysis capabilities

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     Enreach Tools Platform                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────┐    │
│  │   Web UI    │  │  CLI Tools   │  │   AI Assistant      │    │
│  └─────────────┘  └──────────────┘  └─────────────────────┘    │
│         │                │                      │                │
│  ┌──────────────────────────────────────────────────────┐       │
│  │            Application Services Layer                 │       │
│  │  - Data Sync  - Validation  - AI Integration         │       │
│  └──────────────────────────────────────────────────────┘       │
│         │                                                         │
│  ┌──────────────────────────────────────────────────────┐       │
│  │              Master Database (SQLite)                 │       │
│  │                                                        │       │
│  │  ├─ devices (generic device table)                   │       │
│  │  ├─ network_interfaces                               │       │
│  │  ├─ ip_addresses                                      │       │
│  │  ├─ vms (vCenter VMs)                                │       │
│  │  ├─ storage_volumes (Dorado/NetApp)                 │       │
│  │  ├─ backups (Commvault)                              │       │
│  │  ├─ configurations (Oxidized)                        │       │
│  │  ├─ server_facts (Foreman/Puppet)                   │       │
│  │  ├─ kb_articles (Confluence cache)                   │       │
│  │  ├─ issues (Jira cache)                              │       │
│  │  ├─ embeddings (vector storage for AI)              │       │
│  │  └─ sync_history (audit trail)                       │       │
│  └──────────────────────────────────────────────────────┘       │
│         │                                                         │
│  ┌──────────────────────────────────────────────────────┐       │
│  │         External Service Integrations                 │       │
│  │                                                        │       │
│  │  vCenter │ Commvault │ Oxidized │ Foreman/Puppet    │       │
│  │  Dorado  │ NetApp    │ NetBox   │ Confluence/Jira   │       │
│  └──────────────────────────────────────────────────────┘       │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

## Implementation Phases

### Phase 1: Foundation (4-6 hours)
- [ ] Database schema design and migrations
- [ ] Generic device model abstraction
- [ ] Data sync framework
- [ ] Production deployment mechanism

### Phase 2: Service Integration (8-12 hours)
- [ ] Oxidized integration (network device configs)
- [ ] Foreman integration (server inventory)
- [ ] Puppet integration (server facts)
- [ ] Storage integration (Dorado/NetApp)

### Phase 3: Knowledge Base & AI (6-8 hours)
- [ ] Confluence/Jira caching
- [ ] Vector embeddings storage
- [ ] AI assistant integration
- [ ] Issue resolution workflow

### Phase 4: NetBox Sync (4-6 hours)
- [ ] NetBox data validation
- [ ] Sync mechanism with approval workflow
- [ ] Conflict resolution
- [ ] Audit logging

---

## Detailed Steps

### Phase 1: Foundation

#### Step 1.1: Design Generic Device Schema (45 min)
**Goal**: Create a unified device model that works across all systems

**Tasks**:
- [ ] Create `docs/database_schema.md` documenting the generic device model
- [ ] Design `devices` table with fields: id, name, type, source_system, source_id, metadata (JSON), last_seen, created_at, updated_at
- [ ] Design `device_relationships` table for device-to-device connections
- [ ] Design `sync_metadata` table to track data freshness per source

**Output**: Schema documentation ready for implementation

---

#### Step 1.2: Create Database Migration (45 min)
**Goal**: Implement the generic device schema in SQLite

**Tasks**:
- [ ] Create Alembic migration for `devices` table
- [ ] Create migration for `device_relationships` table
- [ ] Create migration for `sync_metadata` table
- [ ] Add indexes for common queries (source_system, source_id, type)
- [ ] Run migration: `uv run alembic upgrade head`

**Validation**:
```bash
sqlite3 data/enreach.db ".schema devices"
```

---

#### Step 1.3: Create Generic Device Domain Model (45 min)
**Goal**: Add domain entities for the generic device model

**Tasks**:
- [ ] Create `src/enreach_tools/domain/models/device.py` with `Device` dataclass
- [ ] Add `DeviceType` enum (server, network_device, vm, storage, etc.)
- [ ] Add `SourceSystem` enum (vcenter, foreman, oxidized, etc.)
- [ ] Create `DeviceRelationship` dataclass for connections
- [ ] Add validation logic for device metadata

**Output**: Domain models ready for use in services

---

#### Step 1.4: Create Sync Framework (60 min)
**Goal**: Build reusable sync framework for all integrations

**Tasks**:
- [ ] Create `src/enreach_tools/application/services/sync_framework.py`
- [ ] Implement `SyncService` base class with:
  - `fetch()` - retrieve data from source
  - `transform()` - convert to generic Device model
  - `load()` - write to database
  - `mark_stale()` - mark missing devices as stale
- [ ] Add `SyncResult` dataclass (added, updated, removed counts)
- [ ] Create repository interface for device CRUD operations
- [ ] Add logging and error handling

**Validation**: Unit tests for sync framework

---

#### Step 1.5: Production Deployment Script (45 min)
**Goal**: Automated deployment mechanism replacing manual copying

**Tasks**:
- [ ] Create `scripts/deploy_to_production.sh` script
- [ ] Add pre-deployment checks (tests pass, migrations ready)
- [ ] Implement database backup before deployment
- [ ] Add rsync or similar for file sync
- [ ] Include service restart logic
- [ ] Add rollback mechanism on failure
- [ ] Document deployment process in `docs/deployment.md`

**Validation**: Test deployment to staging environment

---

### Phase 2: Service Integration

#### Step 2.1: Oxidized Integration - Connection (45 min)
**Goal**: Connect to Oxidized API and retrieve device list

**Tasks**:
- [ ] Create `src/enreach_tools/infrastructure/external/oxidized_client.py`
- [ ] Add Oxidized configuration to config model (URL, auth)
- [ ] Implement `get_devices()` method
- [ ] Add error handling and retries
- [ ] Test connection with production Oxidized instance

**Validation**:
```bash
uv run enreach oxidized list
```

---

#### Step 2.2: Oxidized Integration - Config Storage (60 min)
**Goal**: Store device configurations in database

**Tasks**:
- [ ] Create migration for `device_configs` table (device_id, config_text, version, retrieved_at)
- [ ] Implement `get_device_config(device_name)` in client
- [ ] Create `OxidizedSyncService` extending `SyncService`
- [ ] Transform Oxidized devices to generic `Device` model (type=network_device)
- [ ] Store configs with versioning
- [ ] Add CLI command: `uv run enreach oxidized refresh`

**Validation**: Configs visible in database and web UI

---

#### Step 2.3: Foreman Integration - Server Inventory (60 min)
**Goal**: Sync server inventory from Foreman

**Tasks**:
- [ ] Create `src/enreach_tools/infrastructure/external/foreman_client.py`
- [ ] Add Foreman configuration (URL, auth)
- [ ] Implement `get_hosts()` method to retrieve server list
- [ ] Create `ForemanSyncService`
- [ ] Transform Foreman hosts to `Device` model (type=server)
- [ ] Extract metadata: OS, IP addresses, host groups, environment
- [ ] Add CLI command: `uv run enreach foreman refresh`

**Validation**: Foreman servers appear in unified device list

---

#### Step 2.4: Puppet Integration - Facts Collection (60 min)
**Goal**: Enrich server data with Puppet facts

**Tasks**:
- [ ] Create `src/enreach_tools/infrastructure/external/puppet_client.py`
- [ ] Implement PuppetDB query interface
- [ ] Create migration for `puppet_facts` table
- [ ] Implement `get_facts(certname)` method
- [ ] Store key facts: CPU, memory, disks, kernel, uptime
- [ ] Link facts to devices via certname/hostname matching
- [ ] Add CLI command: `uv run enreach puppet refresh`

**Validation**: Puppet facts visible in server detail view

---

#### Step 2.5: Storage Integration - Dorado (45 min)
**Goal**: Inventory Dorado SAN storage

**Tasks**:
- [ ] Create `src/enreach_tools/infrastructure/external/dorado_client.py`
- [ ] Add Dorado configuration (REST API endpoint, auth)
- [ ] Implement `get_luns()` and `get_filesystems()` methods
- [ ] Create migration for `storage_volumes` table
- [ ] Create `DoradoSyncService`
- [ ] Store volume metadata: capacity, allocated, RAID level, controller
- [ ] Add CLI command: `uv run enreach storage refresh --type dorado`

**Validation**: Storage volumes visible in web UI

---

#### Step 2.6: Storage Integration - NetApp (45 min)
**Goal**: Inventory NetApp NAS storage

**Tasks**:
- [ ] Create `src/enreach_tools/infrastructure/external/netapp_client.py`
- [ ] Add NetApp configuration (ONTAP API endpoint, auth)
- [ ] Implement `get_volumes()` and `get_qtrees()` methods
- [ ] Extend `storage_volumes` table for NAS-specific fields
- [ ] Create `NetAppSyncService`
- [ ] Store volume metadata: aggregates, snapshots, quotas, exports
- [ ] Add CLI command: `uv run enreach storage refresh --type netapp`

**Validation**: NetApp volumes visible alongside Dorado in unified view

---

#### Step 2.7: Unified Device View (60 min)
**Goal**: Web UI showing all devices from all sources

**Tasks**:
- [ ] Create API endpoint: `GET /api/devices`
- [ ] Add filtering by source_system, device_type, status
- [ ] Create `static/devices/index.html` with unified device table
- [ ] Add columns: Name, Type, Source, Last Seen, Status
- [ ] Implement search across all device types
- [ ] Add device detail page showing source-specific metadata
- [ ] Link to source system (e.g., vCenter VM → vCenter detail page)

**Validation**: Can browse all infrastructure devices in one place

---

### Phase 3: Knowledge Base & AI

#### Step 3.1: Confluence Cache - Articles (60 min)
**Goal**: Cache Confluence pages for offline access and AI processing

**Tasks**:
- [ ] Create migration for `kb_articles` table (id, space_key, title, body_text, body_html, url, last_updated)
- [ ] Create `src/enreach_tools/infrastructure/external/confluence_client.py`
- [ ] Implement `get_spaces()` and `get_pages(space_key)` methods
- [ ] Create `ConfluenceSyncService`
- [ ] Store both HTML (for display) and plain text (for AI)
- [ ] Add CLI command: `uv run enreach kb refresh`

**Validation**: Confluence articles cached in database

---

#### Step 3.2: Jira Cache - Issues (45 min)
**Goal**: Cache Jira issues for AI-powered resolution suggestions

**Tasks**:
- [ ] Create migration for `issues` table (key, summary, description, status, resolution, assignee, created, updated)
- [ ] Create `src/enreach_tools/infrastructure/external/jira_client.py`
- [ ] Implement `get_issues(jql)` method
- [ ] Cache issues from specific projects
- [ ] Store comments for context
- [ ] Add CLI command: `uv run enreach issues refresh`

**Validation**: Jira issues cached and browsable

---

#### Step 3.3: Vector Embeddings Setup (60 min)
**Goal**: Create vector storage for semantic search

**Tasks**:
- [ ] Create migration for `embeddings` table (content_type, content_id, embedding_vector, model_version, created_at)
- [ ] Add dependency: `sentence-transformers` or similar
- [ ] Create `src/enreach_tools/application/services/embedding_service.py`
- [ ] Implement `generate_embedding(text)` using open-source model
- [ ] Create `search_similar(query, limit)` using cosine similarity
- [ ] Add index for efficient vector search

**Validation**: Can find similar KB articles by semantic search

---

#### Step 3.4: KB Article Vectorization (45 min)
**Goal**: Generate embeddings for all cached KB articles

**Tasks**:
- [ ] Create background job to process KB articles
- [ ] Chunk long articles (max 512 tokens per chunk)
- [ ] Generate embeddings for each chunk
- [ ] Store in `embeddings` table linked to `kb_articles`
- [ ] Add CLI command: `uv run enreach kb vectorize`
- [ ] Track vectorization status per article

**Validation**: All KB articles have embeddings

---

#### Step 3.5: Issue Vectorization (45 min)
**Goal**: Generate embeddings for Jira issues and resolutions

**Tasks**:
- [ ] Process issue summary + description + resolution
- [ ] Generate embeddings for resolved issues
- [ ] Create index of issue patterns
- [ ] Add CLI command: `uv run enreach issues vectorize`

**Validation**: Can search for similar resolved issues

---

#### Step 3.6: AI Assistant - Basic Integration (60 min)
**Goal**: Add AI-powered query interface

**Tasks**:
- [ ] Create `src/enreach_tools/application/services/ai_assistant.py`
- [ ] Add configuration for AI model (Anthropic API, OpenAI, or local)
- [ ] Implement `query(question, context)` method
- [ ] Create context builder from vector search results
- [ ] Add web UI endpoint: `POST /api/ai/query`
- [ ] Create simple chat interface in web UI

**Validation**: Can ask questions about infrastructure and get AI responses

---

#### Step 3.7: AI Assistant - Issue Resolution (60 min)
**Goal**: AI-powered suggestions for new issues based on historical resolutions

**Tasks**:
- [ ] Implement `suggest_resolution(issue_description)` method
- [ ] Search for similar resolved issues using embeddings
- [ ] Retrieve relevant KB articles
- [ ] Generate resolution suggestion with references
- [ ] Add confidence scoring
- [ ] Create UI for issue resolution workflow

**Validation**: Given a problem description, get actionable suggestions

---

#### Step 3.8: AI Assistant - KB Maintenance (45 min)
**Goal**: AI suggestions for KB improvements

**Tasks**:
- [ ] Implement `analyze_kb_gaps()` - find topics with many issues but no KB
- [ ] Implement `suggest_kb_updates()` - identify outdated articles
- [ ] Detect duplicate/overlapping articles
- [ ] Create maintenance dashboard in web UI
- [ ] Add CLI command: `uv run enreach kb analyze`

**Validation**: Get list of KB improvement suggestions

---

### Phase 4: NetBox Sync

#### Step 4.1: NetBox Data Model Mapping (60 min)
**Goal**: Map generic device model to NetBox schema

**Tasks**:
- [ ] Document NetBox API endpoints and data models in `docs/netbox_mapping.md`
- [ ] Create mapping rules: Device → NetBox device
- [ ] Map network interfaces, IPs, connections
- [ ] Handle NetBox-specific fields (site, rack, role, platform)
- [ ] Create validation rules for required NetBox fields

**Output**: Clear mapping documentation

---

#### Step 4.2: NetBox Client (45 min)
**Goal**: Create NetBox API client

**Tasks**:
- [ ] Create `src/enreach_tools/infrastructure/external/netbox_client.py`
- [ ] Implement CRUD methods for devices, interfaces, IPs
- [ ] Add error handling for NetBox API
- [ ] Test against production NetBox instance
- [ ] Add dry-run mode for safety

**Validation**: Can read NetBox data via client

---

#### Step 4.3: Data Validation Framework (60 min)
**Goal**: Validate data before syncing to NetBox

**Tasks**:
- [ ] Create `src/enreach_tools/application/services/netbox_validator.py`
- [ ] Implement validation rules:
  - Required fields present
  - IP addresses valid and not duplicated
  - Devices have valid site/role
  - Interface names standardized
- [ ] Create validation report format
- [ ] Add CLI command: `uv run enreach netbox validate`

**Validation**: Get clear report of data issues before sync

---

#### Step 4.4: Sync Preview & Approval (60 min)
**Goal**: Show changes before applying to NetBox

**Tasks**:
- [ ] Implement diff generation (additions, updates, deletions)
- [ ] Create web UI page for sync preview
- [ ] Show side-by-side comparison of current vs proposed state
- [ ] Add approval workflow (approve all, approve selected, reject)
- [ ] Store approval history in database
- [ ] Add CLI command: `uv run enreach netbox preview`

**Validation**: Can review and approve changes safely

---

#### Step 4.5: NetBox Sync Implementation (60 min)
**Goal**: Execute approved syncs to NetBox

**Tasks**:
- [ ] Create `NetBoxSyncService`
- [ ] Implement `sync_devices(approved_changes)` method
- [ ] Add transaction/rollback support
- [ ] Handle partial failures gracefully
- [ ] Log all changes to `sync_history` table
- [ ] Add CLI command: `uv run enreach netbox sync --approve`

**Validation**: Successfully update NetBox with new data

---

#### Step 4.6: Conflict Resolution (45 min)
**Goal**: Handle conflicts when NetBox data differs from sources

**Tasks**:
- [ ] Detect conflicts (same device in multiple sources)
- [ ] Implement resolution strategies:
  - Source priority (prefer vCenter over Foreman)
  - Newest data wins
  - Manual resolution
- [ ] Create conflict resolution UI
- [ ] Add CLI command: `uv run enreach netbox conflicts`

**Validation**: Conflicts are detected and can be resolved

---

#### Step 4.7: Audit & History (45 min)
**Goal**: Complete audit trail of all syncs

**Tasks**:
- [ ] Enhance `sync_history` table with detailed change logs
- [ ] Create web UI page for sync history
- [ ] Add filtering by source, device, date range
- [ ] Implement rollback capability for recent syncs
- [ ] Add CLI command: `uv run enreach netbox history`

**Validation**: Can see complete history of NetBox changes

---

## Production Deployment Process

### Current State
- Manual copy of environment to production
- Risk of inconsistency and downtime

### Target State
- Automated deployment with validation
- Zero-downtime updates
- Automatic rollback on failure

### Deployment Script Flow
```bash
#!/bin/bash
# scripts/deploy_to_production.sh

1. Run tests: uv run pytest
2. Check migrations: uv run alembic check
3. Backup production database: cp data/enreach.db data/enreach.db.backup
4. Sync code: rsync -av --exclude data/ ./ production:/app/
5. Run migrations on production: ssh production "cd /app && uv run alembic upgrade head"
6. Restart services: ssh production "systemctl restart enreach-api"
7. Health check: curl https://production/api/health
8. Rollback on failure: restore backup and restart
```

---

## Success Metrics

- [ ] All 7 data sources integrated (vCenter, Commvault, Oxidized, Foreman, Puppet, Dorado, NetApp)
- [ ] 100% of infrastructure devices in unified view
- [ ] AI assistant can answer questions about infrastructure
- [ ] KB vectorization covers all articles
- [ ] NetBox sync preview shows accurate changes
- [ ] Production deployment takes <5 minutes
- [ ] Zero data loss during deployments

---

## Future Enhancements

- Real-time sync using webhooks from source systems
- Automated anomaly detection (devices in one system but not another)
- Predictive maintenance using ML on historical data
- GraphQL API for complex queries
- Mobile app for infrastructure dashboard
- Integration with monitoring systems (Prometheus, Grafana)
- Multi-tenant support for managing multiple environments

---

## Notes

**Development Approach**:
- Each step should take ~45-60 minutes
- Test thoroughly before moving to next step
- Update this checklist as work progresses
- Document learnings in relevant docs files

**Database Choice**:
- SQLite is sufficient for personal project
- Easy backup/restore for deployment
- Can migrate to PostgreSQL if needed later

**AI Model Strategy**:
- Start with Anthropic Claude API for best results
- Can switch to open-source models (Llama, Mistral) for cost savings
- Keep embedding model open-source (sentence-transformers) to avoid API costs

**Security**:
- All credentials in `.env` file (never commit)
- Use encrypted storage for sensitive configs
- API authentication for all endpoints
- Audit logging for NetBox changes
