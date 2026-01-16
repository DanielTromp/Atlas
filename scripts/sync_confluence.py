#!/usr/bin/env python3
"""
Confluence RAG Sync Script

Syncs Confluence content to Qdrant vector store for semantic search.
"""

import asyncio
import logging
import os
import sys

import click

# Add src to python path for standalone execution
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

logging.basicConfig(level=logging.INFO)


@click.command()
@click.option("--full", is_flag=True, help="Force full sync (re-process all pages)")
@click.option("--spaces", "-s", multiple=True, help="Specific spaces to sync")
@click.option("--labels", "-l", multiple=True, help="Filter by labels (default from config)")
@click.option("--no-labels", is_flag=True, help="Disable label filtering (sync all pages)")
@click.option("--ancestor-id", help="Sync only a specific page tree (folder) by parent ID")
@click.option("--provider", "-p", type=click.Choice(["local", "gemini"]), help="Embedding provider (default from config)")
@click.option("--collection-suffix", help="Suffix for Qdrant collection name (e.g., 'gemini' creates confluence_chunks_gemini)")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def sync(
    full: bool,
    spaces: tuple[str],
    labels: tuple[str],
    no_labels: bool,
    ancestor_id: str | None,
    provider: str | None,
    collection_suffix: str | None,
    verbose: bool,
):
    """Sync Confluence content to Qdrant vector store."""

    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    async def run():
        from infrastructure_atlas.confluence_rag.chunker import ConfluenceChunker
        from infrastructure_atlas.confluence_rag.config import ConfluenceRAGSettings
        from infrastructure_atlas.confluence_rag.confluence_client import ConfluenceClient
        from infrastructure_atlas.confluence_rag.embeddings import get_embedding_pipeline
        from infrastructure_atlas.confluence_rag.qdrant_store import QdrantConfig, QdrantStore
        from infrastructure_atlas.confluence_rag.qdrant_sync import QdrantSyncEngine

        settings = ConfluenceRAGSettings()

        # Override labels if specified via CLI
        if labels:
            settings.watched_labels = list(labels)
        elif no_labels:
            settings.watched_labels = []

        # Determine embedding provider
        embed_provider = provider or settings.embedding_provider
        click.echo(f"Embedding provider: {embed_provider}")

        # Get embedding pipeline (will use env vars for config)
        embeddings = get_embedding_pipeline(provider=embed_provider)
        embed_dimensions = embeddings.dimensions
        click.echo(f"Embedding dimensions: {embed_dimensions}")

        # Determine collection name (allows parallel collections for migration)
        collection_name = settings.get_collection_name(collection_suffix)

        # Initialize Qdrant store with custom config
        click.echo(f"Connecting to Qdrant at {settings.qdrant_host}:{settings.qdrant_port}...")
        qdrant_config = QdrantConfig(
            host=settings.qdrant_host,
            port=settings.qdrant_port,
            grpc_port=settings.qdrant_grpc_port,
            prefer_grpc=settings.qdrant_prefer_grpc,
            api_key=settings.qdrant_api_key,
            collection_name=collection_name,
            vector_size=embed_dimensions,
        )
        qdrant_store = QdrantStore(config=qdrant_config)

        # Verify Qdrant connection
        stats = qdrant_store.get_stats()
        if "error" in stats:
            click.echo(f"Error connecting to Qdrant: {stats['error']}", err=True)
            click.echo("Make sure Qdrant is running: docker compose up -d", err=True)
            sys.exit(1)

        click.echo(f"Qdrant collection: {stats.get('collection_name')} ({stats.get('points_count', 0)} vectors)")

        # Initialize other components
        confluence = ConfluenceClient(
            settings.confluence_base_url,
            settings.confluence_username,
            settings.confluence_api_token,
        )
        chunker = ConfluenceChunker(max_chunk_tokens=settings.max_chunk_tokens)

        sync_engine = QdrantSyncEngine(confluence, qdrant_store, chunker, embeddings, settings)
        space_list = list(spaces) if spaces else None

        # Show configuration
        click.echo(f"Spaces: {space_list or settings.watched_spaces}")
        click.echo(f"Labels: {settings.watched_labels or '(none - syncing all pages)'}")
        if ancestor_id:
            click.echo(f"Ancestor ID: {ancestor_id}")
        click.echo("")

        if full:
            click.echo("Starting full sync...")
            stats = await sync_engine.full_sync(space_list, ancestor_id=ancestor_id)
        else:
            click.echo("Starting incremental sync...")
            stats = await sync_engine.incremental_sync(space_list, ancestor_id=ancestor_id)

        await confluence.close()

        # Print summary
        click.echo("")
        click.echo("=" * 60)
        click.echo("Sync Complete!")
        click.echo(f"  Pages processed: {stats.pages_processed}")
        click.echo(f"  Pages skipped:   {stats.pages_skipped}")
        click.echo(f"  Pages failed:    {stats.pages_failed}")
        click.echo(f"  Chunks created:  {stats.chunks_created}")
        click.echo(f"  Duration:        {stats.duration_seconds:.1f}s")
        click.echo("=" * 60)

        # Show final Qdrant stats
        final_stats = qdrant_store.get_stats()
        click.echo(f"\nQdrant total vectors: {final_stats.get('points_count', 0)}")

    asyncio.run(run())


if __name__ == "__main__":
    sync()
