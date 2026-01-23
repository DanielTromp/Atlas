"""Confluence skill implementation for agent workflows.

Provides documentation and knowledge base actions:
- Semantic search across Confluence
- Page retrieval with content
- Find related documentation
- Create, update, and delete pages
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
import re
import time
from typing import Any

import requests

from infrastructure_atlas.infrastructure.logging import get_logger
from infrastructure_atlas.skills.base import BaseSkill

logger = get_logger(__name__)


def _log_rag_analytics(query: str, result_count: int, top_score: float | None, duration_ms: int) -> None:
    """Log query to RAG analytics (best effort)."""
    try:
        from infrastructure_atlas.confluence_rag.api import _query_analytics

        _query_analytics.log_query(
            query=query,
            result_count=result_count,
            top_score=top_score,
            duration_ms=duration_ms,
        )
    except Exception as e:
        logger.debug(f"Could not log to RAG analytics: {e}")


def _run_async(coro):
    """Run an async coroutine, handling both sync and async contexts.

    When called from a sync context, uses asyncio.run().
    When called from an async context (like Slack bot), runs in a thread pool.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop - use asyncio.run()
        return asyncio.run(coro)
    else:
        # Already in async context - run in thread to avoid blocking
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result(timeout=60)


class ConfluenceSkill(BaseSkill):
    """Skill for interacting with Confluence documentation.

    Provides actions for:
    - Searching for documentation semantically
    - Retrieving page content
    - Finding relevant runbooks and procedures
    - Creating, updating, and deleting pages
    """

    name = "confluence"
    description = "Search, retrieve, and manage Confluence documentation, runbooks, and procedures"
    category = "documentation"

    def __init__(self) -> None:
        super().__init__()
        self._search_engine = None
        self._session: requests.Session | None = None
        self._wiki_url: str | None = None

    def _get_search_engine(self):
        """Get or create search engine lazily."""
        if self._search_engine is None:
            try:
                from infrastructure_atlas.confluence_rag.api import get_search_engine

                logger.info("Initializing Confluence RAG search engine")
                self._search_engine = get_search_engine()
                logger.info("Confluence RAG search engine initialized successfully")
            except Exception as e:
                logger.warning(f"Could not initialize Confluence RAG search engine: {e}")
                raise
        return self._search_engine

    def _get_rest_session(self) -> tuple[requests.Session, str]:
        """Get or create REST API session lazily."""
        if self._session is None:
            base = os.getenv("ATLASSIAN_BASE_URL", "").strip() or os.getenv("JIRA_BASE_URL", "").strip()
            email = os.getenv("ATLASSIAN_EMAIL", "").strip() or os.getenv("JIRA_EMAIL", "").strip()
            token = os.getenv("ATLASSIAN_API_TOKEN", "").strip() or os.getenv("JIRA_API_TOKEN", "").strip()

            if not (base and email and token):
                raise RuntimeError(
                    "Confluence REST API not configured: set ATLASSIAN_BASE_URL, ATLASSIAN_EMAIL, ATLASSIAN_API_TOKEN"
                )

            self._session = requests.Session()
            self._session.auth = (email, token)
            self._session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
            self._wiki_url = base.rstrip("/") + "/wiki"

        return self._session, self._wiki_url  # type: ignore[return-value]

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

        # Write operations (use REST API)
        self.register_action(
            name="update_page",
            func=self._update_page,
            description="Update an existing Confluence page content. Supports storage format (HTML) or markdown.",
            is_destructive=True,
            input_schema={
                "type": "object",
                "properties": {
                    "page_id": {"type": "string", "description": "Confluence page ID to update"},
                    "content": {"type": "string", "description": "New page content"},
                    "content_format": {
                        "type": "string",
                        "enum": ["storage", "markdown"],
                        "description": "Format: 'storage' (HTML) or 'markdown' (default: storage)",
                    },
                    "title": {"type": "string", "description": "New title (optional, keeps current if not provided)"},
                    "version_comment": {"type": "string", "description": "Version comment for the change"},
                },
                "required": ["page_id", "content"],
            },
        )

        self.register_action(
            name="create_page",
            func=self._create_page,
            description="Create a new Confluence page in a space. Supports storage format (HTML) or markdown.",
            is_destructive=True,
            input_schema={
                "type": "object",
                "properties": {
                    "space_key": {"type": "string", "description": "Confluence space key (e.g., DOCS, IT)"},
                    "title": {"type": "string", "description": "Page title"},
                    "content": {"type": "string", "description": "Page content"},
                    "content_format": {
                        "type": "string",
                        "enum": ["storage", "markdown"],
                        "description": "Format: 'storage' (HTML) or 'markdown' (default: storage)",
                    },
                    "parent_page_id": {"type": "string", "description": "Parent page ID for hierarchy (optional)"},
                    "labels": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Labels to add to the page (optional)",
                    },
                },
                "required": ["space_key", "title", "content"],
            },
        )

        self.register_action(
            name="append_to_page",
            func=self._append_to_page,
            description="Append or prepend content to an existing Confluence page without replacing existing content.",
            is_destructive=True,
            input_schema={
                "type": "object",
                "properties": {
                    "page_id": {"type": "string", "description": "Confluence page ID to append to"},
                    "content": {"type": "string", "description": "Content to append"},
                    "content_format": {
                        "type": "string",
                        "enum": ["storage", "markdown"],
                        "description": "Format: 'storage' (HTML) or 'markdown' (default: storage)",
                    },
                    "position": {
                        "type": "string",
                        "enum": ["end", "start"],
                        "description": "Where to add: 'end' (append) or 'start' (prepend) (default: end)",
                    },
                    "version_comment": {"type": "string", "description": "Version comment for the change"},
                },
                "required": ["page_id", "content"],
            },
        )

        self.register_action(
            name="delete_page",
            func=self._delete_page,
            description="Delete a Confluence page by ID. This action is irreversible.",
            is_destructive=True,
            requires_confirmation=True,
            input_schema={
                "type": "object",
                "properties": {
                    "page_id": {"type": "string", "description": "Confluence page ID to delete"},
                },
                "required": ["page_id"],
            },
        )

        self.register_action(
            name="get_page_by_id",
            func=self._get_page_by_id,
            description="Get a Confluence page by ID using REST API (includes full content in storage format)",
            is_destructive=False,
            input_schema={
                "type": "object",
                "properties": {
                    "page_id": {"type": "string", "description": "Confluence page ID"},
                },
                "required": ["page_id"],
            },
        )

        logger.info("ConfluenceSkill initialized with 10 actions")

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
        start_time = time.time()
        try:
            logger.info(f"Confluence RAG search starting", extra={"query": query[:100], "top_k": top_k})
            search_engine = self._get_search_engine()

            from infrastructure_atlas.confluence_rag.qdrant_search import SearchConfig

            config = SearchConfig(
                top_k=top_k,
                min_score=min_score,
                include_citations=include_citations,
            )

            # Run async search in sync context
            response = _run_async(search_engine.search(query, config))
            duration_ms = int((time.time() - start_time) * 1000)

            # Log to RAG analytics
            top_score = response.results[0].relevance_score if response.results else None
            _log_rag_analytics(query, response.total_results, top_score, duration_ms)

            logger.info(
                f"Confluence RAG search completed",
                extra={"query": query[:50], "results": response.total_results, "time_ms": duration_ms},
            )

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
                                "quote": c.quote,
                                "page_title": c.page_title,
                                "section": c.section,
                                "confidence": c.confidence_score,
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
        start_time = time.time()
        try:
            logger.info(f"Confluence RAG runbook search", extra={"topic": topic, "top_k": top_k})
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
            search_query = f"runbook {topic}"
            response = _run_async(search_engine.search(search_query, config))

            # If no results, try without label filter
            if response.total_results == 0:
                logger.debug("No runbooks with labels, retrying without label filter")
                config.labels = None
                search_query = f"runbook procedure how to {topic}"
                response = _run_async(search_engine.search(search_query, config))

            duration_ms = int((time.time() - start_time) * 1000)
            top_score = response.results[0].relevance_score if response.results else None
            _log_rag_analytics(search_query, response.total_results, top_score, duration_ms)

            logger.info(f"Confluence RAG runbook search completed", extra={"topic": topic, "results": response.total_results})
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
        start_time = time.time()
        try:
            logger.info(f"Confluence RAG space search", extra={"query": query[:50], "space_key": space_key, "top_k": top_k})
            search_engine = self._get_search_engine()

            from infrastructure_atlas.confluence_rag.qdrant_search import SearchConfig

            config = SearchConfig(
                top_k=top_k,
                min_score=0.3,
                include_citations=True,
                space_keys=[space_key.upper()],
            )

            response = _run_async(search_engine.search(query, config))
            duration_ms = int((time.time() - start_time) * 1000)
            top_score = response.results[0].relevance_score if response.results else None
            _log_rag_analytics(f"[{space_key}] {query}", response.total_results, top_score, duration_ms)

            logger.info(f"Confluence RAG space search completed", extra={"space_key": space_key, "results": response.total_results})

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
        start_time = time.time()
        try:
            logger.info(f"Confluence RAG related pages search", extra={"page_id": page_id, "top_k": top_k})
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

            response = _run_async(search_engine.search(query_text, config))

            # Filter out the source page
            related = [r for r in response.results if r.page.page_id != page_id][:top_k]
            duration_ms = int((time.time() - start_time) * 1000)
            top_score = related[0].relevance_score if related else None
            _log_rag_analytics(f"[related:{page_id}] {query_text[:50]}", len(related), top_score, duration_ms)

            logger.info(f"Confluence RAG related pages completed", extra={"page_id": page_id, "related_count": len(related)})

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

    # =========================================================================
    # Write operations (REST API)
    # =========================================================================

    def _markdown_to_storage(self, markdown: str) -> str:
        """Convert markdown to Confluence storage format (basic conversion)."""
        content = markdown

        # Headers
        content = re.sub(r"^### (.+)$", r"<h3>\1</h3>", content, flags=re.MULTILINE)
        content = re.sub(r"^## (.+)$", r"<h2>\1</h2>", content, flags=re.MULTILINE)
        content = re.sub(r"^# (.+)$", r"<h1>\1</h1>", content, flags=re.MULTILINE)

        # Bold and italic
        content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", content)
        content = re.sub(r"\*(.+?)\*", r"<em>\1</em>", content)

        # Code blocks
        content = re.sub(
            r"```(\w+)?\n(.*?)\n```",
            r'<ac:structured-macro ac:name="code"><ac:parameter ac:name="language">\1</ac:parameter>'
            r"<ac:plain-text-body><![CDATA[\2]]></ac:plain-text-body></ac:structured-macro>",
            content,
            flags=re.DOTALL,
        )
        content = re.sub(r"`([^`]+)`", r"<code>\1</code>", content)

        # Lists (basic)
        lines = content.split("\n")
        in_list = False
        result: list[str] = []
        for line in lines:
            if line.startswith("- ") or line.startswith("* "):
                if not in_list:
                    result.append("<ul>")
                    in_list = True
                result.append(f"<li>{line[2:]}</li>")
            else:
                if in_list:
                    result.append("</ul>")
                    in_list = False
                result.append(line)
        if in_list:
            result.append("</ul>")
        content = "\n".join(result)

        # Paragraphs (wrap non-html lines)
        lines = content.split("\n")
        result = []
        for raw_line in lines:
            stripped = raw_line.strip()
            if stripped and not stripped.startswith("<"):
                result.append(f"<p>{stripped}</p>")
            else:
                result.append(stripped)

        return "\n".join(result)

    def _get_page_by_id(self, page_id: str) -> dict[str, Any]:
        """Get a Confluence page by ID using REST API.

        Args:
            page_id: The Confluence page ID

        Returns:
            Page details with content in storage format
        """
        try:
            session, wiki_url = self._get_rest_session()
            url = f"{wiki_url}/rest/api/content/{page_id}"
            params = {"expand": "body.storage,version,space,ancestors"}

            resp = session.get(url, params=params, timeout=30)
            if resp.status_code == 404:
                return {"success": False, "error": f"Page {page_id} not found"}
            if resp.status_code == 401:
                return {"success": False, "error": "Authentication failed; check ATLASSIAN_API_TOKEN"}
            resp.raise_for_status()

            data = resp.json()
            return {
                "success": True,
                "page_id": data.get("id", ""),
                "title": data.get("title", ""),
                "space_key": (data.get("space") or {}).get("key", ""),
                "version": (data.get("version") or {}).get("number", 1),
                "content": (data.get("body", {}).get("storage", {}) or {}).get("value", ""),
                "url": f"{wiki_url}{(data.get('_links') or {}).get('webui', '')}",
                "ancestors": [{"id": a.get("id"), "title": a.get("title")} for a in (data.get("ancestors") or [])],
            }
        except Exception as e:
            logger.error(f"Failed to get Confluence page {page_id}: {e}")
            return {"success": False, "error": str(e)}

    def _update_page(
        self,
        page_id: str,
        content: str,
        content_format: str = "storage",
        title: str | None = None,
        version_comment: str | None = None,
    ) -> dict[str, Any]:
        """Update an existing Confluence page.

        Args:
            page_id: Confluence page ID to update
            content: New page content
            content_format: Format: 'storage' (HTML) or 'markdown'
            title: New title (optional, keeps current if not provided)
            version_comment: Version comment for the change

        Returns:
            Result dict with page details
        """
        try:
            session, wiki_url = self._get_rest_session()

            # Get current page for version number
            get_url = f"{wiki_url}/rest/api/content/{page_id}"
            resp = session.get(get_url, params={"expand": "version,space"}, timeout=30)
            if resp.status_code == 404:
                return {"success": False, "error": f"Page {page_id} not found"}
            if resp.status_code == 401:
                return {"success": False, "error": "Authentication failed; check ATLASSIAN_API_TOKEN"}
            resp.raise_for_status()
            current = resp.json()

            current_version = (current.get("version") or {}).get("number", 0)
            current_title = current.get("title", "")
            space_key = (current.get("space") or {}).get("key", "")

            # Convert markdown if needed
            if content_format == "markdown":
                content = self._markdown_to_storage(content)

            page_title = title if title is not None else current_title

            payload: dict[str, Any] = {
                "type": "page",
                "title": page_title,
                "version": {"number": current_version + 1, "minorEdit": False},
                "body": {"storage": {"value": content, "representation": "storage"}},
            }
            if version_comment:
                payload["version"]["message"] = version_comment

            resp = session.put(f"{wiki_url}/rest/api/content/{page_id}", json=payload, timeout=30)
            if resp.status_code == 401:
                return {"success": False, "error": "Authentication failed; check ATLASSIAN_API_TOKEN"}
            if resp.status_code == 400:
                error_data = resp.json() if resp.text else {}
                detail = error_data.get("message", str(error_data))
                return {"success": False, "error": f"Invalid update data: {detail}"}
            resp.raise_for_status()

            result = resp.json()
            logger.info(f"Updated Confluence page {page_id}", extra={"title": page_title})
            return {
                "success": True,
                "page_id": result.get("id", ""),
                "title": result.get("title", ""),
                "space_key": space_key,
                "version": (result.get("version") or {}).get("number", current_version + 1),
                "url": f"{wiki_url}{(result.get('_links') or {}).get('webui', '')}",
            }
        except Exception as e:
            logger.error(f"Failed to update Confluence page {page_id}: {e}")
            return {"success": False, "error": str(e)}

    def _create_page(
        self,
        space_key: str,
        title: str,
        content: str,
        content_format: str = "storage",
        parent_page_id: str | None = None,
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a new Confluence page.

        Args:
            space_key: Confluence space key (e.g., DOCS, IT)
            title: Page title
            content: Page content
            content_format: Format: 'storage' (HTML) or 'markdown'
            parent_page_id: Parent page ID for hierarchy (optional)
            labels: Labels to add to the page (optional)

        Returns:
            Result dict with page details
        """
        try:
            session, wiki_url = self._get_rest_session()

            # Convert markdown if needed
            if content_format == "markdown":
                content = self._markdown_to_storage(content)

            payload: dict[str, Any] = {
                "type": "page",
                "title": title,
                "space": {"key": space_key},
                "body": {"storage": {"value": content, "representation": "storage"}},
            }
            if parent_page_id:
                payload["ancestors"] = [{"id": parent_page_id}]

            resp = session.post(f"{wiki_url}/rest/api/content", json=payload, timeout=30)
            if resp.status_code == 401:
                return {"success": False, "error": "Authentication failed; check ATLASSIAN_API_TOKEN"}
            if resp.status_code == 400:
                error_data = resp.json() if resp.text else {}
                detail = error_data.get("message", str(error_data))
                return {"success": False, "error": f"Invalid page data: {detail}"}
            resp.raise_for_status()

            result = resp.json()
            page_id = result.get("id", "")

            # Add labels if provided
            if labels and page_id:
                try:
                    labels_url = f"{wiki_url}/rest/api/content/{page_id}/label"
                    labels_payload = [{"name": label} for label in labels]
                    session.post(labels_url, json=labels_payload, timeout=15)
                except Exception:
                    pass  # Best effort labeling

            logger.info(f"Created Confluence page {page_id}", extra={"title": title, "space_key": space_key})
            return {
                "success": True,
                "page_id": page_id,
                "title": result.get("title", ""),
                "space_key": (result.get("space") or {}).get("key", space_key),
                "version": (result.get("version") or {}).get("number", 1),
                "url": f"{wiki_url}{(result.get('_links') or {}).get('webui', '')}",
            }
        except Exception as e:
            logger.error(f"Failed to create Confluence page in space {space_key}: {e}")
            return {"success": False, "error": str(e)}

    def _append_to_page(
        self,
        page_id: str,
        content: str,
        content_format: str = "storage",
        position: str = "end",
        version_comment: str | None = None,
    ) -> dict[str, Any]:
        """Append or prepend content to an existing Confluence page.

        Args:
            page_id: Confluence page ID to append to
            content: Content to append
            content_format: Format: 'storage' (HTML) or 'markdown'
            position: Where to add: 'end' (append) or 'start' (prepend)
            version_comment: Version comment for the change

        Returns:
            Result dict with page details
        """
        try:
            session, wiki_url = self._get_rest_session()

            # Get current page content and version
            get_url = f"{wiki_url}/rest/api/content/{page_id}"
            resp = session.get(get_url, params={"expand": "body.storage,version,space"}, timeout=30)
            if resp.status_code == 404:
                return {"success": False, "error": f"Page {page_id} not found"}
            if resp.status_code == 401:
                return {"success": False, "error": "Authentication failed; check ATLASSIAN_API_TOKEN"}
            resp.raise_for_status()
            current = resp.json()

            current_version = (current.get("version") or {}).get("number", 0)
            current_title = current.get("title", "")
            space_key = (current.get("space") or {}).get("key", "")
            current_content = (current.get("body", {}).get("storage", {}) or {}).get("value", "")

            # Convert new content if markdown
            new_content = content
            if content_format == "markdown":
                new_content = self._markdown_to_storage(content)

            # Combine content
            if position == "start":
                combined = new_content + "\n" + current_content
            else:
                combined = current_content + "\n" + new_content

            payload: dict[str, Any] = {
                "type": "page",
                "title": current_title,
                "version": {"number": current_version + 1, "minorEdit": False},
                "body": {"storage": {"value": combined, "representation": "storage"}},
            }
            if version_comment:
                payload["version"]["message"] = version_comment

            resp = session.put(f"{wiki_url}/rest/api/content/{page_id}", json=payload, timeout=30)
            if resp.status_code == 401:
                return {"success": False, "error": "Authentication failed; check ATLASSIAN_API_TOKEN"}
            if resp.status_code == 400:
                error_data = resp.json() if resp.text else {}
                detail = error_data.get("message", str(error_data))
                return {"success": False, "error": f"Invalid update data: {detail}"}
            resp.raise_for_status()

            result = resp.json()
            logger.info(f"Appended to Confluence page {page_id}", extra={"position": position})
            return {
                "success": True,
                "page_id": result.get("id", ""),
                "title": result.get("title", ""),
                "space_key": space_key,
                "version": (result.get("version") or {}).get("number", current_version + 1),
                "position": position,
                "url": f"{wiki_url}{(result.get('_links') or {}).get('webui', '')}",
            }
        except Exception as e:
            logger.error(f"Failed to append to Confluence page {page_id}: {e}")
            return {"success": False, "error": str(e)}

    def _delete_page(self, page_id: str) -> dict[str, Any]:
        """Delete a Confluence page by ID.

        Args:
            page_id: Confluence page ID to delete

        Returns:
            Result dict confirming deletion
        """
        try:
            session, wiki_url = self._get_rest_session()

            # First get page info for response
            get_url = f"{wiki_url}/rest/api/content/{page_id}"
            resp = session.get(get_url, params={"expand": "space"}, timeout=30)
            if resp.status_code == 404:
                return {"success": False, "error": f"Page {page_id} not found"}
            if resp.status_code == 401:
                return {"success": False, "error": "Authentication failed; check ATLASSIAN_API_TOKEN"}
            resp.raise_for_status()
            page_info = resp.json()
            title = page_info.get("title", "")
            space_key = (page_info.get("space") or {}).get("key", "")

            # Delete the page
            resp = session.delete(f"{wiki_url}/rest/api/content/{page_id}", timeout=30)
            if resp.status_code == 401:
                return {"success": False, "error": "Authentication failed; check ATLASSIAN_API_TOKEN"}
            if resp.status_code == 403:
                return {"success": False, "error": "Permission denied: cannot delete this page"}
            if resp.status_code == 404:
                return {"success": False, "error": f"Page {page_id} not found"}
            resp.raise_for_status()

            logger.info(f"Deleted Confluence page {page_id}", extra={"title": title, "space_key": space_key})
            return {
                "success": True,
                "deleted_page_id": page_id,
                "deleted_title": title,
                "space_key": space_key,
            }
        except Exception as e:
            logger.error(f"Failed to delete Confluence page {page_id}: {e}")
            return {"success": False, "error": str(e)}


__all__ = ["ConfluenceSkill"]
