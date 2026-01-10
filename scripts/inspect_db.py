import duckdb
import click
from pathlib import Path
from infrastructure_atlas.confluence_rag.config import ConfluenceRAGSettings

@click.command()
@click.option('--limit', '-n', default=20, help='Number of pages to list')
def inspect(limit: int):
    """List pages currently in the RAG database"""
    settings = ConfluenceRAGSettings()
    db_path = settings.duckdb_path
    
    if not Path(db_path).exists():
        click.echo(f"Database not found at {db_path}", err=True)
        return

    conn = duckdb.connect(db_path, read_only=True)
    
    try:
        # Get count
        count = conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
        click.echo(f"Total Pages in Database: {count}")
        click.echo("-" * 40)
        
        # Get pages with chunk counts
        pages = conn.execute(f"""
            SELECT 
                p.title, 
                p.page_id, 
                p.space_key,
                (SELECT COUNT(*) FROM chunks c WHERE c.page_id = p.page_id) as chunk_count,
                (SELECT COUNT(*) FROM chunk_embeddings ce JOIN chunks c ON ce.chunk_id = c.chunk_id WHERE c.page_id = p.page_id) as emb_count
            FROM pages p
            ORDER BY p.title 
            LIMIT {limit}
        """).fetchall()
        
        if not pages:
            click.echo("No pages found.")
        
        for p in pages:
            click.echo(f"[{p[2]}] {p[0]} (ID: {p[1]}) - Chunks: {p[3]}, Embeddings: {p[4]}")
            
        if count > limit:
            click.echo(f"... and {count - limit} more.")
            
    except Exception as e:
        click.echo(f"Error reading database: {e}", err=True)

if __name__ == "__main__":
    inspect()
