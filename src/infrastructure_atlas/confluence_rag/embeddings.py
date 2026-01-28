"""
Embedding pipelines for Confluence RAG.

Supports multiple embedding providers:
- Local: Nomic embed (requires model download, runs on CPU/GPU)
- Gemini: Google's gemini-embedding-001 (API-based, free tier available)
"""

import logging
import os
from abc import ABC, abstractmethod

from infrastructure_atlas.confluence_rag.models import Chunk, ChunkWithEmbedding

logger = logging.getLogger(__name__)


class BaseEmbeddingPipeline(ABC):
    """Abstract base class for embedding pipelines."""

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Return the embedding dimensions."""
        pass

    @abstractmethod
    def embed_chunks(
        self,
        chunks: list[Chunk],
        show_progress: bool = True
    ) -> list[ChunkWithEmbedding]:
        """Embed a list of chunks."""
        pass

    @abstractmethod
    def embed_query(self, query: str) -> list[float]:
        """Embed a search query."""
        pass


class LocalEmbeddingPipeline(BaseEmbeddingPipeline):
    """
    Local embedding with nomic-embed-text.
    Supports batching and Matryoshka dimension reduction.
    """

    def __init__(
        self,
        model_name: str = "nomic-ai/nomic-embed-text-v1.5",
        dimensions: int = 768,
        batch_size: int = 32,
        device: str = "cpu"
    ):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name, trust_remote_code=True)
        self._dimensions = dimensions
        self.batch_size = batch_size
        self.device = device
        logger.info(f"Initialized local embedding pipeline: {model_name} ({dimensions}D)")

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed_chunks(
        self,
        chunks: list[Chunk],
        show_progress: bool = True
    ) -> list[ChunkWithEmbedding]:
        """Embed a list of chunks with document prefix."""
        import numpy as np

        # Nomic requires task prefix
        texts = [
            f"search_document: {chunk.heading_context or ''} {chunk.content}"
            for chunk in chunks
        ]

        embeddings = self.model.encode(
            texts,
            batch_size=self.batch_size,
            show_progress_bar=show_progress,
            normalize_embeddings=True,
            device=self.device
        )

        # Manually truncate if needed (Matryoshka)
        if self._dimensions < 768:
            embeddings = embeddings[:, :self._dimensions]
            norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
            embeddings = embeddings / norms

        return [
            ChunkWithEmbedding(
                **chunk.model_dump(),
                embedding=emb.tolist()
            )
            for chunk, emb in zip(chunks, embeddings)
        ]

    def embed_query(self, query: str) -> list[float]:
        """Embed a search query with query prefix."""
        import numpy as np

        embeddings = self.model.encode(
            [f"search_query: {query}"],
            normalize_embeddings=True,
            device=self.device
        )

        if self._dimensions < 768:
            embeddings = embeddings[:, :self._dimensions]
            norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
            embeddings = embeddings / norms

        return embeddings[0].tolist()


class GeminiEmbeddingPipeline(BaseEmbeddingPipeline):
    """
    Google Gemini embedding pipeline.

    Uses the Gemini API for embeddings. Supports:
    - gemini-embedding-001: FREE tier, 768-3072 dimensions, excellent multilingual

    Note: text-embedding-004 was deprecated on Jan 14, 2026.
    Uses the new google.genai SDK (replaces deprecated google.generativeai).
    """

    # Gemini embedding dimensions by model
    # Note: gemini-embedding-001 supports 768, 1536, or 3072 dimensions via MRL
    # We default to 768 for compatibility with existing Qdrant collections
    MODEL_DIMENSIONS = {
        "gemini-embedding-001": 768,
        "text-embedding-004": 768,  # deprecated Jan 14, 2026
    }

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str = "gemini-embedding-001",
        batch_size: int = 100,  # Gemini supports up to 100 texts per request
    ):
        from google import genai

        self.api_key = api_key or os.environ.get("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError(
                "GOOGLE_API_KEY is required for Gemini embeddings. "
                "Get one at: https://aistudio.google.com/apikey"
            )

        # New SDK uses Client instead of configure()
        self._client = genai.Client(api_key=self.api_key)
        self.model_name = model_name
        self.batch_size = batch_size
        self._dimensions = self.MODEL_DIMENSIONS.get(model_name, 768)

        logger.info(f"Initialized Gemini embedding pipeline: {model_name} ({self._dimensions}D)")

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def _embed_batch(
        self,
        texts: list[str],
        task_type: str = "RETRIEVAL_DOCUMENT"
    ) -> list[list[float]]:
        """Embed a batch of texts using Gemini API."""
        from google.genai import types

        # Embed each text individually to avoid complex batch response parsing
        results = []
        for text in texts:
            response = self._client.models.embed_content(
                model=f"models/{self.model_name}",
                contents=[text],
                config=types.EmbedContentConfig(
                    task_type=task_type,
                    output_dimensionality=self._dimensions,  # MRL: output 768 dims for compatibility
                ),
            )
            # New SDK returns response.embeddings list
            emb = response.embeddings[0].values
            results.append([float(x) for x in emb])

        return results

    def embed_chunks(
        self,
        chunks: list[Chunk],
        show_progress: bool = True
    ) -> list[ChunkWithEmbedding]:
        """Embed a list of chunks using Gemini API."""
        from tqdm import tqdm

        texts = [
            f"{chunk.heading_context or ''} {chunk.content}".strip()
            for chunk in chunks
        ]

        all_embeddings = []

        # Process in batches
        batches = [
            texts[i:i + self.batch_size]
            for i in range(0, len(texts), self.batch_size)
        ]

        iterator = tqdm(batches, desc="Embedding chunks") if show_progress else batches

        for batch in iterator:
            batch_embeddings = self._embed_batch(batch, task_type="RETRIEVAL_DOCUMENT")
            all_embeddings.extend(batch_embeddings)

        return [
            ChunkWithEmbedding(
                **chunk.model_dump(),
                embedding=emb
            )
            for chunk, emb in zip(chunks, all_embeddings)
        ]

    def embed_query(self, query: str) -> list[float]:
        """Embed a search query using Gemini API."""
        embeddings = self._embed_batch([query], task_type="RETRIEVAL_QUERY")
        return embeddings[0]


def get_embedding_pipeline(
    provider: str | None = None,
    **kwargs
) -> BaseEmbeddingPipeline:
    """
    Factory function to get the appropriate embedding pipeline.

    Args:
        provider: "local" for Nomic, "gemini" for Google Gemini API.
                  If None, reads from ATLAS_RAG_EMBEDDING_PROVIDER env var.
        **kwargs: Additional arguments passed to the pipeline constructor.

    Returns:
        Configured embedding pipeline instance.
    """
    if provider is None:
        provider = os.environ.get("ATLAS_RAG_EMBEDDING_PROVIDER", "local")

    provider = provider.lower()

    if provider == "gemini":
        model = kwargs.pop("model_name", None) or os.environ.get(
            "ATLAS_RAG_GEMINI_MODEL", "gemini-embedding-001"
        )
        return GeminiEmbeddingPipeline(model_name=model, **kwargs)

    elif provider == "local":
        return LocalEmbeddingPipeline(**kwargs)

    else:
        raise ValueError(
            f"Unknown embedding provider: {provider}. "
            "Supported: 'local' (Nomic), 'gemini' (Google)"
        )


# Backwards compatibility alias
EmbeddingPipeline = LocalEmbeddingPipeline
