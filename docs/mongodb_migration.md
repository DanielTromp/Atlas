# MongoDB Migration Guide

This document describes the migration from SQLite to MongoDB for Infrastructure Atlas application data storage.

## Overview

Infrastructure Atlas now supports MongoDB as the primary storage backend, replacing SQLite for application data. This migration was implemented to:

- Eliminate SQLite lock contention with concurrent agent/MCP access
- Enable document-level updates instead of full file rewrites
- Provide better scalability for multi-user deployments
- Support atomic operations across related data

## Configuration

### Environment Variables

```bash
# Storage backend selection (default: sqlite)
ATLAS_STORAGE_BACKEND=mongodb   # or "sqlite"

# MongoDB connection
MONGODB_URI=mongodb://localhost:27017
MONGODB_DATABASE=atlas
```

### Docker Setup

MongoDB runs alongside Qdrant in the Docker stack:

```yaml
services:
  mongodb:
    image: mongo:7.0
    container_name: atlas-mongodb
    ports:
      - "27017:27017"
    volumes:
      - mongodb_data:/data/db
    environment:
      - MONGO_INITDB_DATABASE=atlas
    restart: unless-stopped

  qdrant:
    # ... existing config unchanged
```

Start with:
```bash
docker compose up -d mongodb
```

## Architecture

### Backend-Aware Services

All services now use a factory pattern that returns the appropriate implementation based on `ATLAS_STORAGE_BACKEND`:

```python
def create_user_service(session=None) -> UserServiceProtocol:
    backend = get_storage_backend()
    if backend == "mongodb":
        return MongoDBUserService(get_mongodb_client().atlas)
    else:
        return SqlAlchemyUserService(session or get_session())
```

### Service Protocol Pattern

Each service defines a protocol type that encompasses both implementations:

```python
UserServiceProtocol = DefaultUserService | MongoDBUserService
ForemanServiceProtocol = ForemanService | MongoDBForemanService
# etc.
```

## Migrated Components

### User Management
| Component | SQLite | MongoDB |
|-----------|--------|---------|
| Users | `users` table | `users` collection |
| User API Keys | `user_api_keys` table | `user_api_keys` collection |
| Global API Keys | `global_api_keys` table | `global_api_keys` collection |
| Role Permissions | `role_permissions` table | `role_permissions` collection |

**Files:**
- `infrastructure/mongodb/repositories.py` - `MongoDBUserRepository`, `MongoDBUserAPIKeyRepository`, `MongoDBGlobalAPIKeyRepository`
- `application/services/users.py` - `create_user_service()`

### Authentication & Sessions
| Component | SQLite | MongoDB |
|-----------|--------|---------|
| Chat Sessions | `chat_sessions` table | `chat_sessions` collection |
| Chat Messages | `chat_messages` table | `chat_messages` collection |

**Files:**
- `infrastructure/mongodb/repositories.py` - `MongoDBChatSessionRepository`
- `interfaces/api/routes/ai_chat.py` - Backend-aware session handling

### Profile Management
| Component | SQLite | MongoDB |
|-----------|--------|---------|
| Profile Service | `ProfileService` | `MongoDBProfileService` |

**Files:**
- `application/services/profile.py` - `MongoDBProfileService`, `create_profile_service()`

### Foreman Integration
| Component | SQLite | MongoDB |
|-----------|--------|---------|
| Foreman Configs | `foreman_configs` table | `foreman_configs` collection |
| Foreman Service | `ForemanService` | `MongoDBForemanService` |

**Files:**
- `infrastructure/mongodb/repositories.py` - `MongoDBForemanConfigRepository`
- `application/services/foreman.py` - `MongoDBForemanService`, `create_foreman_service()`

### Puppet Integration
| Component | SQLite | MongoDB |
|-----------|--------|---------|
| Puppet Configs | `puppet_configs` table | `puppet_configs` collection |
| Puppet Service | `PuppetService` | `MongoDBPuppetService` |

**Files:**
- `infrastructure/mongodb/repositories.py` - `MongoDBPuppetConfigRepository`
- `infrastructure/mongodb/mappers.py` - `puppet_config_to_document()`, `document_to_puppet_config()`
- `application/services/puppet.py` - `MongoDBPuppetService`, `create_puppet_service()`

### vCenter Integration
| Component | SQLite | MongoDB |
|-----------|--------|---------|
| vCenter Configs | `vcenter_configs` table | `vcenter_configs` collection |

**Files:**
- `infrastructure/mongodb/repositories.py` - `MongoDBVCenterConfigRepository`
- `application/services/vcenter.py` - `create_vcenter_service()`

### Playground Usage
| Component | SQLite | MongoDB |
|-----------|--------|---------|
| Playground Usage | `playground_usage` table | `playground_usage` collection |
| Usage Service | `UsageService` | `MongoDBUsageService` |

**Files:**
- `agents/usage.py` - `MongoDBUsageService`, `create_usage_service()`
- `interfaces/api/routes/playground.py` - Updated routes
- `interfaces/api/routes/admin.py` - Updated admin routes
- `agents/playground.py` - Updated usage recording

### AI Usage Tracking
| Component | SQLite | MongoDB |
|-----------|--------|---------|
| AI Activity Logs | `ai_activity_logs` table | `ai_activity_logs` collection |
| AI Model Configs | `ai_model_configs` table | `ai_model_configs` collection |
| AI Usage Service | `AIUsageService` | `MongoDBIAUsageService` |

