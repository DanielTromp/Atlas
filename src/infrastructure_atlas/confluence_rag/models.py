from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum

class ChunkType(str, Enum):
    PROSE = "prose"
    CODE = "code"
    TABLE = "table"
    LIST = "list"
    HEADING = "heading"

class ConfluencePage(BaseModel):
    """Metadata of a Confluence page"""
    page_id: str
    space_key: str
    title: str
    url: str
    labels: list[str]
    version: int
    updated_at: datetime
    updated_by: str
    parent_id: str | None = None
    ancestors: list[str] = Field(default_factory=list)  # Breadcrumb trail

class TextSpan(BaseModel):
    """Exact location of text in source document"""
    start_char: int
    end_char: int
    original_text: str  # Exact original text for quotes

class Chunk(BaseModel):
    """A chunk of content with full traceability"""
    chunk_id: str
    page_id: str
    content: str                    # Processed/normalized content for search
    original_content: str           # Exact original text for quotes
    context_path: list[str]         # ["Space", "Parent Page", "Section"]
    chunk_type: ChunkType
    token_count: int
    position_in_page: int           # Order in document
    text_spans: list[TextSpan]      # Exact locations in source
    heading_context: str | None     # Last heading above this chunk
    metadata: dict = Field(default_factory=dict)

class ChunkWithEmbedding(Chunk):
    """Chunk with embedding vector"""
    embedding: list[float]

class Citation(BaseModel):
    """Citation with full reference"""
    quote: str                      # Exact text from document
    page_title: str
    page_url: str
    space_key: str
    section: str | None             # Heading/section where quote comes from
    context_before: str             # ~50 chars context before quote
    context_after: str              # ~50 chars context after quote
    chunk_id: str
    confidence_score: float         # How relevant is this quote

class SearchResult(BaseModel):
    """Search result with citations"""
    chunk_id: str
    content: str
    relevance_score: float
    citations: list[Citation]
    page: ConfluencePage
    context_path: list[str]

class SearchResponse(BaseModel):
    """Complete search response"""
    query: str
    results: list[SearchResult]
    total_results: int
    search_time_ms: float
