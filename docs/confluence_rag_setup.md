# Confluence RAG Setup Guide

This guide covers the setup and operation of the Confluence RAG (Retrieval-Augmented Generation) system using Qdrant vector database.

## Architecture Overview

The Confluence RAG system uses:
- **Qdrant** - Vector database for storing and searching embeddings
- **nomic-embed-text-v1.5** - Local embedding model (768 dimensions)
- **Docling** - Document parsing and intelligent chunking
- **Semantic search** - Cosine similarity for finding relevant content

### Data Flow

```
Confluence API
    ↓
ConfluenceClient (async, cursor pagination)
    ↓
QdrantSyncEngine (full/incremental)
    ↓
ConfluenceChunker (Docling + intelligent chunking)
    ↓
EmbeddingPipeline (nomic-embed-text-v1.5)
    ↓
QdrantStore (vector storage with HNSW indexing)
    ↓
QdrantSearchEngine (semantic search)
    ↓
REST API / MCP Tools → Claude
```

## Prerequisites

### 1. Start Qdrant

The system uses Qdrant running in Docker:

```bash
# Start Qdrant container
docker compose up -d

# Verify it's running
curl http://localhost:6333/readyz
# Should return: "all shards are ready"

# Check container status
docker ps --filter name=atlas-qdrant
```

### 2. Configure Environment

Add these to your `.env` file:

```bash
# Confluence credentials (required)
ATLAS_RAG_CONFLUENCE_BASE_URL=https://your-company.atlassian.net
ATLAS_RAG_CONFLUENCE_USERNAME=your-email@company.com
ATLAS_RAG_CONFLUENCE_API_TOKEN=your-api-token

# Sync settings (optional)
ATLAS_RAG_WATCHED_SPACES=["INFRA", "SE", "RUNBOOKS"]
ATLAS_RAG_WATCHED_LABELS=["procedure", "how-to", "troubleshooting"]

# Qdrant settings (optional, defaults shown)
ATLAS_RAG_QDRANT_HOST=localhost
ATLAS_RAG_QDRANT_PORT=6333
ATLAS_RAG_QDRANT_GRPC_PORT=6334
```

## Running a Sync

### Initial Full Sync

Use `--full` for the initial population:

```bash
# Sync entire space
uv run python scripts/sync_confluence.py --full -s SPS --no-labels

# Sync specific folder/tree by ancestor ID
uv run python scripts/sync_confluence.py --full -s SPS --ancestor-id "65111963" --no-labels -v
```

### Incremental Sync

After the initial sync, use incremental sync to only process changed pages:

```bash
# Incremental sync - only changed pages
uv run python scripts/sync_confluence.py -s SPS --no-labels

# Incremental sync of specific folder
uv run python scripts/sync_confluence.py -s SPS --ancestor-id "65111963" --no-labels
```

### CLI Options

| Option | Description |
|--------|-------------|
| `--full` | Force full sync (re-process all pages) |
| `-s, --spaces` | Space keys to sync (can repeat) |
| `-l, --labels` | Filter by labels (can repeat) |
| `--no-labels` | Disable label filtering (sync all pages) |
| `--ancestor-id` | Limit sync to a specific page tree |
| `-v, --verbose` | Enable verbose logging |

### When to Use Full vs Incremental

| Scenario | Command |
|----------|---------|
| First time setup | `--full` |
| Daily/regular updates | No `--full` (incremental) |
| After Qdrant reset | `--full` |
| Content seems stale | `--full` |

## Testing Search

### CLI Search Test

```bash
uv run python scripts/search_confluence.py "your query here" --limit 3
```

### API Search Test

```bash
# Start the API server
uv run atlas api serve

# Test search endpoint
curl -X POST http://localhost:8000/confluence-rag/search \
  -H "Content-Type: application/json" \
  -d '{"query": "how to configure", "top_k": 5}'
```

## MCP Integration

The MCP server provides Claude with access to the RAG system.

### Available Tools

