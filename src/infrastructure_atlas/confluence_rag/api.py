import asyncio
import json
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from infrastructure_atlas.confluence_rag.chunker import ConfluenceChunker
from infrastructure_atlas.confluence_rag.citations import CitationExtractor
from infrastructure_atlas.confluence_rag.config import ConfluenceRAGSettings
from infrastructure_atlas.confluence_rag.confluence_client import ConfluenceClient
from infrastructure_atlas.confluence_rag.embeddings import get_embedding_pipeline
from infrastructure_atlas.confluence_rag.models import SearchResponse

# Qdrant-based implementations
from infrastructure_atlas.confluence_rag.qdrant_search import QdrantSearchEngine, SearchConfig
from infrastructure_atlas.confluence_rag.qdrant_store import QdrantStore
from infrastructure_atlas.confluence_rag.qdrant_sync import QdrantSyncEngine

logger = logging.getLogger(__name__)

# Analytics persistence file
ANALYTICS_FILE = Path(os.getenv("ATLAS_DATA_DIR", "data")) / "rag_query_analytics.json"

# Sync metadata persistence file (tracks when sync last ran)
SYNC_METADATA_FILE = Path(os.getenv("ATLAS_DATA_DIR", "data")) / "rag_sync_metadata.json"


def _load_sync_metadata() -> dict:
    """Load sync metadata from JSON file."""
    if not SYNC_METADATA_FILE.exists():
        return {}
    try:
        with open(SYNC_METADATA_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load sync metadata: {e}")
        return {}


def _save_sync_metadata(sync_type: str):
    """Save sync metadata with current timestamp."""
    try:
        SYNC_METADATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "last_sync_run": datetime.utcnow().isoformat(),
            "last_sync_type": sync_type,
        }
        with open(SYNC_METADATA_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.warning(f"Failed to save sync metadata: {e}")


# ────────────────────────────────────────────────────────────────────────────────
# Query Analytics (Persistent)
# ────────────────────────────────────────────────────────────────────────────────
@dataclass
class QueryLog:
    """A single query log entry."""
    query: str
    timestamp: datetime
    result_count: int
    top_score: float | None
    duration_ms: int


@dataclass
class QueryAnalytics:
    """Persistent query analytics tracker with JSON file storage."""
    queries: deque = field(default_factory=lambda: deque(maxlen=1000))
    failed_queries: dict = field(default_factory=dict)  # query -> {"count": N, "last_occurred": datetime}

    def __post_init__(self):
        """Load existing data on initialization."""
        self._load()

    def _load(self):
        """Load analytics from JSON file."""
        if not ANALYTICS_FILE.exists():
            return

        try:
            with open(ANALYTICS_FILE, "r") as f:
                data = json.load(f)

            # Load queries
            for q in data.get("queries", []):
                try:
                    self.queries.append(QueryLog(
                        query=q["query"],
                        timestamp=datetime.fromisoformat(q["timestamp"]),
                        result_count=q["result_count"],
                        top_score=q.get("top_score"),
                        duration_ms=q["duration_ms"],
                    ))
                except (KeyError, ValueError):
                    continue

            # Load failed queries
            for key, val in data.get("failed_queries", {}).items():
                try:
                    self.failed_queries[key] = {
                        "query": val["query"],
                        "count": val["count"],
                        "last_occurred": datetime.fromisoformat(val["last_occurred"]),
                    }
                except (KeyError, ValueError):
                    continue

            logger.info(f"Loaded {len(self.queries)} queries from {ANALYTICS_FILE}")
        except Exception as e:
            logger.warning(f"Failed to load analytics: {e}")

    def _save(self):
        """Save analytics to JSON file."""
        try:
            # Ensure directory exists
            ANALYTICS_FILE.parent.mkdir(parents=True, exist_ok=True)

            data = {
                "queries": [
                    {
                        "query": q.query,
                        "timestamp": q.timestamp.isoformat(),
                        "result_count": q.result_count,
                        "top_score": q.top_score,
                        "duration_ms": q.duration_ms,
                    }
                    for q in self.queries
                ],
                "failed_queries": {
                    key: {
                        "query": val["query"],
                        "count": val["count"],
                        "last_occurred": val["last_occurred"].isoformat(),
                    }
                    for key, val in self.failed_queries.items()
                },
                "saved_at": datetime.utcnow().isoformat(),
            }

            with open(ANALYTICS_FILE, "w") as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            logger.warning(f"Failed to save analytics: {e}")

    def log_query(self, query: str, result_count: int, top_score: float | None, duration_ms: int):
        """Log a query and periodically persist to disk."""
        entry = QueryLog(
            query=query,
            timestamp=datetime.utcnow(),
            result_count=result_count,
            top_score=top_score,
            duration_ms=duration_ms,
        )
        self.queries.append(entry)

        # Track failed queries (0 results)
        if result_count == 0:
            normalized = query.lower().strip()
            if normalized in self.failed_queries:
                self.failed_queries[normalized]["count"] += 1
                self.failed_queries[normalized]["last_occurred"] = entry.timestamp
            else:
                self.failed_queries[normalized] = {
                    "query": query,
                    "count": 1,
                    "last_occurred": entry.timestamp,
                }

        # Save after every query to ensure persistence
        self._save()

    def get_stats(self, period: str = "week") -> dict:
        """Get analytics stats for a period."""
        now = datetime.utcnow()

        if period == "today":
            cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "week":
            cutoff = now - timedelta(days=7)
        elif period == "month":
            cutoff = now - timedelta(days=30)
        else:
            cutoff = datetime.min

        # Filter queries by period
        period_queries = [q for q in self.queries if q.timestamp >= cutoff]

        if not period_queries:
            return {
                "total_queries": 0,
                "avg_response_ms": 0,
                "hit_rate": 0,
                "no_results_count": 0,
                "recent_queries": [],
                "failed_queries": [],
            }

        total = len(period_queries)
        hits = sum(1 for q in period_queries if q.result_count > 0)
        no_results = total - hits
        avg_ms = sum(q.duration_ms for q in period_queries) // total if total else 0

        # Sort failed queries by count
        sorted_failed = sorted(
            [
                {"query": v["query"], "count": v["count"], "last_occurred": v["last_occurred"].isoformat()}
                for v in self.failed_queries.values()
                if v["last_occurred"] >= cutoff
            ],
            key=lambda x: x["count"],
            reverse=True,
        )[:20]

        return {
            "total_queries": total,
            "avg_response_ms": avg_ms,
            "hit_rate": round(hits / total * 100, 1) if total else 0,
            "no_results_count": no_results,
            "recent_queries": [
                {
                    "query": q.query,
                    "timestamp": q.timestamp.isoformat(),
                    "result_count": q.result_count,
                    "top_score": q.top_score,
                    "duration_ms": q.duration_ms,
                }
                for q in reversed(list(period_queries)[-50:])
            ],
            "failed_queries": sorted_failed,
        }

    def flush(self):
        """Force save to disk."""
        self._save()


# Global analytics instance (loads from disk on startup)
_query_analytics = QueryAnalytics()

router = APIRouter(prefix="/confluence-rag", tags=["Confluence RAG"])


class SearchRequest(BaseModel):
    query: str
    top_k: int = 10
    include_citations: bool = True
    spaces: list[str] | None = None


class SyncRequest(BaseModel):
    spaces: list[str] | None = None
    full_sync: bool = False


class GuideRequest(BaseModel):
    query: str
    max_pages: int = 5


# Global singletons (cached)
_settings = None
_qdrant_store = None
_search_engine = None


def get_settings():
    global _settings
    if not _settings:
        _settings = ConfluenceRAGSettings()
    return _settings


def get_qdrant_store():
    global _qdrant_store
    if not _qdrant_store:
        _qdrant_store = QdrantStore()
    return _qdrant_store


def get_search_engine():
    global _search_engine
    if not _search_engine:
        store = get_qdrant_store()
        settings = get_settings()
        embeddings = get_embedding_pipeline(provider=settings.embedding_provider)
        citations = CitationExtractor()
        _search_engine = QdrantSearchEngine(store, embeddings, citations)
    return _search_engine


def get_sync_engine():
    """Create a new sync engine instance (not cached due to client lifecycle)."""
    settings = get_settings()
    store = get_qdrant_store()
    confluence = ConfluenceClient(
        settings.confluence_base_url,
        settings.confluence_username,
        settings.confluence_api_token,
    )
    chunker = ConfluenceChunker(max_chunk_tokens=settings.max_chunk_tokens)
    embeddings = get_embedding_pipeline(provider=settings.embedding_provider)

    return QdrantSyncEngine(confluence, store, chunker, embeddings, settings)

@router.post("/search", response_model=SearchResponse)
async def search_confluence(request: SearchRequest):
    """
    Search the Confluence RAG cache using Qdrant vector search.
    """
    start_time = time.time()
    engine = get_search_engine()

    config = SearchConfig(
        top_k=request.top_k,
        include_citations=request.include_citations,
        space_keys=request.spaces,
    )

    result = await engine.search(request.query, config)

    # Log analytics
    duration_ms = int((time.time() - start_time) * 1000)
    top_score = result.results[0].relevance_score if result.results else None
    _query_analytics.log_query(
        query=request.query,
        result_count=len(result.results),
        top_score=top_score,
        duration_ms=duration_ms,
    )

    return result


@router.post("/sync")
async def trigger_sync(request: SyncRequest):
    """Trigger a Confluence sync to Qdrant."""
    sync_engine = get_sync_engine()
    sync_type = "full" if request.full_sync else "incremental"

    async def run_sync():
        try:
            if request.full_sync:
                await sync_engine.full_sync(request.spaces)
            else:
                await sync_engine.incremental_sync(request.spaces)
        finally:
            await sync_engine.confluence.close()
            # Save sync metadata when sync completes (success or failure)
            _save_sync_metadata(sync_type)
            logger.info(f"Sync metadata saved: {sync_type} sync completed")

    asyncio.create_task(run_sync())

    return {"status": "sync_started", "spaces": request.spaces or "all"}


@router.get("/stats")
async def get_stats():
    """Get statistics about the Qdrant RAG cache."""
    engine = get_search_engine()
    store = get_qdrant_store()
    settings = get_settings()

    base_stats = engine.get_stats()
    spaces = store.list_spaces()

    # Calculate totals
    total_chunks = sum(s.get("chunk_count", 0) for s in spaces)
    total_pages = sum(s.get("page_count", 0) for s in spaces)

    # Get last sync run time from metadata file (when sync actually ran)
    sync_metadata = _load_sync_metadata()
    last_sync_run = sync_metadata.get("last_sync_run")
    last_sync_type = sync_metadata.get("last_sync_type")

    return {
        **base_stats,
        "total_chunks": total_chunks,
        "total_pages": total_pages,
        "space_count": len(spaces),
        "embedding_provider": settings.embedding_provider,
        "embedding_model": settings.gemini_model if settings.embedding_provider == "gemini" else settings.embedding_model,
        "qdrant_collection": settings.qdrant_collection,
        "last_sync": last_sync_run,
        "last_sync_type": last_sync_type,
    }


@router.get("/analytics")
async def get_analytics(period: str = Query(default="week", regex="^(today|week|month|all)$")):
    """Get query analytics for the RAG system."""
    return _query_analytics.get_stats(period)


@router.get("/page/{page_id}")
async def get_page_chunks(page_id: str):
    """Get all chunks for a specific page from Qdrant."""
    engine = get_search_engine()
    page, chunks = engine.get_page(page_id)

    if not page:
        raise HTTPException(404, "Page not found")

    return {
        "page": page.model_dump(),
        "chunks": [c.model_dump() for c in chunks],
    }


@router.get("/spaces")
async def list_spaces():
    """List all spaces in the Qdrant cache with statistics."""
    store = get_qdrant_store()
    spaces = store.list_spaces()
    return {"spaces": spaces, "total": len(spaces)}


@router.delete("/spaces/{space_key}")
async def delete_space(space_key: str):
    """Delete all indexed content from a specific Confluence space."""
    store = get_qdrant_store()

    # Get count before deletion
    spaces_before = store.list_spaces()
    space_info = next((s for s in spaces_before if s["space_key"] == space_key.upper()), None)

    if not space_info:
        raise HTTPException(404, f"Space '{space_key}' not found in index")

    chunks_deleted = space_info.get("chunk_count", 0)

    # Delete by filtering
    try:
        store.delete_by_space(space_key.upper())
        logger.info(f"Deleted {chunks_deleted} chunks from space {space_key}")
        return {
            "status": "deleted",
            "space_key": space_key.upper(),
            "chunks_deleted": chunks_deleted,
        }
    except Exception as e:
        logger.error(f"Failed to delete space {space_key}: {e}")
        raise HTTPException(500, f"Failed to delete space: {str(e)}")


@router.post("/warmup")
async def warmup_rag():
    """
    Preload the embedding model and Qdrant connection.

    Call this after server startup to ensure fast first queries.
    Returns stats about the loaded components.
    """
    logger.info("Warming up Confluence RAG...")

    # Force initialization of all components
    engine = get_search_engine()
    stats = engine.get_stats()

    logger.info(f"RAG warmup complete: {stats.get('points_count', 0)} vectors ready")

    settings = get_settings()
    return {
        "status": "ready",
        "qdrant": stats,
        "embedding_provider": settings.embedding_provider,
    }


@router.post("/guide")
async def generate_guide_from_docs(request: GuideRequest):
    """
    Generate a comprehensive guide by searching documentation and returning FULL page content.

    Unlike /search which returns snippets, this endpoint:
    1. Searches for relevant pages
    2. Returns complete page content from the most relevant pages
    3. Suitable for generating comprehensive how-to guides

    Args:
        query: What to search for (e.g., 'configure MS Defender', 'CEPH tenant setup')
        max_pages: Maximum number of relevant pages to include (default 5)

    Returns:
        Full page content from the most relevant documentation pages.
    """
    engine = get_search_engine()
    store = get_qdrant_store()

    # First search for relevant pages
    config = SearchConfig(
        top_k=request.max_pages * 3,  # Get more candidates to find unique pages
        include_citations=True,
        space_keys=None,
    )

    search_result = await engine.search(request.query, config)

    # Collect unique page IDs from search results
    seen_page_ids: set[str] = set()
    page_ids: list[str] = []

    for result in search_result.results:
        page_id = result.metadata.get("page_id")
        if page_id and page_id not in seen_page_ids:
            seen_page_ids.add(page_id)
            page_ids.append(page_id)
            if len(page_ids) >= request.max_pages:
                break

    if not page_ids:
        return {
            "query": request.query,
            "pages_found": 0,
            "pages": [],
            "message": "No relevant documentation found for this query.",
        }

    # Fetch full content for each page
    pages = []
    for page_id in page_ids:
        try:
            page, chunks = engine.get_page(page_id)
            if page:
                # Reconstruct full content from chunks
                full_content = "\n\n".join(c.text for c in chunks)
                pages.append({
                    "page_id": page_id,
                    "title": page.title,
                    "space_key": page.space_key,
                    "url": page.url,
                    "content": full_content,
                    "last_modified": page.last_modified.isoformat() if page.last_modified else None,
                })
        except Exception as e:
            logger.warning(f"Failed to fetch page {page_id}: {e}")

    return {
        "query": request.query,
        "pages_found": len(pages),
        "pages": pages,
    }


def warmup_search_engine():
    """
    Synchronous warmup function to preload the embedding model.

    Call this during application startup to avoid cold-start latency.
    """
    if os.getenv("ATLAS_RAG_SKIP_WARMUP", "").lower() in ("1", "true", "yes"):
        logger.info("Skipping RAG warmup (ATLAS_RAG_SKIP_WARMUP=1)")
        return

    try:
        logger.info("Preloading Confluence RAG embedding model...")
        engine = get_search_engine()
        stats = engine.get_stats()
        logger.info(f"RAG ready: {stats.get('points_count', 0)} vectors in Qdrant")
    except Exception as e:
        logger.warning(f"RAG warmup failed (non-fatal): {e}")
