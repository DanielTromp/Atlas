from typing import Literal

from pydantic_settings import BaseSettings


class ConfluenceRAGSettings(BaseSettings):
    # Confluence
    confluence_base_url: str  # https://company.atlassian.net/wiki
    confluence_username: str
    confluence_api_token: str

    # Sync settings
    watched_spaces: list[str] = ["INFRA", "SE", "RUNBOOKS"]
    watched_labels: list[str] = ["procedure", "how-to", "troubleshooting", "runbook"]
    sync_interval_minutes: int = 60

    # Chunking
    max_chunk_tokens: int = 512
    chunk_overlap_tokens: int = 50

    # Embedding provider: "gemini" (Google API) or "local" (Nomic)
    embedding_provider: Literal["local", "gemini"] = "gemini"

    # Local embedding settings (Nomic)
    embedding_model: str = "nomic-ai/nomic-embed-text-v1.5"
    embedding_dimensions: int = 768  # Can be lower for Matryoshka

    # Gemini embedding settings (text-embedding-004 deprecated Jan 14, 2026)
    gemini_model: str = "gemini-embedding-001"

    # Vector Store Backend: "qdrant" or "duckdb" (deprecated)
    vector_store: str = "qdrant"

    # Qdrant settings
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_grpc_port: int = 6334
    qdrant_prefer_grpc: bool = True
    qdrant_api_key: str | None = None
    qdrant_collection: str = "confluence_chunks"

    # DuckDB (deprecated - kept for migration)
    duckdb_path: str = "data/atlas_confluence_rag.duckdb"

    # MCP
    mcp_server_name: str = "atlas-confluence"
    mcp_server_port: int = 8765

    class Config:
        env_prefix = "ATLAS_RAG_"
        env_file = ".env"
        extra = "ignore"

    def get_collection_name(self, suffix: str | None = None) -> str:
        """
        Get the Qdrant collection name, optionally with a suffix.

        Useful for creating separate collections for different embedding models
        during migration (e.g., "confluence_chunks_gemini").
        """
        if suffix:
            return f"{self.qdrant_collection}_{suffix}"
        return self.qdrant_collection
