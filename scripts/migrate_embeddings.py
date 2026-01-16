#!/usr/bin/env python3
"""
Embedding Migration Script

Migrates from one embedding provider to another by:
1. Creating a new Qdrant collection with the new embeddings
2. Re-indexing all content with the new embedding model
3. Optionally switching the default collection

Usage:
    # Step 1: Create new collection with Gemini embeddings (parallel to existing)
    python scripts/migrate_embeddings.py --to gemini --full

    # Step 2: Test the new collection
    python scripts/search_confluence.py --collection confluence_chunks_gemini "your query"

    # Step 3: If satisfied, switch the default (update .env)
    # ATLAS_RAG_EMBEDDING_PROVIDER=gemini
    # ATLAS_RAG_QDRANT_COLLECTION=confluence_chunks_gemini

    # Step 4: Optionally delete the old collection
    python scripts/migrate_embeddings.py --delete-collection confluence_chunks
"""

import asyncio
import logging
import os
import sys

import click

# Add src to python path for standalone execution
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@click.command()
@click.option("--to", "to_provider", required=True, type=click.Choice(["local", "gemini"]),
              help="Target embedding provider")
@click.option("--full", is_flag=True, help="Full re-index (required for migration)")
@click.option("--spaces", "-s", multiple=True, help="Specific spaces to migrate")
@click.option("--collection-name", help="Custom collection name (default: auto-generated)")
@click.option("--delete-collection", help="Delete an existing collection by name")
@click.option("--list-collections", is_flag=True, help="List all Qdrant collections")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
def migrate(
    to_provider: str,
    full: bool,
    spaces: tuple[str],
    collection_name: str | None,
    delete_collection: str | None,
    list_collections: bool,
    verbose: bool,
):
    """Migrate embeddings to a new provider."""

    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    async def run():
        from qdrant_client import QdrantClient

        from infrastructure_atlas.confluence_rag.config import ConfluenceRAGSettings

        settings = ConfluenceRAGSettings()

        # Connect to Qdrant
        client = QdrantClient(
            host=settings.qdrant_host,
            port=settings.qdrant_port,
            prefer_grpc=settings.qdrant_prefer_grpc,
        )

        # List collections mode
        if list_collections:
            collections = client.get_collections().collections
            click.echo("Qdrant Collections:")
            click.echo("-" * 60)
            for col in collections:
                info = client.get_collection(col.name)
                click.echo(f"  {col.name}")
                click.echo(f"    Vectors: {info.points_count}")
                click.echo(f"    Status:  {info.status}")
                click.echo(f"    Size:    {info.vectors_count} dimensions")
            return

        # Delete collection mode
        if delete_collection:
            if click.confirm(f"Delete collection '{delete_collection}'? This cannot be undone!"):
                try:
                    client.delete_collection(delete_collection)
                    click.echo(f"Deleted collection: {delete_collection}")
                except Exception as e:
                    click.echo(f"Error: {e}", err=True)
            return

        # Migration mode - require --full
        if not full:
            click.echo("Migration requires --full flag to re-index all content.", err=True)
            click.echo("Run: python scripts/migrate_embeddings.py --to gemini --full")
            sys.exit(1)

        # Determine target collection name
        target_collection = collection_name or f"{settings.qdrant_collection}_{to_provider}"

        click.echo("=" * 60)
        click.echo("EMBEDDING MIGRATION")
        click.echo("=" * 60)
        click.echo(f"Target provider:    {to_provider}")
        click.echo(f"Target collection:  {target_collection}")
        click.echo(f"Source collection:  {settings.qdrant_collection}")
        click.echo("=" * 60)

        # Check if target collection already exists
        existing = [c.name for c in client.get_collections().collections]
        if target_collection in existing:
            info = client.get_collection(target_collection)
            if info.points_count > 0:
                if not click.confirm(
                    f"Collection '{target_collection}' exists with {info.points_count} vectors. "
                    f"Continue and overwrite?"
                ):
                    return

        click.echo("")
        click.echo("Starting migration...")
        click.echo("This will create a NEW collection alongside your existing one.")
        click.echo("Your current data is safe until you switch the default.")
        click.echo("")

        # Import and run sync with the new provider
        from infrastructure_atlas.confluence_rag.chunker import ConfluenceChunker
        from infrastructure_atlas.confluence_rag.confluence_client import ConfluenceClient
        from infrastructure_atlas.confluence_rag.embeddings import get_embedding_pipeline
        from infrastructure_atlas.confluence_rag.qdrant_store import QdrantConfig, QdrantStore
        from infrastructure_atlas.confluence_rag.qdrant_sync import QdrantSyncEngine

        # Get embedding pipeline for target provider
        embeddings = get_embedding_pipeline(provider=to_provider)
        click.echo(f"Embedding model: {to_provider} ({embeddings.dimensions}D)")

        # Create Qdrant store for new collection
        qdrant_config = QdrantConfig(
            host=settings.qdrant_host,
            port=settings.qdrant_port,
            grpc_port=settings.qdrant_grpc_port,
            prefer_grpc=settings.qdrant_prefer_grpc,
            api_key=settings.qdrant_api_key,
            collection_name=target_collection,
            vector_size=embeddings.dimensions,
        )
        qdrant_store = QdrantStore(config=qdrant_config)

        # Initialize sync components
        confluence = ConfluenceClient(
            settings.confluence_base_url,
            settings.confluence_username,
            settings.confluence_api_token,
        )
        chunker = ConfluenceChunker(max_chunk_tokens=settings.max_chunk_tokens)

        sync_engine = QdrantSyncEngine(
            confluence, qdrant_store, chunker, embeddings, settings
        )

        # Run full sync
        space_list = list(spaces) if spaces else None
        stats = await sync_engine.full_sync(space_list)

        await confluence.close()

        # Summary
        click.echo("")
        click.echo("=" * 60)
        click.echo("MIGRATION COMPLETE")
        click.echo("=" * 60)
        click.echo(f"Pages processed: {stats.pages_processed}")
        click.echo(f"Pages skipped:   {stats.pages_skipped}")
        click.echo(f"Pages failed:    {stats.pages_failed}")
        click.echo(f"Chunks created:  {stats.chunks_created}")
        click.echo(f"Duration:        {stats.duration_seconds:.1f}s")
        click.echo("=" * 60)

        # Final stats
        final_stats = qdrant_store.get_stats()
        click.echo(f"\nNew collection '{target_collection}': {final_stats.get('points_count', 0)} vectors")

        click.echo("")
        click.echo("NEXT STEPS:")
        click.echo("-" * 60)
        click.echo("1. Test the new collection:")
        click.echo(f"   python scripts/search_confluence.py --collection {target_collection} 'test query'")
        click.echo("")
        click.echo("2. If satisfied, update .env to use new embeddings:")
        click.echo(f"   ATLAS_RAG_EMBEDDING_PROVIDER={to_provider}")
        click.echo(f"   ATLAS_RAG_QDRANT_COLLECTION={target_collection}")
        click.echo("")
        click.echo("3. Optionally delete the old collection:")
        click.echo(f"   python scripts/migrate_embeddings.py --delete-collection {settings.qdrant_collection}")

    asyncio.run(run())


if __name__ == "__main__":
    migrate()
