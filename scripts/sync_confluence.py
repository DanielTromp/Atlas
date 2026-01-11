import asyncio
import click
import logging
import sys
import os

# Add src to python path for standalone execution
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

logging.basicConfig(level=logging.INFO)

@click.command()
@click.option('--full', is_flag=True, help='Force full sync')
@click.option('--spaces', '-s', multiple=True, help='Specific spaces to sync')
@click.option('--labels', '-l', multiple=True, help='Filter by labels (default from config)')
@click.option('--no-labels', is_flag=True, help='Disable label filtering (sync all pages)')
@click.option('--ancestor-id', help='Sync only a specific page tree (folder) by parent ID')
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose logging')
def sync(full: bool, spaces: tuple[str], labels: tuple[str], no_labels: bool, ancestor_id: str | None, verbose: bool):
    """Sync Confluence content to RAG cache"""

    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    async def run():
        from infrastructure_atlas.confluence_rag.config import ConfluenceRAGSettings
        from infrastructure_atlas.confluence_rag.database import Database
        from infrastructure_atlas.confluence_rag.confluence_client import ConfluenceClient
        from infrastructure_atlas.confluence_rag.chunker import ConfluenceChunker
        from infrastructure_atlas.confluence_rag.embeddings import EmbeddingPipeline
        from infrastructure_atlas.confluence_rag.sync import ConfluenceSyncEngine

        settings = ConfluenceRAGSettings()

        # Override labels if specified via CLI
        if labels:
            settings.watched_labels = list(labels)
        elif no_labels:
            settings.watched_labels = []

        db = Database(settings.duckdb_path)
        confluence = ConfluenceClient(
            settings.confluence_base_url,
            settings.confluence_username,
            settings.confluence_api_token
        )
        chunker = ConfluenceChunker(max_chunk_tokens=settings.max_chunk_tokens)
        embeddings = EmbeddingPipeline(
            model_name=settings.embedding_model,
            dimensions=settings.embedding_dimensions
        )

        sync_engine = ConfluenceSyncEngine(confluence, db, chunker, embeddings, settings)
        space_list = list(spaces) if spaces else None

        # Show configuration
        click.echo(f"Spaces: {space_list or settings.watched_spaces}")
        click.echo(f"Labels: {settings.watched_labels or '(none - syncing all pages)'}")
        if ancestor_id:
            click.echo(f"Ancestor ID: {ancestor_id}")

        if full:
            click.echo("Starting full sync...")
            await sync_engine.full_sync(space_list, ancestor_id=ancestor_id)
        else:
            click.echo("Starting incremental sync...")
            await sync_engine.incremental_sync(space_list, ancestor_id=ancestor_id)

        await confluence.close()
        click.echo("Sync complete!")
    
    asyncio.run(run())

if __name__ == "__main__":
    sync()
