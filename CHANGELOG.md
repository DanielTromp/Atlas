# Changelog

All notable changes to Infrastructure Atlas are documented here.

## [Unreleased]

### Added

- **RAG Admin Panel in Web UI (2026-01-16)**
  - New "RAG / Knowledge Base" tab under AI & Chat group in admin
  - Stats dashboard showing vector count, pages, spaces, and index size
  - Sync controls with incremental and full sync buttons
  - Space management table with per-space statistics
  - Query analytics showing total queries, response times, hit rate
  - Recent queries table with timing and result counts
  - "Queries Without Results" tracking to identify documentation gaps
  - Search settings (threshold, max results) configuration UI
  - Add/remove space functionality for managing indexed content

- **RAG Sync Timestamp Tracking (2026-01-16)**
  - Sync metadata now persisted to `data/rag_sync_metadata.json`
  - "Last sync" shows when sync actually ran (not when data was last modified)
  - Displays sync type (incremental/full) alongside timestamp
  - Timestamp updates even when sync finds no changes to process

- **RAG API Analytics Endpoint**
  - New `/confluence-rag/analytics` endpoint for query statistics
  - In-memory query logging with configurable retention
  - Period filtering (today/week/month/all)
  - Failed query tracking for identifying content gaps

- **RAG Space Management API**
  - New `DELETE /confluence-rag/spaces/{space_key}` endpoint
  - Removes all indexed content for a specific Confluence space

- **Per-Session AI Model Persistence (2026-01-16)**
  - Each chat session now remembers its AI model and provider
  - Switching between sessions automatically loads the model that was used
  - Changing model within a session persists to the database
  - New `PATCH /ai/sessions/{session_id}` endpoint for updating session settings

### Changed

- **RAG: Migrated to Google Gemini embeddings (2026-01-16)**
  - Default embedding provider changed from `local` (Nomic) to `gemini` (Google API)
  - Uses `text-embedding-004` model (FREE tier, 768 dimensions, excellent quality)
  - Migrated from deprecated `google.generativeai` to new `google.genai` SDK
  - Added `ATLAS_RAG_QDRANT_COLLECTION` env var to specify collection name
  - Fixed bug where `QdrantStore` was not reading collection name from settings
  - Documentation updated in `docs/confluence_rag_setup.md`

- **Chat UI: Added loading spinner and cancel functionality**
  - Send button transforms to "Cancel" during AI processing
  - AbortController support for canceling in-flight requests
  - Improved spinner animation (ring-style instead of solid)
  - Red cancel button styling with hover effects

### Fixed

- **RAG search returning no results**: Fixed `QdrantStore.__init__()` not passing `collection_name` from settings to `QdrantConfig`, causing API to search wrong collection

### Dependencies

- Added `google-genai>=1.0.0` (replaces `google-generativeai>=0.8.0`)

---

## Previous Changes

See git history for earlier changes.
