"""
Qdrant-based sync engine for Confluence RAG.

Synchronizes Confluence content to Qdrant vector store.
"""

import logging
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from infrastructure_atlas.confluence_rag.chunker import ConfluenceChunker
from infrastructure_atlas.confluence_rag.config import ConfluenceRAGSettings
from infrastructure_atlas.confluence_rag.confluence_client import ConfluenceClient
from infrastructure_atlas.confluence_rag.embeddings import EmbeddingPipeline
from infrastructure_atlas.confluence_rag.models import ConfluencePage
from infrastructure_atlas.confluence_rag.qdrant_store import QdrantStore

logger = logging.getLogger(__name__)


@dataclass
class SyncStats:
    """Statistics from a sync operation."""

    pages_processed: int = 0
    pages_skipped: int = 0
    pages_failed: int = 0
    chunks_created: int = 0
    start_time: datetime | None = None
    end_time: datetime | None = None

    @property
    def duration_seconds(self) -> float:
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0.0


class QdrantSyncEngine:
    """
    Synchronizes Confluence content to Qdrant vector store.

    Features:
    - Full and incremental sync modes
    - Progress reporting during sync
    - Deduplication of pages
    - Error handling with continuation
    """

    def __init__(
        self,
        confluence_client: ConfluenceClient,
        qdrant_store: QdrantStore,
        chunker: ConfluenceChunker,
        embedding_pipeline: EmbeddingPipeline,
        settings: ConfluenceRAGSettings,
    ):
        self.confluence = confluence_client
        self.store = qdrant_store
        self.chunker = chunker
        self.embeddings = embedding_pipeline
        self.settings = settings

    async def full_sync(
        self,
        spaces: list[str] | None = None,
        ancestor_id: str | None = None,
    ) -> SyncStats:
        """
        Perform a full sync for specified or all configured spaces.

        Args:
            spaces: List of space keys to sync (default: all watched spaces)
            ancestor_id: Only sync pages under this ancestor

        Returns:
            SyncStats with operation statistics
        """
        spaces = spaces or self.settings.watched_spaces
        total_stats = SyncStats(start_time=datetime.now())

        for space in spaces:
            logger.info(f"Starting full sync for space: {space}")
            try:
                stats = await self._sync_space(
                    space, incremental=False, ancestor_id=ancestor_id
                )
                total_stats.pages_processed += stats.pages_processed
                total_stats.pages_skipped += stats.pages_skipped
                total_stats.pages_failed += stats.pages_failed
                total_stats.chunks_created += stats.chunks_created
            except Exception as e:
                logger.error(f"Sync failed for space {space}: {e}")
                total_stats.pages_failed += 1

        total_stats.end_time = datetime.now()
        return total_stats

    async def incremental_sync(
        self,
        spaces: list[str] | None = None,
        since: datetime | None = None,
        ancestor_id: str | None = None,
    ) -> SyncStats:
        """
        Sync only pages changed since the specified time.

        Args:
            spaces: List of space keys to sync
            since: Only sync pages updated after this time (auto-detected if None)
            ancestor_id: Only sync pages under this ancestor

        Returns:
            SyncStats with operation statistics
        """
        spaces = spaces or self.settings.watched_spaces
        total_stats = SyncStats(start_time=datetime.now())

        for space in spaces:
            # Auto-detect last sync time if not provided
            effective_since = since
            if effective_since is None:
                effective_since = self.store.get_last_indexed_time(space)
                if effective_since:
                    logger.info(f"Auto-detected last sync time for {space}: {effective_since}")

            logger.info(f"Incremental sync for {space} since {effective_since}")
            try:
                stats = await self._sync_space(
                    space, incremental=True, since=effective_since, ancestor_id=ancestor_id
                )
                total_stats.pages_processed += stats.pages_processed
                total_stats.pages_skipped += stats.pages_skipped
                total_stats.pages_failed += stats.pages_failed
                total_stats.chunks_created += stats.chunks_created
            except Exception as e:
                logger.error(f"Incremental sync failed for {space}: {e}")
                total_stats.pages_failed += 1

        total_stats.end_time = datetime.now()
        return total_stats

    async def _sync_space(
        self,
        space_key: str,
        incremental: bool = True,
        since: datetime | None = None,
        ancestor_id: str | None = None,
    ) -> SyncStats:
        """Sync a single space."""
        stats = SyncStats(start_time=datetime.now())
        seen_page_ids: set[str] = set()  # Track pages to avoid duplicates

        async for page_data in self.confluence.get_pages_in_space(
            space_key=space_key,
            labels=self.settings.watched_labels,
            updated_after=since if incremental else None,
            ancestor_id=ancestor_id,
        ):
            page_num = (
                stats.pages_processed + stats.pages_skipped + stats.pages_failed + 1
            )
            page_id = page_data.get("id", "?")
            page_title = page_data.get("title", "Unknown")[:50]

            # Skip duplicates
            if page_id in seen_page_ids:
                print(f"[{page_num}] {page_title} - DUPLICATE, skipping", flush=True)
                continue
            seen_page_ids.add(page_id)

            try:
                page = self._parse_page_data(page_data, space_key)

                # Version check for incremental sync - skip unchanged pages
                if incremental:
                    stored_version = self.store.get_page_version(page_id)
                    if stored_version is not None and stored_version >= page.version:
                        print(f"[{page_num}] {page_title} - UNCHANGED (v{page.version}), skipping", flush=True)
                        stats.pages_skipped += 1
                        continue

                print(f"[{page_num}] {page_title} (v{page.version})", flush=True)

                # Fetch full content
                print("  -> Exporting HTML...", end="", flush=True)
                html_content, html_warning = await self.confluence.export_page_html(
                    page.page_id
                )

                if html_warning:
                    print(f" {len(html_content):,} chars ({html_warning})", flush=True)
                else:
                    print(f" {len(html_content):,} chars", flush=True)

                # Skip empty pages
                if not html_content.strip():
                    print("  -> SKIPPED: empty page", flush=True)
                    stats.pages_skipped += 1
                    continue

                # Chunk the page
                print("  -> Chunking...", end="", flush=True)
                chunks = self.chunker.chunk_page(page, html_content, "")
                print(f" {len(chunks)} chunks", flush=True)

                # Generate embeddings
                print("  -> Embedding...", end="", flush=True)
                chunks_with_embeddings = self.embeddings.embed_chunks(
                    chunks, show_progress=False
                )
                print(" done", flush=True)

                # Store in Qdrant
                print("  -> Storing...", end="", flush=True)
                stored_count = self.store.upsert_chunks(page, chunks_with_embeddings)
                print(f" {stored_count} vectors", flush=True)

                stats.pages_processed += 1
                stats.chunks_created += len(chunks)

            except Exception as e:
                stats.pages_failed += 1
                print(f"  -> ERROR: {e}", file=sys.stderr, flush=True)
                continue

        stats.end_time = datetime.now()

        # Print summary
        summary_parts = [
            f"{stats.pages_processed} pages",
            f"{stats.chunks_created} chunks",
        ]
        if stats.pages_skipped:
            summary_parts.append(f"{stats.pages_skipped} skipped")
        if stats.pages_failed:
            summary_parts.append(f"{stats.pages_failed} failed")

        print(f"\nSpace {space_key} complete: {', '.join(summary_parts)}", flush=True)

        return stats

    def _parse_page_data(self, data: dict[str, Any], space_key: str) -> ConfluencePage:
        """Parse Confluence API response to ConfluencePage model."""
        updated = data["version"]["when"]
        try:
            updated_at = datetime.fromisoformat(updated.replace("Z", "+00:00"))
        except Exception:
            updated_at = datetime.now()

        # Build the page URL from _links.webui
        webui = data["_links"]["webui"]

        if webui.startswith("http"):
            url = webui
        else:
            base = self.confluence.base_url.rstrip("/")
            if webui.startswith("/wiki/"):
                url = f"{base}{webui}"
            elif webui.startswith("/"):
                url = f"{base}/wiki{webui}"
            else:
                url = f"{base}/wiki/{webui}"

        return ConfluencePage(
            page_id=data["id"],
            space_key=space_key,
            title=data["title"],
            url=url,
            labels=[
                l["name"]
                for l in data.get("metadata", {}).get("labels", {}).get("results", [])
            ],
            version=data["version"]["number"],
            updated_at=updated_at,
            updated_by=data["version"]["by"]["displayName"],
            parent_id=(
                data.get("ancestors", [{}])[-1].get("id")
                if data.get("ancestors")
                else None
            ),
            ancestors=[a["title"] for a in data.get("ancestors", [])],
        )

    async def delete_space(self, space_key: str) -> int:
        """
        Delete all chunks for a space.

        Returns the number of chunks deleted.
        """
        # Get all page IDs in this space
        spaces = self.store.list_spaces()
        space_info = next((s for s in spaces if s["space_key"] == space_key), None)

        if not space_info:
            return 0

        # We need to delete by page_id since Qdrant doesn't have space-level deletion
        # This is a limitation - for now we'd need to scroll through all chunks
        # A better approach would be to add a delete-by-filter to QdrantStore
        logger.warning(
            f"Space deletion not fully implemented - {space_info['chunk_count']} chunks in {space_key}"
        )
        return 0

    def get_sync_stats(self) -> dict[str, Any]:
        """Get sync-related statistics."""
        spaces = self.store.list_spaces()
        store_stats = self.store.get_stats()

        return {
            "spaces": spaces,
            "total_chunks": store_stats.get("points_count", 0),
            "collection_status": store_stats.get("status", "unknown"),
        }
