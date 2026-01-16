#!/usr/bin/env python3
"""
Confluence RAG Search Script

Searches the Qdrant vector store for relevant documentation.
"""

import asyncio
import logging
import os
import sys

import click

# Add src to python path for standalone execution
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

# Configure logging
logging.basicConfig(level=logging.WARNING)


@click.command()
@click.argument("query")
@click.option("--limit", "-n", default=10, help="Number of results to return")
@click.option("--spaces", "-s", multiple=True, help="Filter by space keys")
@click.option("--collection", "-c", help="Qdrant collection name (for testing migrations)")
@click.option("--provider", "-p", type=click.Choice(["local", "gemini"]), help="Embedding provider")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def search(query: str, limit: int, spaces: tuple[str], collection: str | None, provider: str | None, verbose: bool):
    """Search Confluence RAG knowledge base (Qdrant)."""

    if verbose:
        logging.getLogger().setLevel(logging.INFO)

    async def run():
        from infrastructure_atlas.confluence_rag.citations import CitationExtractor
        from infrastructure_atlas.confluence_rag.config import ConfluenceRAGSettings
        from infrastructure_atlas.confluence_rag.embeddings import get_embedding_pipeline
        from infrastructure_atlas.confluence_rag.qdrant_search import (
            QdrantSearchEngine,
            SearchConfig,
        )
        from infrastructure_atlas.confluence_rag.qdrant_store import QdrantConfig, QdrantStore

        settings = ConfluenceRAGSettings()

        # Determine embedding provider
        embed_provider = provider or settings.embedding_provider

        # Get embedding pipeline
        embeddings = get_embedding_pipeline(provider=embed_provider)

        # Determine collection name
        collection_name = collection or settings.qdrant_collection

        # Connect to Qdrant with custom config
        click.echo(f"Connecting to Qdrant at {settings.qdrant_host}:{settings.qdrant_port}...")
        qdrant_config = QdrantConfig(
            host=settings.qdrant_host,
            port=settings.qdrant_port,
            grpc_port=settings.qdrant_grpc_port,
            prefer_grpc=settings.qdrant_prefer_grpc,
            api_key=settings.qdrant_api_key,
            collection_name=collection_name,
            vector_size=embeddings.dimensions,
        )
        store = QdrantStore(config=qdrant_config)

        # Verify connection
        stats = store.get_stats()
        if "error" in stats:
            click.echo(f"Error: {stats['error']}", err=True)
            click.echo("Make sure Qdrant is running: docker compose up -d", err=True)
            sys.exit(1)

        vector_count = stats.get("points_count", 0)
        if vector_count == 0:
            click.echo("Warning: Qdrant collection is empty. Run sync first:", err=True)
            click.echo("  uv run python scripts/sync_confluence.py --full -s SPACE", err=True)
            sys.exit(1)

        click.echo(f"Collection: {collection_name} ({vector_count} vectors)")
        click.echo(f"Provider: {embed_provider} ({embeddings.dimensions}D)")
        citations = CitationExtractor()
        search_engine = QdrantSearchEngine(store, embeddings, citations)

        click.echo(f"Searching for: '{query}'...")

        config = SearchConfig(
            top_k=limit,
            include_citations=True,
            space_keys=list(spaces) if spaces else None,
        )
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
                    click.echo(f'> "{citation.quote}"')
                    click.echo(f"  (Confidence: {citation.confidence_score:.0%})")
                    click.echo("")
            else:
                # Fallback to content snippet
                snippet = result.content[:200].replace("\n", " ")
                click.echo(f"{snippet}...")

            click.echo(f"\n   URL: {result.page.url}")
            click.echo("\n")

    asyncio.run(run())


if __name__ == "__main__":
    search()
