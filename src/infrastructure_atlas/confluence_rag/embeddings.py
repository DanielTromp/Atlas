from sentence_transformers import SentenceTransformer
from infrastructure_atlas.confluence_rag.models import Chunk, ChunkWithEmbedding

class EmbeddingPipeline:
    """
    Local embedding with nomic-embed-text.
    Supports batching and Matryoshka dimension reduction.
    """
    
    def __init__(
        self,
        model_name: str = "nomic-ai/nomic-embed-text-v1.5",
        dimensions: int = 768,
        batch_size: int = 32,
        device: str = "cpu"  # or "cuda" if GPU available
    ):
        self.model = SentenceTransformer(model_name, trust_remote_code=True)
        self.dimensions = dimensions
        self.batch_size = batch_size
        self.device = device
        
        # Matryoshka: truncate to desired dimensions
        # Note: 'truncate_dim' property might depend on the specific model code or sentence-transformers version
        # Nomic generally supports it via argument in encode or attribute
        if dimensions < 768:
             # Some versions/models support this directly
             pass 
    
    def embed_chunks(
        self, 
        chunks: list[Chunk],
        show_progress: bool = True
    ) -> list[ChunkWithEmbedding]:
        """Embed a list of chunks with document prefix"""
        
        # Nomic requires task prefix
        texts = [
            f"search_document: {chunk.heading_context or ''} {chunk.content}"
            for chunk in chunks
        ]
        
        # Check if truncate_dim is supported in this version of ST or via model
        # Using simple encode
        embeddings = self.model.encode(
            texts,
            batch_size=self.batch_size,
            show_progress_bar=show_progress,
            normalize_embeddings=True,  # Cosine similarity
            device=self.device
        )
        
        # Manually truncate if needed (if model doesn't handle it)
        if self.dimensions < 768:
            embeddings = embeddings[:, :self.dimensions]
            # Renormalize after truncation
            import numpy as np
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
        """Embed a search query with query prefix"""
        embeddings = self.model.encode(
            [f"search_query: {query}"],
            normalize_embeddings=True,
            device=self.device
        )
        
        if self.dimensions < 768:
             embeddings = embeddings[:, :self.dimensions]
             # Renormalize
             import numpy as np
             norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
             embeddings = embeddings / norms
             
        return embeddings[0].tolist()
