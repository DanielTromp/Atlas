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

To populate or update the RAG database from Confluence:

```bash
uv run python scripts/sync_confluence.py --full --spaces "SPS" --ancestor-id "65111963" -v
```

*   `--full`: Forces valid full sync of specified spaces.
*   `--spaces "KEY"`: Space keys to sync.
*   `--ancestor-id "ID"`: Limit sync to a specific page tree (useful for testing).
*   `-v`: Verbose logging (shows chunk creation details).

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

The system exposes an MCP Tool named **`search_confluence_docs`**.

### How to Use
In your LLM/Agent (e.g., Claude Desktop), simply ask questions related to the documentation content.

**Prompting Tips:**
*   "Search Confluence for..."
*   "Check the documentation about..."
*   "How do I configure X (check docs)?"

### Tool Implementation (`src/mcp_server/tools/search.py`)
The tool effectively wraps the `HybridSearchEngine`. It:
1.  Accepts a `query`.
2.  Performs vector + keyword search.
3.  Returns a formatted string containing relevant snippets and their Source URLs.
