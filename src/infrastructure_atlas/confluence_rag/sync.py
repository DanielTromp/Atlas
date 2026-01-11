import asyncio
from datetime import datetime
import logging
import json

from infrastructure_atlas.confluence_rag.models import ConfluencePage, Chunk, ChunkWithEmbedding
from infrastructure_atlas.confluence_rag.config import ConfluenceRAGSettings
from infrastructure_atlas.confluence_rag.database import Database
from infrastructure_atlas.confluence_rag.confluence_client import ConfluenceClient
from infrastructure_atlas.confluence_rag.chunker import ConfluenceChunker
from infrastructure_atlas.confluence_rag.embeddings import EmbeddingPipeline

logger = logging.getLogger(__name__)

class ConfluenceSyncEngine:
    """
    Synchronizes Confluence content to the RAG cache.
    """
    
    def __init__(
        self,
        confluence_client: ConfluenceClient,
        db: Database,
        chunker: ConfluenceChunker,
        embedding_pipeline: EmbeddingPipeline,
        settings: ConfluenceRAGSettings
    ):
        self.confluence = confluence_client
        self.db = db
        self.chunker = chunker
        self.embeddings = embedding_pipeline
        self.settings = settings
    
    async def full_sync(self, spaces: list[str] | None = None, ancestor_id: str | None = None):
        """
        Perform a full sync for all configured spaces.
        """
        spaces = spaces or self.settings.watched_spaces
        
        for space in spaces:
            logger.info(f"Starting full sync for space: {space}")
            try:
                await self._sync_space(space, incremental=False, ancestor_id=ancestor_id)
                self._update_sync_state(space, "completed")
            except Exception as e:
                logger.error(f"Sync failed for space {space}: {e}")
                self._update_sync_state(space, "failed", str(e))
    
    async def incremental_sync(self, spaces: list[str] | None = None, ancestor_id: str | None = None):
        """
        Sync only changed pages since last sync.
        """
        spaces = spaces or self.settings.watched_spaces
        
        for space in spaces:
            last_sync = self._get_last_sync(space)
            logger.info(f"Incremental sync for {space} since {last_sync}")
            
            try:
                await self._sync_space(space, incremental=True, since=last_sync, ancestor_id=ancestor_id)
                self._update_sync_state(space, "completed")
            except Exception as e:
                logger.error(f"Incremental sync failed for {space}: {e}")
                self._update_sync_state(space, "failed", str(e))
    
    async def _sync_space(
        self,
        space_key: str,
        incremental: bool = True,
        since: datetime | None = None,
        ancestor_id: str | None = None
    ):
        """Sync a single space"""
        import sys

        pages_processed = 0
        pages_skipped = 0
        pages_failed = 0
        chunks_created = 0
        seen_page_ids: set[str] = set()  # Track pages to avoid duplicates

        async for page_data in self.confluence.get_pages_in_space(
            space_key=space_key,
            labels=self.settings.watched_labels,
            updated_after=since if incremental else None,
            ancestor_id=ancestor_id
        ):
            page_num = pages_processed + pages_skipped + pages_failed + 1
            page_id = page_data.get("id", "?")
            page_title = page_data.get("title", "Unknown")[:50]

            # Skip if we've already processed this page in this session
            if page_id in seen_page_ids:
                print(f"[{page_num}] {page_title} - DUPLICATE, skipping", flush=True)
                continue
            seen_page_ids.add(page_id)

            try:
                # Progress: fetching
                print(f"[{page_num}] {page_title}", flush=True)

                page = self._parse_page_data(page_data, space_key)

                # Fetch full content (export_view for Docling processing)
                print(f"  -> Exporting HTML...", end="", flush=True)
                html_content, html_warning = await self.confluence.export_page_html(page.page_id)

                if html_warning:
                    print(f" {len(html_content):,} chars ({html_warning})", flush=True)
                else:
                    print(f" {len(html_content):,} chars", flush=True)

                # Skip pages with no content
                if not html_content.strip():
                    print(f"  -> SKIPPED: empty page", flush=True)
                    pages_skipped += 1
                    continue

                # Chunk the page
                print(f"  -> Chunking...", end="", flush=True)
                chunks = self.chunker.chunk_page(page, html_content, "")
                print(f" {len(chunks)} chunks", flush=True)

                # Generate embeddings
                print(f"  -> Embedding...", end="", flush=True)
                chunks_with_embeddings = self.embeddings.embed_chunks(
                    chunks,
                    show_progress=False
                )
                print(f" done", flush=True)

                # Store in database
                print(f"  -> Storing...", end="", flush=True)
                await self._store_page_and_chunks(page, chunks_with_embeddings)
                print(f" done", flush=True)

                pages_processed += 1
                chunks_created += len(chunks)

                # Periodic checkpoint to prevent DB bloat (every 50 pages)
                if pages_processed % 50 == 0:
                    conn = self.db.connect()
                    conn.execute("CHECKPOINT")
                    print(f"  [checkpoint at {pages_processed} pages]", flush=True)

            except Exception as e:
                pages_failed += 1
                print(f"  -> ERROR: {e}", file=sys.stderr, flush=True)
                continue

        summary_parts = [f"{pages_processed} pages", f"{chunks_created} chunks"]
        if pages_skipped:
            summary_parts.append(f"{pages_skipped} skipped")
        if pages_failed:
            summary_parts.append(f"{pages_failed} failed")

        print(f"\nSpace {space_key} complete: {', '.join(summary_parts)}", flush=True)

    async def _store_page_and_chunks(
        self,
        page: ConfluencePage,
        chunks: list[ChunkWithEmbedding]
    ):
        """Store page and chunks in database.

        Note: DuckDB's foreign key constraint checker doesn't see uncommitted
        deletes within the same transaction. We must commit the deletion of
        child rows (chunks, embeddings) before upserting the parent (page).
        """
        conn = self.db.connect()

        # Step 1: Delete existing child data in a separate transaction
        # This must be committed before we can upsert the page due to DuckDB FK limitations
        existing = conn.execute(
            "SELECT chunk_id FROM chunks WHERE page_id = $1",
            [page.page_id]
        ).fetchall()

        if existing:
            chunk_ids = [r[0] for r in existing]
            logger.debug(f"Deleting {len(chunk_ids)} existing chunks for page {page.page_id}")

            conn.execute("BEGIN TRANSACTION")
            try:
                # Delete embeddings first (no FK, but cleanup)
                for cid in chunk_ids:
                    conn.execute("DELETE FROM chunk_embeddings WHERE chunk_id = $1", [cid])

                # Delete chunks
                conn.execute("DELETE FROM chunks WHERE page_id = $1", [page.page_id])
                conn.execute("COMMIT")
            except Exception as e:
                conn.execute("ROLLBACK")
                raise e

        # Step 2: Upsert page and insert new chunks in a new transaction
        conn.execute("BEGIN TRANSACTION")
        try:
            # Upsert page (raw_content removed to eliminate base64 image bloat)
            conn.execute("""
                INSERT INTO pages (
                    page_id, space_key, title, url, labels, version,
                    updated_at, updated_by, parent_id, ancestors, synced_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                ON CONFLICT (page_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    labels = EXCLUDED.labels,
                    version = EXCLUDED.version,
                    updated_at = EXCLUDED.updated_at,
                    synced_at = EXCLUDED.synced_at
            """, [
                page.page_id, page.space_key, page.title, page.url,
                page.labels, page.version, page.updated_at, page.updated_by,
                page.parent_id, page.ancestors, datetime.now()
            ])

            # Insert chunks
            for chunk in chunks:
                conn.execute("""
                    INSERT INTO chunks (
                        chunk_id, page_id, content, context_path, chunk_type,
                        token_count, position_in_page, heading_context, metadata
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """, [
                    chunk.chunk_id, chunk.page_id, chunk.content,
                    chunk.context_path, chunk.chunk_type.value,
                    chunk.token_count, chunk.position_in_page, chunk.heading_context,
                    json.dumps(chunk.metadata)
                ])

                # Insert embedding
                conn.execute("""
                    INSERT INTO chunk_embeddings (chunk_id, embedding, model_version)
                    VALUES ($1, $2, $3)
                """, [chunk.chunk_id, chunk.embedding, self.settings.embedding_model])

            conn.execute("COMMIT")

        except Exception as e:
            conn.execute("ROLLBACK")
            raise e
    
    def _parse_page_data(self, data: dict, space_key: str) -> ConfluencePage:
        """Parse Confluence API response to ConfluencePage model"""
        # Confluence API structure handling
        # version.when usually '2023-01-01T10:00:00.000Z'
        updated = data["version"]["when"]
        try:
             # fromisoformat handles Z in Python 3.11+
             updated_at = datetime.fromisoformat(updated.replace("Z", "+00:00"))
        except:
             updated_at = datetime.now()  # Fallback

        # Build the page URL from _links.webui
        # webui is typically "/spaces/SPACE/pages/ID/Title" (relative path)
        # base_url is typically "https://company.atlassian.net" (no /wiki)
        webui = data["_links"]["webui"]

        if webui.startswith("http"):
            # Already absolute URL
            url = webui
        else:
            # Build absolute URL: base + /wiki + webui path
            base = self.confluence.base_url.rstrip("/")
            # Ensure /wiki is included (Confluence Cloud uses /wiki context)
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
            labels=[l["name"] for l in data.get("metadata", {}).get("labels", {}).get("results", [])],
            version=data["version"]["number"],
            updated_at=updated_at,
            updated_by=data["version"]["by"]["displayName"],
            parent_id=data.get("ancestors", [{}])[-1].get("id") if data.get("ancestors") else None,
            ancestors=[a["title"] for a in data.get("ancestors", [])]
        )
    
    def _get_last_sync(self, space_key: str) -> datetime | None:
        """Get last sync timestamp for a space"""
        conn = self.db.connect()
        try:
            result = conn.execute(
                "SELECT last_sync_at FROM sync_state WHERE space_key = $1",
                [space_key]
            ).fetchone()
            return result[0] if result else None
        except:
            return None
    
    def _update_sync_state(
        self, 
        space_key: str, 
        status: str, 
        error_message: str | None = None
    ):
        """Update sync state for a space"""
        conn = self.db.connect()
        
        try:
            # Get current counts
            page_count = conn.execute(
                "SELECT COUNT(*) FROM pages WHERE space_key = $1",
                [space_key]
            ).fetchone()[0]
            
            chunk_count = conn.execute(
                "SELECT COUNT(*) FROM chunks c JOIN pages p ON c.page_id = p.page_id WHERE p.space_key = $1",
                [space_key]
            ).fetchone()[0]
            
            conn.execute("""
                INSERT INTO sync_state (space_key, last_sync_at, last_page_count, last_chunk_count, status, error_message)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (space_key) DO UPDATE SET
                    last_sync_at = EXCLUDED.last_sync_at,
                    last_page_count = EXCLUDED.last_page_count,
                    last_chunk_count = EXCLUDED.last_chunk_count,
                    status = EXCLUDED.status,
                    error_message = EXCLUDED.error_message
            """, [space_key, datetime.now(), page_count, chunk_count, status, error_message])
        except Exception as e:
            logger.warning(f"Failed to update sync state: {e}")
