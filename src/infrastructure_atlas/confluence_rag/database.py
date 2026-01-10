import duckdb
from pathlib import Path
from infrastructure_atlas.confluence_rag.config import ConfluenceRAGSettings

SCHEMA_SETUP_STMTS = [
    # Install VSS extension
    "INSTALL vss;",
    "LOAD vss;",

    # Pages metadata
    """
    CREATE TABLE IF NOT EXISTS pages (
        page_id VARCHAR PRIMARY KEY,
        space_key VARCHAR NOT NULL,
        title VARCHAR NOT NULL,
        url VARCHAR NOT NULL,
        labels VARCHAR[],
        version INTEGER,
        updated_at TIMESTAMP,
        updated_by VARCHAR,
        parent_id VARCHAR,
        ancestors VARCHAR[],
        synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        raw_content TEXT
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_pages_space ON pages (space_key);",
    "CREATE INDEX IF NOT EXISTS idx_pages_updated ON pages (updated_at);",

    # Chunks with original content for quotes
    """
    CREATE TABLE IF NOT EXISTS chunks (
        chunk_id VARCHAR PRIMARY KEY,
        page_id VARCHAR NOT NULL REFERENCES pages(page_id),
        content TEXT NOT NULL,
        original_content TEXT NOT NULL,
        context_path VARCHAR[],
        chunk_type VARCHAR,
        token_count INTEGER,
        position_in_page INTEGER,
        heading_context VARCHAR,
        text_span_start INTEGER,
        text_span_end INTEGER,
        metadata JSON,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_chunks_page ON chunks (page_id);",
    "CREATE INDEX IF NOT EXISTS idx_chunks_type ON chunks (chunk_type);",

    # Vector embeddings
    """
    CREATE TABLE IF NOT EXISTS chunk_embeddings (
        chunk_id VARCHAR PRIMARY KEY,
        embedding FLOAT[768],
        model_version VARCHAR,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """,
    
    # HNSW index for vector search
    """
    CREATE INDEX IF NOT EXISTS idx_chunk_embeddings_hnsw 
    ON chunk_embeddings 
    USING HNSW (embedding)
    WITH (metric = 'cosine');
    """,

    # Full-text search index (DuckDB FTS)
    # Note: FTS index creation might fail if table empty or repeated, handling in loop
    "PRAGMA create_fts_index('chunks', 'chunk_id', 'content', 'heading_context');",

    # Sync state tracking
    """
    CREATE TABLE IF NOT EXISTS sync_state (
        space_key VARCHAR PRIMARY KEY,
        last_sync_at TIMESTAMP,
        last_page_count INTEGER,
        last_chunk_count INTEGER,
        status VARCHAR,
        error_message VARCHAR
    );
    """,

    # Query cache for frequently used searches
    """
    CREATE TABLE IF NOT EXISTS search_cache (
        query_hash VARCHAR PRIMARY KEY,
        query_text VARCHAR,
        results JSON,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        hit_count INTEGER DEFAULT 0
    );
    """
]

class Database:
    def __init__(self, db_path: str | None = None):
        if db_path is None:
            settings = ConfluenceRAGSettings()
            db_path = settings.duckdb_path
            
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = None
    
    def connect(self) -> duckdb.DuckDBPyConnection:
        if self.conn is None:
            # Connect to DuckDB with experimental HNSW persistence enabled
            self.conn = duckdb.connect(
                str(self.db_path),
                config={'hnsw_enable_experimental_persistence': 'true'}
            )
            self._init_schema()
        return self.conn
    
    def _init_schema(self):
        for stmt in SCHEMA_SETUP_STMTS:
            try:
                self.conn.execute(stmt)
            except Exception as e:
                # FTS index repeated creation might fail gracefully or if vss not available
                # Logging would be good but silently passing for robust init unless critical
                # But we should raise for critical table fails
                if "create_fts_index" in stmt:
                    continue # Ignore FTS index recreation issues
                # Assume other errors are fatal for first run
                # But allow re-run if tables exist
                # SCHEMA_SETUP_STMTS uses IF NOT EXISTS so should be fine
                raise e
