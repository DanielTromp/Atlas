from fastapi import APIRouter, Query, HTTPException, Depends
from pydantic import BaseModel
import asyncio
from typing import Annotated

from infrastructure_atlas.confluence_rag.config import ConfluenceRAGSettings
from infrastructure_atlas.confluence_rag.database import Database
from infrastructure_atlas.confluence_rag.search import HybridSearchEngine, SearchConfig
from infrastructure_atlas.confluence_rag.sync import ConfluenceSyncEngine
from infrastructure_atlas.confluence_rag.models import SearchResponse
from infrastructure_atlas.confluence_rag.embeddings import EmbeddingPipeline
from infrastructure_atlas.confluence_rag.citations import CitationExtractor
from infrastructure_atlas.confluence_rag.confluence_client import ConfluenceClient
from infrastructure_atlas.confluence_rag.chunker import ConfluenceChunker

# Note: In a real app we'd use a DI container or app state.
# Here we'll instantiate lazily given the "module" structure.

router = APIRouter(prefix="/confluence-rag", tags=["Confluence RAG"])

class SearchRequest(BaseModel):
    query: str
    top_k: int = 10
    include_citations: bool = True
    spaces: list[str] | None = None

class SyncRequest(BaseModel):
    spaces: list[str] | None = None
    full_sync: bool = False

# Global singletons (cached)
_settings = None
_db = None
_search_engine = None

def get_settings():
    global _settings
    if not _settings:
        _settings = ConfluenceRAGSettings()
    return _settings

def get_database():
    global _db
    if not _db:
        settings = get_settings()
        _db = Database(settings.duckdb_path)
    return _db

def get_search_engine():
    global _search_engine
    if not _search_engine:
        db = get_database()
        settings = get_settings()
        embeddings = EmbeddingPipeline(model_name=settings.embedding_model, dimensions=settings.embedding_dimensions)
        citations = CitationExtractor()
        _search_engine = HybridSearchEngine(db, embeddings, citations)
    return _search_engine

def get_sync_engine():
    # Sync engine is heavy, maybe don't cache it forever or careful with client session
    # We will create one fresh or use a cached one.
    # The client needs closing though.
    settings = get_settings()
    db = get_database()
    confluence = ConfluenceClient(
        settings.confluence_base_url,
        settings.confluence_username,
        settings.confluence_api_token
    )
    chunker = ConfluenceChunker(max_chunk_tokens=settings.max_chunk_tokens)
    embeddings = EmbeddingPipeline(model_name=settings.embedding_model, dimensions=settings.embedding_dimensions)
    
    return ConfluenceSyncEngine(confluence, db, chunker, embeddings, settings)

@router.post("/search", response_model=SearchResponse)
async def search_confluence(request: SearchRequest):
    """
    Search the Confluence RAG cache.
    """
    engine = get_search_engine()
    
    config = SearchConfig(
        top_k=request.top_k,
        include_citations=request.include_citations
    )
    
    # Filter by spaces logic would go into search engine config or query
    # Currently SearchConfig doesn't support space filter but sql query can be updated.
    # For now we ignore spaces filter or would need to extend SearchEngine.
    
    return await engine.search(request.query, config)

@router.post("/sync")
async def trigger_sync(request: SyncRequest):
    """Trigger a Confluence sync"""
    # Background task
    sync_engine = get_sync_engine()
    
    async def run_sync():
        if request.full_sync:
            await sync_engine.full_sync(request.spaces)
        else:
            await sync_engine.incremental_sync(request.spaces)
        await sync_engine.confluence.close()

    asyncio.create_task(run_sync())
    
    return {"status": "sync_started", "spaces": request.spaces or "all"}

@router.get("/stats")
async def get_stats():
    """Get statistics about the RAG cache"""
    db = get_database()
    conn = db.connect()
    
    try:
        stats = conn.execute("""
            SELECT
                (SELECT COUNT(*) FROM pages) as total_pages,
                (SELECT COUNT(*) FROM chunks) as total_chunks,
                (SELECT COUNT(*) FROM chunk_embeddings) as total_embeddings,
                (SELECT MAX(synced_at) FROM pages) as last_sync,
                (SELECT SUM(hit_count) FROM search_cache) as total_cache_hits
        """).fetchone()
        
        return {
            "pages": stats[0],
            "chunks": stats[1],
            "embeddings": stats[2],
            "last_sync": stats[3],
            "cache_hits": stats[4] or 0
        }
    except:
        return {"status": "Database empty or not initialized"}

@router.get("/page/{page_id}")
async def get_page_chunks(page_id: str):
    """Get all chunks for a specific page"""
    db = get_database()
    conn = db.connect()
    
    try:
        page = conn.execute(
            "SELECT * FROM pages WHERE page_id = $1", [page_id]
        ).fetchone()
        
        if not page:
            raise HTTPException(404, "Page not found")
        
        page_cols = [desc[0] for desc in conn.description]
        
        chunks = conn.execute(
            "SELECT * FROM chunks WHERE page_id = $1 ORDER BY position_in_page",
            [page_id]
        ).fetchall()
        
        chunk_cols = [desc[0] for desc in conn.description]
        
        return {
            "page": dict(zip(page_cols, page)),
            "chunks": [dict(zip(chunk_cols, c)) for c in chunks]
        }
    except Exception as e:
        raise HTTPException(500, str(e))

@router.get("/spaces")
async def list_spaces():
    """List all spaces in the cache with statistics"""
    db = get_database()
    conn = db.connect()
    
    try:
        spaces = conn.execute("""
            SELECT 
                p.space_key,
                COUNT(DISTINCT p.page_id) as page_count,
                COUNT(c.chunk_id) as chunk_count,
                MAX(p.synced_at) as last_sync,
                s.status as sync_status
            FROM pages p
            LEFT JOIN chunks c ON p.page_id = c.page_id
            LEFT JOIN sync_state s ON p.space_key = s.space_key
            GROUP BY p.space_key, s.status
            ORDER BY p.space_key
        """).fetchall()
        
        return [
            {
                "space_key": row[0],
                "page_count": row[1],
                "chunk_count": row[2],
                "last_sync": row[3],
                "sync_status": row[4]
            }
            for row in spaces
        ]
    except:
        return []
