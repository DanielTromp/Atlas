import asyncio
import logging
import sys
import os

# Add src to python path for standalone execution
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

# Configure logging to stderr to not interfere with MCP stdout protocol
logging.basicConfig(level=logging.INFO, stream=sys.stderr)

def run_mcp():
    """Run the MCP server for Claude integration"""
    # Debug info
    logging.info(f"Python executable: {sys.executable}")
    logging.info(f"Python path: {sys.path}")

    from infrastructure_atlas.confluence_rag.config import ConfluenceRAGSettings
    from infrastructure_atlas.confluence_rag.database import Database
    from infrastructure_atlas.confluence_rag.embeddings import EmbeddingPipeline
    from infrastructure_atlas.confluence_rag.citations import CitationExtractor
    from infrastructure_atlas.confluence_rag.search import HybridSearchEngine
    from infrastructure_atlas.confluence_rag.mcp_server import AtlasConfluenceMCPServer
    
    settings = ConfluenceRAGSettings()
    db = Database(settings.duckdb_path)
    embeddings = EmbeddingPipeline(
        model_name=settings.embedding_model,
        dimensions=settings.embedding_dimensions
    )
    citations = CitationExtractor()
    search_engine = HybridSearchEngine(db, embeddings, citations)
    
    mcp_server = AtlasConfluenceMCPServer(search_engine, db, settings)
    
    asyncio.run(mcp_server.run())

if __name__ == "__main__":
    run_mcp()
