"""Confluence skill implementation for agent workflows.

Provides documentation and knowledge base actions:
- Semantic search across Confluence
- Page retrieval with content
- Find related documentation
"""

from __future__ import annotations

import asyncio
from typing import Any

from infrastructure_atlas.infrastructure.logging import get_logger
from infrastructure_atlas.skills.base import BaseSkill

logger = get_logger(__name__)


class ConfluenceSkill(BaseSkill):
    """Skill for interacting with Confluence documentation.

    Provides actions for:
    - Searching for documentation semantically
    - Retrieving page content
    - Finding relevant runbooks and procedures
    """

    name = "confluence"
    description = "Search and retrieve Confluence documentation, runbooks, and procedures"
    category = "documentation"

    def __init__(self) -> None:
        super().__init__()
        self._search_engine = None

    def _get_search_engine(self):
        """Get or create search engine lazily."""
        if self._search_engine is None:
            try:
                from infrastructure_atlas.confluence_rag.api import get_search_engine

                self._search_engine = get_search_engine()
            except Exception as e:
                logger.warning(f"Could not initialize Confluence search engine: {e}")
                raise
        return self._search_engine

    def initialize(self) -> None:
        """Register all Confluence actions."""
        self.register_action(
            name="search",
            func=self._search,
            description="Search Confluence documentation using semantic search",
            is_destructive=False,
        )

        self.register_action(
            name="get_page",
            func=self._get_page,
            description="Get a Confluence page by ID with its content",
            is_destructive=False,
        )

        self.register_action(
            name="find_runbook",
            func=self._find_runbook,
            description="Find runbooks or procedures related to a topic",
            is_destructive=False,
        )

        self.register_action(
            name="search_by_space",
            func=self._search_by_space,
            description="Search within a specific Confluence space",
            is_destructive=False,
        )

        self.register_action(
            name="get_related_pages",
            func=self._get_related_pages,
            description="Find pages related to a given page",
            is_destructive=False,
        )

        logger.info("ConfluenceSkill initialized with 5 actions")

    def _search(
        self,
        query: str,
        top_k: int = 10,
        min_score: float = 0.3,
        include_citations: bool = True,
    ) -> dict[str, Any]:
        """Search Confluence documentation semantically.

        Args:
            query: Search query text
            top_k: Maximum number of results (default 10)
            min_score: Minimum relevance score threshold (0.0-1.0)
            include_citations: Include citation snippets in results

        Returns:
            Search results with relevance scores and optional citations
        """
        try:
            search_engine = self._get_search_engine()

            from infrastructure_atlas.confluence_rag.qdrant_search import SearchConfig

            config = SearchConfig(
                top_k=top_k,
                min_score=min_score,
                include_citations=include_citations,
            )

            # Run async search in sync context
            response = asyncio.run(search_engine.search(query, config))

            return {
                "success": True,
                "query": response.query,
                "total_results": response.total_results,
                "search_time_ms": response.search_time_ms,
                "results": [
                    {
                        "chunk_id": r.chunk_id,
                        "content": r.content[:500] + "..." if len(r.content) > 500 else r.content,
                        "relevance_score": r.relevance_score,
                        "page": {
                            "page_id": r.page.page_id,
                            "title": r.page.title,
                            "space_key": r.page.space_key,
                            "url": r.page.url,
                            "labels": r.page.labels,
                        },
                        "context_path": r.context_path,
                        "citations": [
                            {
                                "text": c.text,
                                "source_type": c.source_type,
                                "confidence": c.confidence,
                            }
                            for c in r.citations
                        ],
                    }
                    for r in response.results
                ],
            }
        except Exception as e:
            logger.error(f"Failed to search Confluence: {e}")
            return {"success": False, "error": str(e)}

    def _get_page(self, page_id: str) -> dict[str, Any]:
        """Get a Confluence page by ID.

        Args:
            page_id: The Confluence page ID

        Returns:
            Page details with content chunks
        """
        try:
            search_engine = self._get_search_engine()

            page, chunks = search_engine.get_page(page_id)

            if page is None:
                return {"success": False, "error": f"Page {page_id} not found"}

            return {
                "success": True,
                "page": {
                    "page_id": page.page_id,
                    "title": page.title,
                    "space_key": page.space_key,
                    "url": page.url,
                    "labels": page.labels,
                    "version": page.version,
                    "updated_at": page.updated_at.isoformat() if page.updated_at else None,
                    "updated_by": page.updated_by,
                    "parent_id": page.parent_id,
                    "ancestors": page.ancestors,
                },
                "content": [
                    {
                        "chunk_id": c.chunk_id,
                        "content": c.content,
                        "chunk_type": c.chunk_type.value,
                        "context_path": c.context_path,
                        "heading_context": c.heading_context,
                        "position": c.position_in_page,
                    }
                    for c in chunks
                ],
            }
        except Exception as e:
            logger.error(f"Failed to get Confluence page {page_id}: {e}")
            return {"success": False, "error": str(e)}

    def _find_runbook(
        self,
        topic: str,
        top_k: int = 5,
    ) -> dict[str, Any]:
        """Find runbooks or procedures related to a topic.

        Searches for documentation labeled as runbooks, procedures, or how-to guides.

        Args:
            topic: The topic to find runbooks for
            top_k: Maximum number of results (default 5)

        Returns:
            List of relevant runbooks
        """
        try:
            search_engine = self._get_search_engine()

            from infrastructure_atlas.confluence_rag.qdrant_search import SearchConfig

            # Search with labels that typically indicate runbooks
            config = SearchConfig(
                top_k=top_k,
                min_score=0.4,
                include_citations=True,
                labels=["runbook", "procedure", "how-to", "troubleshooting", "guide"],
            )

            # Try with labels first
            response = asyncio.run(search_engine.search(f"runbook {topic}", config))

            # If no results, try without label filter
            if response.total_results == 0:
                config.labels = None
                response = asyncio.run(
                    search_engine.search(f"runbook procedure how to {topic}", config)
                )

            return {
                "success": True,
                "topic": topic,
                "total_results": response.total_results,
                "runbooks": [
                    {
                        "title": r.page.title,
                        "page_id": r.page.page_id,
                        "url": r.page.url,
                        "space_key": r.page.space_key,
                        "labels": r.page.labels,
                        "relevance_score": r.relevance_score,
                        "summary": r.content[:300] + "..." if len(r.content) > 300 else r.content,
                    }
                    for r in response.results
                ],
            }
        except Exception as e:
            logger.error(f"Failed to find runbooks for topic '{topic}': {e}")
            return {"success": False, "error": str(e)}

    def _search_by_space(
        self,
        query: str,
        space_key: str,
        top_k: int = 10,
    ) -> dict[str, Any]:
        """Search within a specific Confluence space.

        Args:
            query: Search query text
            space_key: Confluence space key (e.g., "IT", "OPS", "DEV")
            top_k: Maximum number of results (default 10)

        Returns:
            Search results from the specified space
        """
        try:
            search_engine = self._get_search_engine()

            from infrastructure_atlas.confluence_rag.qdrant_search import SearchConfig

            config = SearchConfig(
                top_k=top_k,
                min_score=0.3,
                include_citations=True,
                space_keys=[space_key.upper()],
            )

            response = asyncio.run(search_engine.search(query, config))

            return {
                "success": True,
                "query": query,
                "space_key": space_key,
                "total_results": response.total_results,
                "results": [
                    {
                        "title": r.page.title,
                        "page_id": r.page.page_id,
                        "url": r.page.url,
                        "relevance_score": r.relevance_score,
                        "content_preview": r.content[:300] + "..." if len(r.content) > 300 else r.content,
                        "labels": r.page.labels,
                    }
                    for r in response.results
                ],
            }
        except Exception as e:
            logger.error(f"Failed to search Confluence space '{space_key}': {e}")
            return {"success": False, "error": str(e)}

    def _get_related_pages(
        self,
        page_id: str,
        top_k: int = 5,
    ) -> dict[str, Any]:
        """Find pages related to a given page.

        Uses the content of the specified page to find similar documentation.

        Args:
            page_id: Source page ID to find related content for
            top_k: Maximum number of related pages (default 5)

        Returns:
            List of related pages
        """
        try:
            search_engine = self._get_search_engine()

            # First get the source page
            page, chunks = search_engine.get_page(page_id)
            if page is None:
                return {"success": False, "error": f"Page {page_id} not found"}

            # Use the page title and first chunk content as search query
            query_text = page.title
            if chunks:
                query_text = f"{page.title} {chunks[0].content[:200]}"

            from infrastructure_atlas.confluence_rag.qdrant_search import SearchConfig

            config = SearchConfig(
                top_k=top_k + 1,  # +1 to exclude the source page
                min_score=0.4,
                include_citations=False,
            )

            response = asyncio.run(search_engine.search(query_text, config))

            # Filter out the source page
            related = [r for r in response.results if r.page.page_id != page_id][:top_k]

            return {
                "success": True,
                "source_page": {
                    "page_id": page.page_id,
                    "title": page.title,
                    "url": page.url,
                },
                "related_pages": [
                    {
                        "title": r.page.title,
                        "page_id": r.page.page_id,
                        "url": r.page.url,
                        "space_key": r.page.space_key,
                        "relevance_score": r.relevance_score,
                        "labels": r.page.labels,
                    }
                    for r in related
                ],
            }
        except Exception as e:
            logger.error(f"Failed to find related pages for {page_id}: {e}")
            return {"success": False, "error": str(e)}


__all__ = ["ConfluenceSkill"]
