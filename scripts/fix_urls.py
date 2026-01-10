import duckdb
from infrastructure_atlas.confluence_rag.config import ConfluenceRAGSettings

def fix_urls():
    settings = ConfluenceRAGSettings()
    conn = duckdb.connect(settings.duckdb_path)
    
    print("Fixing URLs in database...")
    
    # Check for broken URLs
    count = conn.execute("SELECT COUNT(*) FROM pages WHERE url LIKE '%.atlassian.n/wiki%'").fetchone()[0]
    print(f"Found {count} pages with broken URLs.")
    
    if count > 0:
        conn.execute("""
            UPDATE pages 
            SET url = replace(url, '.atlassian.n/wiki', '.atlassian.net/wiki')
            WHERE url LIKE '%.atlassian.n/wiki%'
        """)
        print("URLs updated successfully.")
    
    # Verify
    check = conn.execute("SELECT url FROM pages LIMIT 1").fetchone()
    if check:
        print(f"Sample URL: {check[0]}")

if __name__ == "__main__":
    fix_urls()
