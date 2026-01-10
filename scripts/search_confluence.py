import asyncio
import click
import logging
import sys
import os

# Add src to python path for standalone execution
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

# Configure logging
logging.basicConfig(level=logging.WARNING)

@click.command()
@click.argument('query')
@click.option('--limit', '-n', default=3, help='Number of results to return')
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose logging')
def search(query: str, limit: int, verbose: bool):
    """Search Confluence RAG knowledge base"""
    
    if verbose:
        logging.getLogger().setLevel(logging.INFO)
    
    async def run():
        from infrastructure_atlas.confluence_rag.config import ConfluenceRAGSettings
        from infrastructure_atlas.confluence_rag.database import Database
        from infrastructure_atlas.confluence_rag.embeddings import EmbeddingPipeline
        from infrastructure_atlas.confluence_rag.citations import CitationExtractor
        from infrastructure_atlas.confluence_rag.search import HybridSearchEngine, SearchConfig
        
        settings = ConfluenceRAGSettings()
        db = Database(settings.duckdb_path)
        
        click.echo("Loading models... (this may take a moment)")
        embeddings = EmbeddingPipeline(
            model_name=settings.embedding_model,
            dimensions=settings.embedding_dimensions
        )
        citations = CitationExtractor()
        search_engine = HybridSearchEngine(db, embeddings, citations)
        
        click.echo(f"Searching for: '{query}'...")
        
        config = SearchConfig(top_k=limit, include_citations=True)
        response = await search_engine.search(query, config)
        
        click.echo(f"\nFound {response.total_results} results in {response.search_time_ms:.0f}ms\n")
        
        for i, result in enumerate(response.results, 1):
            click.echo("=" * 60)
            click.echo(f"{i}. {result.page.title}")
            click.echo(f"   Space: {result.page.space_key}")
            click.echo(f"   Score: {result.relevance_score:.2%}")
            click.echo("-" * 60)
            
            # Print citations if available
            if result.citations:
                for citation in result.citations:
                    click.echo(f"> \"{citation.quote}\"")
                    click.echo(f"  (Confidence: {citation.confidence_score:.0%})")
                    click.echo("")
            else:
                # Fallback to content snippet
                snippet = result.content[:200].replace('\n', ' ')
                click.echo(f"{snippet}...")
            
            click.echo(f"\n   URL: {result.page.url}")
            click.echo("\n")

    asyncio.run(run())

if __name__ == "__main__":
    search()
