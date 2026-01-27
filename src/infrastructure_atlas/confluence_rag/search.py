from dataclasses import dataclass
import hashlib
import json
import time

from infrastructure_atlas.confluence_rag.database import Database
from infrastructure_atlas.confluence_rag.embeddings import EmbeddingPipeline
from infrastructure_atlas.confluence_rag.citations import CitationExtractor
from infrastructure_atlas.confluence_rag.models import (
    SearchResponse, SearchResult, ConfluencePage, 
    Chunk, ChunkType
)

@dataclass
class SearchConfig:
    top_k: int = 10
    semantic_weight: float = 0.6
    keyword_weight: float = 0.4
    min_relevance_score: float = 0.001
    include_citations: bool = True
    max_citations_per_result: int = 3
    use_cache: bool = True
    cache_ttl_seconds: int = 3600

class HybridSearchEngine:
    """
    Hybrid search: combines vector similarity with keyword matching.
    Uses Reciprocal Rank Fusion for score combination.
    """
    
    def __init__(
        self,
        db: Database,
        embedding_pipeline: EmbeddingPipeline,
        citation_extractor: CitationExtractor
    ):
        self.db = db
        self.embeddings = embedding_pipeline
        self.citations = citation_extractor
    
    async def search(
        self,
        query: str,
        config: SearchConfig | None = None
    ) -> SearchResponse:
        """
        Execute hybrid search with citations.
        """
        start_time = time.time()
        config = config or SearchConfig()
        
        # Check cache
        if config.use_cache:
            cached = self._get_cached_results(query)
            if cached:
                return cached
        
        # Embed query
        query_embedding = self.embeddings.embed_query(query)
        
        # Hybrid search query
        results = await self._execute_hybrid_search(
            query=query,
            query_embedding=query_embedding,
            config=config
        )
        
        # Enrich with page data and citations
        enriched_results = []
        for row in results:
            page = self._get_page(row["page_id"])
            chunk = self._row_to_chunk(row)
            
            citations = []
            if config.include_citations:
                citations = self.citations.extract_citations(
                    chunk=chunk,
                    page=page,
                    query=query,
                    relevance_score=row["relevance_score"]
                )[:config.max_citations_per_result]
            
            enriched_results.append(SearchResult(
                chunk_id=chunk.chunk_id,
                content=chunk.content,
                relevance_score=row["relevance_score"],
                citations=citations,
                page=page,
                context_path=chunk.context_path
            ))
        
        response = SearchResponse(
            query=query,
            results=enriched_results,
            total_results=len(enriched_results),
            search_time_ms=(time.time() - start_time) * 1000
        )
        
        # Cache results
        if config.use_cache:
            self._cache_results(query, response, config.cache_ttl_seconds)
        
        return response
    
    async def _execute_hybrid_search(
        self,
        query: str,
        query_embedding: list[float],
        config: SearchConfig
    ) -> list[dict]:
        """Execute the hybrid search query on DuckDB"""
        
        conn = self.db.connect()
        
        # RRF constant (default 60)
        k = 60
        
        # Note: Using parameterized query for safety
        # DuckDB Python API handles array params
        
        # Need to ensure vector search works
        # array_cosine_distance might need list input
        
        sql = """
            WITH semantic_results AS (
                -- Vector similarity search
                SELECT
                    c.chunk_id,
                    c.page_id,
                    c.content,
                    c.context_path,
                    c.chunk_type,
                    c.heading_context,
                    c.metadata,
                    1 - array_cosine_distance(ce.embedding, $1::FLOAT[768]) as similarity,
                    ROW_NUMBER() OVER (ORDER BY array_cosine_distance(ce.embedding, $1::FLOAT[768])) as sem_rank
                FROM chunk_embeddings ce
                JOIN chunks c ON c.chunk_id = ce.chunk_id
                ORDER BY similarity DESC
                LIMIT $2
            ),
            keyword_results AS (
                -- Full-text search with DuckDB FTS
                SELECT
                    c.chunk_id,
                    c.page_id,
                    c.content,
                    c.context_path,
                    c.chunk_type,
                    c.heading_context,
                    c.metadata,
                    fts_main_chunks.match_bm25(chunk_id, $3) as bm25_score,
                    ROW_NUMBER() OVER (ORDER BY fts_main_chunks.match_bm25(chunk_id, $3) DESC) as kw_rank
                FROM chunks c
                WHERE fts_main_chunks.match_bm25(chunk_id, $3) IS NOT NULL
                ORDER BY bm25_score DESC
                LIMIT $2
            ),
            combined AS (
                SELECT
                    COALESCE(s.chunk_id, k.chunk_id) as chunk_id,
                    COALESCE(s.page_id, k.page_id) as page_id,
                    COALESCE(s.content, k.content) as content,
                    COALESCE(s.context_path, k.context_path) as context_path,
                    COALESCE(s.chunk_type, k.chunk_type) as chunk_type,
                    COALESCE(s.heading_context, k.heading_context) as heading_context,
                    COALESCE(s.metadata, k.metadata) as metadata,
                    s.similarity,
                    k.bm25_score,
                    -- Reciprocal Rank Fusion
                    (
                        $4 * (1.0 / ($5 + COALESCE(s.sem_rank, 1000))) +
                        $6 * (1.0 / ($5 + COALESCE(k.kw_rank, 1000)))
                    ) as relevance_score
                FROM semantic_results s
                FULL OUTER JOIN keyword_results k ON s.chunk_id = k.chunk_id
            )
            SELECT *
            FROM combined
            WHERE relevance_score >= $7
            ORDER BY relevance_score DESC
            LIMIT $8
        """
        
        params = [
            query_embedding,           # $1: embedding vector
            config.top_k * 3,          # $2: initial limit per method
            query,                     # $3: keyword query
            config.semantic_weight,    # $4: semantic weight
            k,                         # $5: RRF constant
            config.keyword_weight,     # $6: keyword weight
            config.min_relevance_score,# $7: min score threshold
            config.top_k               # $8: final limit
        ]
        
        import asyncio
        # Run in thread if needed (DuckDB is embedded but queries can take time)
        # Assuming duckdb cursor is not 100% thread safe if shared, but we get new connection/cursor usually
        # But here we are using self.db.connect() which is singleton-ish? No, self.conn is cached.
        # DuckDB connections are not thread safe if modifying. Read might be fine.
        # To be safe run in executor
        
        loop = asyncio.get_running_loop()
        
        def run_query():
            return conn.execute(sql, params).fetchall()

        try:
             result_rows = await loop.run_in_executor(None, run_query)
        except Exception:
             # FTS/VSS might fail if not initialized or table empty?
             # Or binding issues
             # We should return empty if no match
             return []
        
        if not result_rows:
             return []

        # DuckDB fetchall returns tuples. We need to map to dict using description.
        # But we need result.description which is only available on cursor/result object 
        # So we cannot use fetchall in executor directly if we want description from that same cursor execution.
        
        # Let's do it synchronously for now as DuckDB is fast and usually embedded means local.
        # Or refactor to return cursor. 
        # But plan says async search.
        
        # Retry sync for now to get column names:
        result = conn.execute(sql, params)
        columns = [desc[0] for desc in result.description]
        return [dict(zip(columns, row)) for row in result.fetchall()]
    
    def _get_page(self, page_id: str) -> ConfluencePage:
        """Fetch page metadata from database"""
        conn = self.db.connect()
        row = conn.execute(
            "SELECT * FROM pages WHERE page_id = $1", [page_id]
        ).fetchone()
        
        if not row:
            # Should not happen ideally due to FK
            raise ValueError(f"Page not found: {page_id}")
            
        columns = [desc[0] for desc in conn.description]
        data = dict(zip(columns, row))
        
        return ConfluencePage(
            page_id=data["page_id"],
            space_key=data["space_key"],
            title=data["title"],
            url=data["url"],
            labels=data["labels"] or [],
            version=data["version"],
            updated_at=data["updated_at"],
            updated_by=data["updated_by"],
            parent_id=data["parent_id"],
            ancestors=data["ancestors"] or []
        )
    
    def _row_to_chunk(self, row: dict) -> Chunk:
        """Convert database row to Chunk model"""
        return Chunk(
            chunk_id=row["chunk_id"],
            page_id=row["page_id"],
            content=row["content"],
            original_content=row["content"],  # Same as content now
            context_path=row["context_path"] or [],
            chunk_type=ChunkType(row["chunk_type"]) if row["chunk_type"] else ChunkType.PROSE,
            token_count=0,  # Not needed for search results
            position_in_page=0,
            heading_context=row["heading_context"],
            text_spans=[],  # Removed from schema
            metadata=json.loads(row["metadata"]) if row["metadata"] else {}
        )
    
    def _get_cached_results(self, query: str) -> SearchResponse | None:
        """Retrieve cached results"""
        query_hash = hashlib.md5(query.encode()).hexdigest()
        conn = self.db.connect()
        
        # DuckDB uses interval syntax
        try:
            result = conn.execute("""
                UPDATE search_cache
                SET hit_count = hit_count + 1
                WHERE query_hash = $1
                  AND created_at > NOW() - INTERVAL 1 HOUR
                RETURNING results
            """, [query_hash]).fetchone()
            
            if result:
                return SearchResponse(**json.loads(result[0]))
        except Exception:
            # Cache might not exist or schema issue
            pass
        return None
    
    def _cache_results(self, query: str, response: SearchResponse, ttl: int):
        """Cache search results"""
        query_hash = hashlib.md5(query.encode()).hexdigest()
        conn = self.db.connect()
        
        try:
            conn.execute("""
                INSERT INTO search_cache (query_hash, query_text, results)
                VALUES ($1, $2, $3)
                ON CONFLICT (query_hash) DO UPDATE SET
                    results = EXCLUDED.results,
                    created_at = CURRENT_TIMESTAMP,
                    hit_count = 1
            """, [query_hash, query, response.model_dump_json()])
        except Exception:
            pass