| Tool | Purpose |
|------|---------|
| `search_confluence_docs` | Semantic search with citations |
| `generate_guide_from_docs` | Get full page content for guides |
| `get_doc_content` | Get specific page by title |
| `get_confluence_page` | Get page by ID or title+space |
| `list_confluence_spaces` | List available spaces |
| `get_confluence_stats` | Cache statistics |

### Example Usage

**For generating guides:**
```
"Use generate_guide_from_docs to explain how to configure CEPH tenants"
```

**For quick searches:**
```
"Search docs for SFTP user management"
```

**For specific pages:**
```
"Get the full content of 'Create/Remove SFTP users' from docs"
```

## Qdrant Management

### Check Collection Status

```bash
curl http://localhost:6333/collections/confluence_chunks
```

### View Statistics

```bash
uv run python -c "
from infrastructure_atlas.confluence_rag.qdrant_store import QdrantStore
store = QdrantStore()
print(store.get_stats())
print(store.list_spaces())
"
```

### Reset Collection

To start fresh, delete and recreate the collection:

```bash
# Delete collection
curl -X DELETE http://localhost:6333/collections/confluence_chunks

# Re-run sync to recreate
uv run python scripts/sync_confluence.py --full -s SPS --no-labels
```

### Docker Management

```bash
# Stop Qdrant
docker compose down

# Stop and remove data
docker compose down -v

# View logs
docker logs atlas-qdrant

# Restart
docker compose restart
```

## Troubleshooting

### Qdrant Connection Failed

```
Error connecting to Qdrant: ...
Make sure Qdrant is running: docker compose up -d
```

**Solution:** Start the Qdrant container with `docker compose up -d`

### Search Returns 0 Results

1. Check if data was synced:
   ```bash
   curl http://localhost:6333/collections/confluence_chunks
   ```

2. Verify vectors exist (points_count > 0)

3. Run a full sync if empty

### Sync Shows Many Duplicates

Confluence Cloud uses cursor-based pagination. Duplicates are automatically skipped, but if sync doesn't progress:
- Cancel and restart
- Run fresh `--full` sync

### Empty Pages (0 chars)

Some Confluence pages return empty content:
- Stub/redirect pages
- Restricted permission pages
- Unsupported content formats

This is normal and pages are skipped.

## Configuration Reference

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ATLAS_RAG_CONFLUENCE_BASE_URL` | (required) | Confluence base URL |
| `ATLAS_RAG_CONFLUENCE_USERNAME` | (required) | Atlassian email |
| `ATLAS_RAG_CONFLUENCE_API_TOKEN` | (required) | API token |
| `ATLAS_RAG_WATCHED_SPACES` | `["INFRA", "SE", "RUNBOOKS"]` | Spaces to sync |
| `ATLAS_RAG_WATCHED_LABELS` | `["procedure", ...]` | Label filters |
| `ATLAS_RAG_QDRANT_HOST` | `localhost` | Qdrant host |
| `ATLAS_RAG_QDRANT_PORT` | `6333` | Qdrant REST port |
| `ATLAS_RAG_QDRANT_GRPC_PORT` | `6334` | Qdrant gRPC port |
| `ATLAS_RAG_EMBEDDING_MODEL` | `nomic-ai/nomic-embed-text-v1.5` | Embedding model |
| `ATLAS_RAG_EMBEDDING_DIMENSIONS` | `768` | Vector dimensions |
| `ATLAS_RAG_MAX_CHUNK_TOKENS` | `512` | Max tokens per chunk |

### Qdrant Collection Schema

The `confluence_chunks` collection stores:

**Vector:** 768-dimensional float array (cosine distance)

**Payload fields:**
- `chunk_id` - Unique chunk identifier
- `page_id` - Source page ID
- `space_key` - Confluence space key
- `page_title` - Page title
- `page_url` - Full page URL
- `content` - Chunk text content
- `chunk_type` - prose/code/table/list/heading
- `heading_context` - Parent heading
- `context_path` - Breadcrumb trail
- `labels` - Page labels
- `updated_at` - Last update timestamp
- `indexed_at` - When indexed to Qdrant

**Indexes:** space_key, page_id, chunk_type, labels
