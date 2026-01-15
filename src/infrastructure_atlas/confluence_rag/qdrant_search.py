"""
Qdrant-based search engine for Confluence RAG.

Provides semantic search using Qdrant vector database with optional filtering.
"""

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from infrastructure_atlas.confluence_rag.citations import CitationExtractor
from infrastructure_atlas.confluence_rag.config import ConfluenceRAGSettings
from infrastructure_atlas.confluence_rag.embeddings import EmbeddingPipeline
from infrastructure_atlas.confluence_rag.models import (
    Chunk,
    ChunkType,
    Citation,
    ConfluencePage,
    SearchResponse,
    SearchResult,
    TextSpan,
)
from infrastructure_atlas.confluence_rag.qdrant_store import QdrantStore

logger = logging.getLogger(__name__)


@dataclass
class SearchConfig:
    """Search configuration options."""

    top_k: int = 10
    min_score: float = 0.3  # Qdrant cosine similarity threshold (0-1)
    include_citations: bool = True
    max_citations_per_result: int = 3
    use_cache: bool = True
    cache_ttl_seconds: int = 3600
    # Filtering options
    space_keys: list[str] | None = None
    labels: list[str] | None = None
    chunk_types: list[ChunkType] | None = None


# Simple in-memory cache (can be replaced with Redis/DuckDB cache later)
_search_cache: dict[str, tuple[SearchResponse, float]] = {}


class QdrantSearchEngine:
    """
    Semantic search engine using Qdrant vector database.

    Features:
    - Pure semantic search with cosine similarity
    - Filtering by space, labels, and chunk type
    - Citation extraction from search results
    - Query caching with TTL
    """

    def __init__(
        self,
        qdrant_store: QdrantStore,
        embedding_pipeline: EmbeddingPipeline,
        citation_extractor: CitationExtractor,
    ):
        self.store = qdrant_store
        self.embeddings = embedding_pipeline
        self.citations = citation_extractor

    async def search(
        self,
        query: str,
        config: SearchConfig | None = None,
    ) -> SearchResponse:
        """
        Execute semantic search with optional citations.

        Args:
            query: Search query text
            config: Search configuration options

        Returns:
            SearchResponse with results and metadata
        """
        start_time = time.time()
        config = config or SearchConfig()

        # Check cache
        if config.use_cache:
            cached = self._get_cached_results(query, config)
            if cached:
                return cached

        # Embed query
        query_embedding = self.embeddings.embed_query(query)

        # Execute Qdrant search
        raw_results = self.store.search(
            query_vector=query_embedding,
            limit=config.top_k,
            space_keys=config.space_keys,
            labels=config.labels,
            chunk_types=config.chunk_types,
            score_threshold=config.min_score,
        )

        # Enrich with page data and citations
        enriched_results = []
        for hit in raw_results:
            payload = hit["payload"]
            score = hit["score"]

            page = self._payload_to_page(payload)
            chunk = self._payload_to_chunk(payload)

            citations = []
            if config.include_citations:
                citations = self.citations.extract_citations(
                    chunk=chunk,
                    page=page,
                    query=query,
                    relevance_score=score,
                )[: config.max_citations_per_result]

            enriched_results.append(
                SearchResult(
                    chunk_id=chunk.chunk_id,
                    content=chunk.content,
                    relevance_score=score,
                    citations=citations,
                    page=page,
                    context_path=chunk.context_path,
                )
            )

        response = SearchResponse(
            query=query,
            results=enriched_results,
            total_results=len(enriched_results),
            search_time_ms=(time.time() - start_time) * 1000,
        )

        # Cache results
        if config.use_cache:
            self._cache_results(query, config, response)

        return response

    def _payload_to_page(self, payload: dict[str, Any]) -> ConfluencePage:
        """Convert Qdrant payload to ConfluencePage model."""
        updated_at = payload.get("updated_at")
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at)
        elif updated_at is None:
            updated_at = datetime.now()

        return ConfluencePage(
            page_id=payload["page_id"],
            space_key=payload["space_key"],
            title=payload.get("page_title", ""),
            url=payload.get("page_url", ""),
            labels=payload.get("labels", []),
            version=payload.get("version", 1),
            updated_at=updated_at,
            updated_by=payload.get("updated_by", ""),
            parent_id=payload.get("parent_id"),
            ancestors=payload.get("ancestors", []),
        )

    def _payload_to_chunk(self, payload: dict[str, Any]) -> Chunk:
        """Convert Qdrant payload to Chunk model."""
        chunk_type_str = payload.get("chunk_type", "prose")
        try:
            chunk_type = ChunkType(chunk_type_str)
        except ValueError:
            chunk_type = ChunkType.PROSE

        return Chunk(
            chunk_id=payload["chunk_id"],
            page_id=payload["page_id"],
            content=payload.get("content", ""),
            original_content=payload.get("original_content", payload.get("content", "")),
            context_path=payload.get("context_path", []),
            chunk_type=chunk_type,
            token_count=payload.get("token_count", 0),
            position_in_page=payload.get("position_in_page", 0),
            heading_context=payload.get("heading_context"),
            text_spans=[],  # Not stored in Qdrant
            metadata=payload.get("metadata", {}),
        )

    def _cache_key(self, query: str, config: SearchConfig) -> str:
        """Generate cache key from query and config."""
        key_parts = [
            query,
            str(config.top_k),
            str(config.min_score),
            str(sorted(config.space_keys or [])),
            str(sorted(config.labels or [])),
        ]
        return hashlib.md5("|".join(key_parts).encode()).hexdigest()

    def _get_cached_results(
        self, query: str, config: SearchConfig
    ) -> SearchResponse | None:
        """Retrieve cached results if valid."""
        cache_key = self._cache_key(query, config)
        if cache_key in _search_cache:
            response, cached_at = _search_cache[cache_key]
            if time.time() - cached_at < config.cache_ttl_seconds:
                return response
            else:
                # Expired, remove from cache
                del _search_cache[cache_key]
        return None

    def _cache_results(
        self, query: str, config: SearchConfig, response: SearchResponse
    ) -> None:
        """Cache search results."""
        cache_key = self._cache_key(query, config)
        _search_cache[cache_key] = (response, time.time())

        # Simple cache size limit (LRU would be better)
        if len(_search_cache) > 1000:
            # Remove oldest entries
            sorted_keys = sorted(
                _search_cache.keys(), key=lambda k: _search_cache[k][1]
            )
            for key in sorted_keys[:100]:
                del _search_cache[key]

    def get_page(self, page_id: str) -> tuple[ConfluencePage | None, list[Chunk]]:
        """
        Retrieve a page and all its chunks.

        Args:
            page_id: Confluence page ID

        Returns:
            Tuple of (page, chunks) or (None, []) if not found
        """
        chunk_data = self.store.get_page_chunks(page_id)
        if not chunk_data:
            return None, []

        # Extract page from first chunk's payload
        first_payload = chunk_data[0]["payload"]
        page = self._payload_to_page(first_payload)

        chunks = [self._payload_to_chunk(cd["payload"]) for cd in chunk_data]
        chunks.sort(key=lambda c: c.position_in_page)

        return page, chunks

    def get_stats(self) -> dict[str, Any]:
        """Get search engine statistics."""
        store_stats = self.store.get_stats()
        return {
            **store_stats,
            "cache_size": len(_search_cache),
        }
