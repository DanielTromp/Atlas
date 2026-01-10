import click
import sys
import os

# Add src to python path for standalone execution
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

@click.command()
@click.option('--db-path', default=None, help='Database path')
def init_db(db_path: str | None):
    """Initialize the RAG database schema"""
    # Import inside function to avoid heavy imports during CLI parsing if possible,
    # but for scripts it's fine.
    from infrastructure_atlas.confluence_rag.database import Database
    from infrastructure_atlas.confluence_rag.config import ConfluenceRAGSettings
    
    # If path not provided, use default from settings (by passing None to Database)
    # But Database ctor handles None.
    
    click.echo(f"Initializing database...")
    try:
        db = Database(db_path)
        db.connect()
        click.echo(f"Database initialized successfully at {db.db_path}!")
    except Exception as e:
        click.echo(f"Failed to initialize database: {e}", err=True)

if __name__ == "__main__":
    init_db()
