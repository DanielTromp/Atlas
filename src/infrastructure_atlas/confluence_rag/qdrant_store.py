"""
Qdrant vector store for Confluence RAG.

Replaces DuckDB-based vector storage with Qdrant for better scalability and search performance.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.exceptions import UnexpectedResponse

from infrastructure_atlas.confluence_rag.config import ConfluenceRAGSettings
from infrastructure_atlas.confluence_rag.models import (
    ChunkType,
    ChunkWithEmbedding,
    ConfluencePage,
)

# Namespace UUID for generating deterministic UUIDs from chunk IDs
CHUNK_UUID_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # DNS namespace


def chunk_id_to_uuid(chunk_id: str) -> str:
    """Convert a chunk_id string to a deterministic UUID string."""
    return str(uuid.uuid5(CHUNK_UUID_NAMESPACE, chunk_id))

logger = logging.getLogger(__name__)

# Collection names
CHUNKS_COLLECTION = "confluence_chunks"


@dataclass
class QdrantConfig:
    """Qdrant connection configuration."""
    host: str = "localhost"
    port: int = 6333
    grpc_port: int = 6334
    prefer_grpc: bool = True
    api_key: str | None = None
    https: bool = False
    collection_name: str = CHUNKS_COLLECTION
    vector_size: int = 768


class QdrantStore:
    """
    Qdrant-based vector store for Confluence RAG.

    Stores chunk embeddings with full page metadata as payload.
    Supports semantic search with filtering by space, labels, and chunk type.
    """

    def __init__(self, config: QdrantConfig | None = None):
        if config is None:
            settings = ConfluenceRAGSettings()
            config = QdrantConfig(
                host=settings.qdrant_host,
                port=settings.qdrant_port,
                grpc_port=settings.qdrant_grpc_port,
                prefer_grpc=settings.qdrant_prefer_grpc,
                api_key=settings.qdrant_api_key,
                collection_name=settings.qdrant_collection,
                vector_size=settings.embedding_dimensions,
            )

        self.config = config
        self._client: QdrantClient | None = None

    @property
    def client(self) -> QdrantClient:
        """Lazy-initialize Qdrant client."""
        if self._client is None:
            self._client = QdrantClient(
                host=self.config.host,
                port=self.config.port,
                grpc_port=self.config.grpc_port,
                prefer_grpc=self.config.prefer_grpc,
                api_key=self.config.api_key,
                https=self.config.https,
            )
            self._ensure_collection()
        return self._client

    def _ensure_collection(self) -> None:
        """Create collection if it doesn't exist."""
        try:
            collections = self.client.get_collections().collections
            collection_names = [c.name for c in collections]

            if self.config.collection_name not in collection_names:
                logger.info(f"Creating collection: {self.config.collection_name}")
                self._client.create_collection(
                    collection_name=self.config.collection_name,
                    vectors_config=models.VectorParams(
                        size=self.config.vector_size,
                        distance=models.Distance.COSINE,
                    ),
                    # Optimized for search performance
                    hnsw_config=models.HnswConfigDiff(
                        m=16,
                        ef_construct=100,
                        full_scan_threshold=10000,
                    ),
                    # Enable payload indexing for common filters
                    optimizers_config=models.OptimizersConfigDiff(
                        indexing_threshold=20000,
                    ),
                )

                # Create payload indexes for filtering
                self._create_payload_indexes()
                logger.info(f"Collection {self.config.collection_name} created")
            else:
                logger.debug(f"Collection {self.config.collection_name} already exists")

        except UnexpectedResponse as e:
            logger.error(f"Failed to ensure collection: {e}")
            raise

    def _create_payload_indexes(self) -> None:
        """Create indexes on payload fields for efficient filtering."""
        indexed_fields = [
            ("space_key", models.PayloadSchemaType.KEYWORD),
            ("page_id", models.PayloadSchemaType.KEYWORD),
            ("chunk_type", models.PayloadSchemaType.KEYWORD),
            ("labels", models.PayloadSchemaType.KEYWORD),
        ]

        for field_name, field_type in indexed_fields:
            try:
                self._client.create_payload_index(
                    collection_name=self.config.collection_name,
                    field_name=field_name,
                    field_schema=field_type,
                )
            except UnexpectedResponse:
                # Index might already exist
                pass

    def upsert_chunks(
        self,
        page: ConfluencePage,
        chunks: list[ChunkWithEmbedding],
    ) -> int:
        """
        Upsert chunks for a page.

        First deletes existing chunks for the page, then inserts new ones.
        Returns the number of chunks upserted.
        """
        if not chunks:
            return 0

        # Delete existing chunks for this page
        self.delete_page_chunks(page.page_id)

        # Prepare points for upsert
        points = []
        for chunk in chunks:
            payload = self._build_payload(page, chunk)
            # Convert chunk_id to UUID for Qdrant compatibility
            point_id = chunk_id_to_uuid(chunk.chunk_id)
            points.append(
                models.PointStruct(
                    id=point_id,
                    vector=chunk.embedding,
                    payload=payload,
                )
            )

        # Batch upsert
        self.client.upsert(
            collection_name=self.config.collection_name,
            points=points,
            wait=True,
        )

        logger.debug(f"Upserted {len(points)} chunks for page {page.page_id}")
        return len(points)

    def _build_payload(
        self,
        page: ConfluencePage,
        chunk: ChunkWithEmbedding,
    ) -> dict[str, Any]:
        """Build payload dict for a chunk."""
        return {
            # Chunk data
            "chunk_id": chunk.chunk_id,
            "content": chunk.content,
            "original_content": chunk.original_content,
            "context_path": chunk.context_path,
            "chunk_type": chunk.chunk_type.value,
            "token_count": chunk.token_count,
            "position_in_page": chunk.position_in_page,
            "heading_context": chunk.heading_context,
            "metadata": chunk.metadata,
            # Page data (denormalized for search efficiency)
            "page_id": page.page_id,
            "space_key": page.space_key,
            "page_title": page.title,
            "page_url": page.url,
            "labels": page.labels,
            "version": page.version,
            "updated_at": page.updated_at.isoformat() if page.updated_at else None,
            "updated_by": page.updated_by,
            "parent_id": page.parent_id,
            "ancestors": page.ancestors,
            # Sync metadata
            "indexed_at": datetime.now().isoformat(),
        }

    def delete_page_chunks(self, page_id: str) -> int:
        """Delete all chunks for a page. Returns estimated count deleted."""
        try:
            # Count before deletion
            count_result = self.client.count(
                collection_name=self.config.collection_name,
                count_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="page_id",
                            match=models.MatchValue(value=page_id),
                        )
                    ]
                ),
            )
            count = count_result.count

            if count > 0:
                self.client.delete(
                    collection_name=self.config.collection_name,
                    points_selector=models.FilterSelector(
                        filter=models.Filter(
                            must=[
                                models.FieldCondition(
                                    key="page_id",
                                    match=models.MatchValue(value=page_id),
                                )
                            ]
                        )
                    ),
                    wait=True,
                )
                logger.debug(f"Deleted {count} chunks for page {page_id}")

            return count
        except UnexpectedResponse as e:
            logger.error(f"Failed to delete chunks for page {page_id}: {e}")
            return 0

    def search(
        self,
        query_vector: list[float],
        limit: int = 10,
        space_keys: list[str] | None = None,
        labels: list[str] | None = None,
        chunk_types: list[ChunkType] | None = None,
        score_threshold: float | None = None,
    ) -> list[dict[str, Any]]:
        """
        Search for similar chunks.

        Returns list of dicts with 'id', 'score', and 'payload' keys.
        """
        # Build filter conditions
        must_conditions = []

        if space_keys:
            must_conditions.append(
                models.FieldCondition(
                    key="space_key",
                    match=models.MatchAny(any=space_keys),
                )
            )

        if labels:
            must_conditions.append(
                models.FieldCondition(
                    key="labels",
                    match=models.MatchAny(any=labels),
                )
            )

        if chunk_types:
            must_conditions.append(
                models.FieldCondition(
                    key="chunk_type",
                    match=models.MatchAny(any=[ct.value for ct in chunk_types]),
                )
            )

        query_filter = models.Filter(must=must_conditions) if must_conditions else None

        # Execute search using query_points (new API)
        response = self.client.query_points(
            collection_name=self.config.collection_name,
            query=query_vector,
            limit=limit,
            query_filter=query_filter,
            score_threshold=score_threshold,
            with_payload=True,
        )

        return [
            {
                "id": point.id,
                "score": point.score,
                "payload": point.payload,
            }
            for point in response.points
        ]

    def get_chunk(self, chunk_id: str) -> dict[str, Any] | None:
        """Retrieve a single chunk by ID."""
        try:
            # Convert chunk_id to UUID for Qdrant lookup
            point_id = chunk_id_to_uuid(chunk_id)
            results = self.client.retrieve(
                collection_name=self.config.collection_name,
                ids=[point_id],
                with_payload=True,
            )
            if results:
                point = results[0]
                return {
                    "id": point.id,
                    "payload": point.payload,
                }
        except UnexpectedResponse:
            pass
        return None

    def get_page_chunks(self, page_id: str) -> list[dict[str, Any]]:
        """Retrieve all chunks for a page."""
        results, _ = self.client.scroll(
            collection_name=self.config.collection_name,
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="page_id",
                        match=models.MatchValue(value=page_id),
                    )
                ]
            ),
            limit=1000,  # Assuming pages won't have more than 1000 chunks
            with_payload=True,
        )

        return [
            {
                "id": point.id,
                "payload": point.payload,
            }
            for point in results
        ]

    def get_stats(self) -> dict[str, Any]:
        """Get collection statistics."""
        try:
            info = self.client.get_collection(self.config.collection_name)
            return {
                "collection_name": self.config.collection_name,
                "points_count": info.points_count,
                "status": info.status.value if info.status else "unknown",
            }
        except UnexpectedResponse as e:
            return {"error": str(e)}

    def list_spaces(self) -> list[dict[str, Any]]:
        """List all spaces with their chunk counts."""
        # Use scroll to aggregate by space
        spaces: dict[str, dict[str, Any]] = {}
        offset = None

        while True:
            results, offset = self.client.scroll(
                collection_name=self.config.collection_name,
                limit=1000,
                offset=offset,
                with_payload=["space_key", "page_id"],
            )

            if not results:
                break

            for point in results:
                space_key = point.payload.get("space_key")
                page_id = point.payload.get("page_id")
                if space_key:
                    if space_key not in spaces:
                        spaces[space_key] = {"space_key": space_key, "chunk_count": 0, "page_ids": set()}
                    spaces[space_key]["chunk_count"] += 1
                    if page_id:
                        spaces[space_key]["page_ids"].add(page_id)

            if offset is None:
                break

        # Convert sets to counts
        return [
            {
                "space_key": s["space_key"],
                "chunk_count": s["chunk_count"],
                "page_count": len(s["page_ids"]),
            }
            for s in spaces.values()
        ]

    def get_page_version(self, page_id: str) -> int | None:
        """Get the stored version number for a page.

        Returns None if the page is not in the store.
        Used for incremental sync to skip unchanged pages.
        """
        try:
            results, _ = self.client.scroll(
                collection_name=self.config.collection_name,
                scroll_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="page_id",
                            match=models.MatchValue(value=page_id),
                        )
                    ]
                ),
                limit=1,
                with_payload=["version"],
            )
            if results:
                return results[0].payload.get("version")
        except UnexpectedResponse:
            pass
        return None

    def get_last_indexed_time(self, space_key: str | None = None) -> datetime | None:
        """Get the most recent indexed_at timestamp.

        Args:
            space_key: Optionally filter by space

        Returns:
            The most recent indexed_at datetime, or None if no data exists.
        """
        try:
            filter_conditions = []
            if space_key:
                filter_conditions.append(
                    models.FieldCondition(
                        key="space_key",
                        match=models.MatchValue(value=space_key),
                    )
                )

            query_filter = models.Filter(must=filter_conditions) if filter_conditions else None

            # Scroll through to find max indexed_at
            # Note: Qdrant doesn't support MAX aggregation, so we sample
            results, _ = self.client.scroll(
                collection_name=self.config.collection_name,
                scroll_filter=query_filter,
                limit=100,
                with_payload=["indexed_at"],
            )

            if not results:
                return None

            # Find the most recent timestamp
            max_time = None
            for point in results:
                indexed_at = point.payload.get("indexed_at")
                if indexed_at:
                    try:
                        dt = datetime.fromisoformat(indexed_at.replace("Z", "+00:00"))
                        if max_time is None or dt > max_time:
                            max_time = dt
                    except (ValueError, TypeError):
                        pass

            return max_time
        except UnexpectedResponse:
            return None

    def delete_by_space(self, space_key: str) -> int:
        """Delete all points belonging to a specific space.

        Args:
            space_key: The Confluence space key to delete.

        Returns:
            Number of points deleted (approximate).
        """
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        # Get count before deletion
        spaces = self.list_spaces()
        space_info = next((s for s in spaces if s["space_key"] == space_key), None)
        count = space_info["chunk_count"] if space_info else 0

        # Delete by filter
        self.client.delete(
            collection_name=self.config.collection_name,
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="space_key",
                        match=MatchValue(value=space_key),
                    )
                ]
            ),
        )

        return count

    def close(self) -> None:
        """Close the client connection."""
        if self._client is not None:
            self._client.close()
            self._client = None
