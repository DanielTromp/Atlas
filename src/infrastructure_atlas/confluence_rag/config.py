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
    
    # Embedding
    embedding_model: str = "nomic-ai/nomic-embed-text-v1.5"
    embedding_dimensions: int = 768  # Can be lower for Matryoshka
    
    # Database
    duckdb_path: str = "data/atlas_confluence_rag.duckdb"
    
    # MCP
    mcp_server_name: str = "atlas-confluence"
    mcp_server_port: int = 8765
    
    class Config:
        env_prefix = "ATLAS_RAG_"
        env_file = ".env"
        extra = "ignore"