**Files:**
- `ai/usage_service.py` - `MongoDBIAUsageService`, `create_usage_service()`
- `interfaces/api/routes/ai_usage.py` - Updated all routes

### Bot System
| Component | SQLite | MongoDB |
|-----------|--------|---------|
| Platform Accounts | `bot_platform_accounts` table | `bot_platform_accounts` collection |
| Webhook Configs | `bot_webhook_configs` table | `bot_webhook_configs` collection |
| Conversations | `bot_conversations` table | `bot_conversations` collection |
| Messages | `bot_messages` table | `bot_messages` collection |

**Files:**
- `infrastructure/mongodb/repositories.py` - Bot repositories
- `bots/service.py` - Backend-aware bot service

## MongoDB Collections

### Application Database (`atlas`)

```
users                    - User accounts
user_api_keys           - Per-user API keys for external services
global_api_keys         - Shared API keys
role_permissions        - Role-based permissions
chat_sessions           - AI chat sessions
chat_messages           - Chat message history
vcenter_configs         - vCenter connection configs
foreman_configs         - Foreman connection configs
puppet_configs          - Puppet repository configs
playground_usage        - Agent playground usage logs
playground_sessions     - Playground session state
ai_activity_logs        - AI API call logs
ai_model_configs        - Custom model pricing configs
bot_platform_accounts   - Bot platform credentials
bot_webhook_configs     - Webhook configurations
bot_conversations       - Bot conversation threads
bot_messages            - Bot message history
secrets                 - Encrypted secrets (passwords, tokens)
```

## Indexes

Indexes are defined in `infrastructure/mongodb/indexes.py` and created automatically during migration:

```python
INDEXES = [
    IndexDefinition(collection="users", keys=[("username", 1)], unique=True),
    IndexDefinition(collection="users", keys=[("email", 1)]),
    IndexDefinition(collection="chat_sessions", keys=[("session_id", 1)], unique=True),
    IndexDefinition(collection="chat_sessions", keys=[("user_id", 1), ("updated_at", -1)]),
    # ... see indexes.py for full list
]
```

## Data Migration

### Running Migration

```bash
# Ensure MongoDB is running
docker compose up -d mongodb

# Run migration (migrates SQLite data to MongoDB)
uv run python -m infrastructure_atlas.infrastructure.mongodb.migrations.runner
```

### Migration Scripts

Located in `infrastructure/mongodb/migrations/versions/`:

- `001_initial_schema.py` - Creates collections and indexes
- `002_migrate_sqlite_data.py` - Migrates all SQLite tables to MongoDB

### Verification

```bash
# Verify migration
uv run python scripts/verify_mongodb_migration.py
```

## API Changes

### Routes Updated

All routes that previously used SQLite sessions now use backend-aware factories:

**Before:**
```python
@router.get("/dashboard")
def get_dashboard(db: DbSessionDep):
    service = SomeService(db)
    return service.get_data()
```

**After:**
```python
@router.get("/dashboard")
def get_dashboard():
    service = create_some_service()  # Backend-aware
    return service.get_data()
```

### Dependencies Removed

The following dependencies are no longer required for MongoDB backend:
- `DbSessionDep` - SQLAlchemy session dependency
- Direct `get_sessionmaker()` calls in routes

## Rollback

To switch back to SQLite:

```bash
# Set environment variable
export ATLAS_STORAGE_BACKEND=sqlite

# Restart API server
uv run atlas api serve
```

SQLite files remain intact during MongoDB operation, allowing quick rollback.

## File Changes Summary

### New Files
- `infrastructure/mongodb/client.py` - MongoDB connection manager
- `infrastructure/mongodb/repositories.py` - All MongoDB repositories
- `infrastructure/mongodb/mappers.py` - Document <-> Entity converters
- `infrastructure/mongodb/indexes.py` - Index definitions
- `infrastructure/mongodb/migrations/` - Migration scripts

### Modified Files
- `application/services/*.py` - Added MongoDB service classes and factories
- `interfaces/api/routes/*.py` - Updated to use backend-aware factories
- `interfaces/api/dependencies.py` - Lazy loading, removed direct DB deps
- `agents/usage.py` - MongoDB usage service
- `agents/playground.py` - Backend-aware usage recording
- `ai/usage_service.py` - MongoDB AI usage service

## Troubleshooting

### Connection Issues

```bash
# Check MongoDB is running
docker ps | grep mongodb

# Test connection
mongosh mongodb://localhost:27017/atlas --eval "db.stats()"
```

### Missing Collections

```bash
# Re-run migrations
uv run python -m infrastructure_atlas.infrastructure.mongodb.migrations.runner --force
```

### Data Inconsistency

```bash
# Compare counts between SQLite and MongoDB
uv run python scripts/verify_mongodb_migration.py --verbose
```

## Performance Considerations

- MongoDB connections are pooled (50 max, 10 min)
- Aggregation pipelines used for statistics (efficient for large datasets)
- Indexes on frequently queried fields
- Document-level updates avoid full collection rewrites

## Security

- MongoDB runs without authentication in development (Docker internal network)
- For production, configure authentication:
  ```yaml
  environment:
    - MONGO_INITDB_ROOT_USERNAME=admin
    - MONGO_INITDB_ROOT_PASSWORD=secretpassword
  ```
- Update `MONGODB_URI` to include credentials:
  ```bash
  MONGODB_URI=mongodb://admin:secretpassword@localhost:27017
  ```
