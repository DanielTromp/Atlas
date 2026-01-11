# Confluence RAG Implementation Guide

Successful deployment and debugging of the Confluence RAG (Retrieval-Augmented Generation) system.

## 1. Architecture & Design Decisions

### Database Schema (DuckDB)
The core database utilizes DuckDB with the `vss` (vector similarity search) extension.

**Critical Configuration: No Foreign Keys**
Due to limitations in DuckDB's constraint handling within high-churn transaction environments (like syncs), we have **disabled foreign key constraints** between `chunk_embeddings` and `chunks`.

*   **Rationale:** Foreign Key `ON DELETE CASCADE` can be unreliable or strict about transaction visibility in DuckDB.
*   **Implementation:** The `chunk_embeddings` table does *not* technically reference `chunks` in the schema.
*   **Integrity:** Data integrity is managed at the **application layer** in `sync.py`. The sync engine explicitly cleans up orphan embeddings before deleting chunks.

### Transactional Logic
The sync process uses a **Two-Step Transaction** approach:
1.  **Cleanup (Tx 1):** Identify existing chunks for a page, explicitly delete their embeddings, then delete the chunks. Commit.
2.  **Upsert (Tx 2):** Insert/Update the Page record, generate new Chunks, and insert new Embeddings. Commit.

This ensures that we never block on an "integrity violation" while still maintaining a clean dataset.

## 2. Running a Sync

### Initial Full Sync (First Time)

Use `--full` for the initial population of the database:

```bash
# Sync entire space
uv run python scripts/sync_confluence.py --full -s SPS --no-labels

# Sync specific folder/tree by ancestor ID
uv run python scripts/sync_confluence.py --full -s SPS --ancestor-id "65111963" --no-labels -v
```

### Subsequent Syncs (Incremental)

After the initial sync, use **incremental sync** (omit `--full`) to only process pages modified since the last sync:

```bash
# Incremental sync - only changed pages since last sync
uv run python scripts/sync_confluence.py -s SPS --no-labels

# Incremental sync of specific folder
uv run python scripts/sync_confluence.py -s SPS --ancestor-id "65111963" --no-labels
```

### When to Use Full vs Incremental

| Scenario | Command |
|----------|---------|
| First time setup | `--full` |
| Daily/regular updates | No `--full` (incremental) |
| After schema changes | `--full` |
| After deleting the database | `--full` |
| Content seems stale/missing | `--full` |

### CLI Options Reference

*   `--full`: Forces full sync (re-process all pages, ignores last sync timestamp)
*   `--spaces "KEY"`, `-s`: Space keys to sync (can repeat for multiple spaces)
*   `--labels "LABEL"`, `-l`: Filter by labels (can repeat)
*   `--no-labels`: Disable label filtering (sync all pages in space)
*   `--ancestor-id "ID"`: Limit sync to a specific page tree
*   `-v`, `--verbose`: Verbose logging (shows chunk creation details)

## 3. Testing Search (CLI)

You can verify the data without using the LLM by running the standalone search script:

```bash
uv run python scripts/search_confluence.py "your query here" --limit 3
```

**Example Output:**
```text
Found 5 results in 42ms

============================================================
1. Deployment Guide
   Space: SPS
   Score: 89.12%
------------------------------------------------------------
> "The automated deployment pipeline runs on..."
   (Confidence: 95%)

   URL: https://yourdomain.atlassian.net/wiki/spaces/SPS/pages/123/Deployment
```

## 4. MCP Integration

The system exposes several MCP tools for accessing documentation from Claude.

### Available Tools

| Tool | Purpose |
|------|---------|
| `search_confluence_docs` | Search and return snippets with links |
| `generate_guide_from_docs` | **Search and return FULL page content** (recommended for guides) |
| `get_doc_content` | Get full content of a specific page by title |
| `get_confluence_page` | Get a page by ID or title+space |
| `list_confluence_spaces` | List available spaces |
| `get_confluence_stats` | Cache statistics |

### Recommended Usage

**For generating guides/documentation (use RAG only, no Confluence fetch):**
```
"Use generate_guide_from_docs to explain how to configure CEPH tenants"
"Generate a guide from docs about MS Defender setup"
```

**For quick searches (returns snippets):**
```
"Search docs for SFTP user management"
```

**For specific page content:**
```
"Get the full content of 'Create/Remove SFTP users' from docs"
```

### Tool Details

#### `generate_guide_from_docs` (Recommended)
- Searches documentation and returns **full page content**
- No need to fetch from Confluence separately
- Best for creating comprehensive guides
- Parameters:
  - `query`: Search terms
  - `max_pages`: Number of pages to include (default 5)

#### `search_confluence_docs`
- Returns snippets with citations and URLs
- Good for quick lookups
- May trigger Claude to fetch full pages from Atlassian MCP

### Implementation
The tools wrap the `HybridSearchEngine` which performs:
1. Vector similarity search (semantic)
2. BM25 keyword search
3. Reciprocal Rank Fusion scoring

## 5. Database Maintenance

### Check Database Status

```bash
uv run python scripts/inspect_db.py
```

### Database Bloat

The DuckDB database can grow large over time due to delete/update cycles during syncs (page count stays the same but file size grows). If the database grows significantly larger than expected, compact it:

```bash
# Check current size
ls -lh data/atlas_confluence_rag.duckdb

# Compact the database (creates a fresh copy without dead rows)
uv run python -c "
import duckdb
old = duckdb.connect('data/atlas_confluence_rag.duckdb', read_only=True)
new = duckdb.connect('data/atlas_confluence_rag_new.duckdb')
for table in ['pages', 'chunks', 'chunk_embeddings', 'sync_state', 'search_cache']:
    new.execute(f\"ATTACH 'data/atlas_confluence_rag.duckdb' AS old (READ_ONLY)\")
    new.execute(f'CREATE TABLE {table} AS SELECT * FROM old.{table}')
    new.execute('DETACH old')
new.close()
old.close()
"

# Replace old with compacted version
mv data/atlas_confluence_rag.duckdb data/atlas_confluence_rag_old.duckdb
mv data/atlas_confluence_rag_new.duckdb data/atlas_confluence_rag.duckdb
rm data/atlas_confluence_rag_old.duckdb
```

**Expected database sizes:**
- ~100 pages: ~10-20 MB
- ~500 pages: ~50-100 MB
- ~1000 pages: ~100-200 MB

If significantly larger, the database needs compacting.

### Reset Database

To start completely fresh:

```bash
rm data/atlas_confluence_rag.duckdb
uv run python scripts/sync_confluence.py --full -s SPS --no-labels
```

## 6. Troubleshooting

### Search Returns 0 Results

1. Check if data exists: `uv run python scripts/inspect_db.py`
2. Verify embeddings exist (should match chunk count)
3. Test vector search directly to isolate the issue

### Sync Gets Stuck or Shows Many Duplicates

Confluence Cloud uses cursor-based pagination. If you see endless duplicates:
- The sync will skip duplicates automatically
- If it doesn't progress, cancel and restart
- Delete DB and run fresh `--full` sync if needed

### Empty Pages (0 chars)

Some Confluence pages return empty content and are skipped:
- Pages that are stubs/redirects
- Pages with restricted permissions
- Pages with content in unsupported formats

This is normal behavior.
