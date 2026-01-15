import asyncio
import logging
import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from infrastructure_atlas.confluence_rag.chunker import ConfluenceChunker
from infrastructure_atlas.confluence_rag.citations import CitationExtractor
from infrastructure_atlas.confluence_rag.config import ConfluenceRAGSettings
from infrastructure_atlas.confluence_rag.confluence_client import ConfluenceClient
from infrastructure_atlas.confluence_rag.embeddings import EmbeddingPipeline
from infrastructure_atlas.confluence_rag.models import SearchResponse

# Qdrant-based implementations
from infrastructure_atlas.confluence_rag.qdrant_search import QdrantSearchEngine, SearchConfig
from infrastructure_atlas.confluence_rag.qdrant_store import QdrantStore
from infrastructure_atlas.confluence_rag.qdrant_sync import QdrantSyncEngine

logger = logging.getLogger(__name__)

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
        embeddings = EmbeddingPipeline(
            model_name=settings.embedding_model, dimensions=settings.embedding_dimensions
        )
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
    embeddings = EmbeddingPipeline(
        model_name=settings.embedding_model, dimensions=settings.embedding_dimensions
    )

    return QdrantSyncEngine(confluence, store, chunker, embeddings, settings)

@router.post("/search", response_model=SearchResponse)
async def search_confluence(request: SearchRequest):
    """
    Search the Confluence RAG cache using Qdrant vector search.
    """
    engine = get_search_engine()

    config = SearchConfig(
        top_k=request.top_k,
        include_citations=request.include_citations,
        space_keys=request.spaces,
    )

    return await engine.search(request.query, config)


@router.post("/sync")
async def trigger_sync(request: SyncRequest):
    """Trigger a Confluence sync to Qdrant."""
    sync_engine = get_sync_engine()

    async def run_sync():
        try:
            if request.full_sync:
                await sync_engine.full_sync(request.spaces)
            else:
                await sync_engine.incremental_sync(request.spaces)
        finally:
            await sync_engine.confluence.close()

    asyncio.create_task(run_sync())

    return {"status": "sync_started", "spaces": request.spaces or "all"}


@router.get("/stats")
async def get_stats():
    """Get statistics about the Qdrant RAG cache."""
    engine = get_search_engine()
    return engine.get_stats()


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
    return store.list_spaces()


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

    return {
        "status": "ready",
        "qdrant": stats,
        "model": get_settings().embedding_model,
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
