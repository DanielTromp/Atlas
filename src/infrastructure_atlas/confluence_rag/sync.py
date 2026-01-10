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
        
        pages_processed = 0
        chunks_created = 0
        
        async for page_data in self.confluence.get_pages_in_space(
            space_key=space_key,
            labels=self.settings.watched_labels,
            updated_after=since if incremental else None,
            ancestor_id=ancestor_id
        ):
            try:
                # Parse page metadata
                page = self._parse_page_data(page_data, space_key)
                
                # Fetch full content
                html_content = await self.confluence.export_page_html(page.page_id)
                raw_content = page_data.get("body", {}).get("storage", {}).get("value", "")
                
                # Chunk the page
                logger.info(f"Chunking page {page.page_id} (HTML len: {len(html_content)}, Raw len: {len(raw_content)})")
                chunks = self.chunker.chunk_page(page, html_content, raw_content)
                logger.info(f"Generated {len(chunks)} chunks")
                
                # Generate embeddings
                chunks_with_embeddings = self.embeddings.embed_chunks(
                    chunks, 
                    show_progress=False
                )
                
                # Store in database
                await self._store_page_and_chunks(page, raw_content, chunks_with_embeddings)
                
                pages_processed += 1
                chunks_created += len(chunks)
                
                logger.debug(f"Processed page: {page.title} ({len(chunks)} chunks)")
                
            except Exception as e:
                logger.error(f"Failed to process page {page_data.get('id')}: {e}")
                continue
        
        logger.info(
            f"Space {space_key} sync complete: "
            f"{pages_processed} pages, {chunks_created} chunks"
        )
    async def _store_page_and_chunks(
        self,
        page: ConfluencePage,
        raw_content: str,
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
            # Upsert page
            conn.execute("""
                INSERT INTO pages (
                    page_id, space_key, title, url, labels, version,
                    updated_at, updated_by, parent_id, ancestors,
                    synced_at, raw_content
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                ON CONFLICT (page_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    labels = EXCLUDED.labels,
                    version = EXCLUDED.version,
                    updated_at = EXCLUDED.updated_at,
                    synced_at = EXCLUDED.synced_at,
                    raw_content = EXCLUDED.raw_content
            """, [
                page.page_id, page.space_key, page.title, page.url,
                page.labels, page.version, page.updated_at, page.updated_by,
                page.parent_id, page.ancestors, datetime.now(), raw_content
            ])

            # Insert chunks
            for chunk in chunks:
                span_start = chunk.text_spans[0].start_char if chunk.text_spans else None
                span_end = chunk.text_spans[0].end_char if chunk.text_spans else None

                conn.execute("""
                    INSERT INTO chunks (
                        chunk_id, page_id, content, original_content,
                        context_path, chunk_type, token_count, position_in_page,
                        heading_context, text_span_start, text_span_end, metadata
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                """, [
                    chunk.chunk_id, chunk.page_id, chunk.content,
                    chunk.original_content, chunk.context_path, chunk.chunk_type.value,
                    chunk.token_count, chunk.position_in_page, chunk.heading_context,
                    span_start, span_end,
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

        # _links.webui is usually relative to the context root (e.g. /wiki/spaces/...)
        # or sometimes just /spaces/... depending on instance.
        # We assume base_url is configured as ".../wiki"
        # We cleanse base_url of any API suffixes just in case
        base_clean = self.confluence.base_url
        for suffix in ["/rest/api", "/v1"]:
            if base_clean.endswith(suffix):
                try:
                    base_clean = base_clean.removesuffix(suffix)
                except AttributeError:
                    base_clean = base_clean[:-len(suffix)]
        
        # If webui starts with /, join carefully
        webui = data["_links"]["webui"]
        if webui.startswith("/wiki/"):
                # if webui already has context, and base has it too, avoid double
                if base_clean.endswith("/wiki"):
                    try:
                        base_clean = base_clean.removesuffix("/wiki")
                    except AttributeError:
                        base_clean = base_clean[:-5] # remove /wiki
        
        url = webui if webui.startswith("http") else f"{base_clean}{webui}"

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
