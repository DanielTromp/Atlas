from mcp.server.fastmcp import FastMCP
import asyncio

from infrastructure_atlas.confluence_rag.search import HybridSearchEngine, SearchConfig, SearchResponse
from infrastructure_atlas.confluence_rag.database import Database
from infrastructure_atlas.confluence_rag.config import ConfluenceRAGSettings

class AtlasConfluenceMCPServer:
    """
    MCP Server for Confluence RAG access from Claude.
    Uses FastMCP for simplified tool registration.
    """
    
    def __init__(
        self,
        search_engine: HybridSearchEngine,
        db: Database,
        settings: ConfluenceRAGSettings
    ):
        self.search = search_engine
        self.db = db
        self.settings = settings
        self.server = FastMCP(settings.mcp_server_name)
        
        self._register_tools()
    
    def _register_tools(self):
        """Register MCP tools"""
        
        @self.server.tool()
        async def search_confluence_docs(
            query: str,
            top_k: int = 5,
            include_citations: bool = True,
            spaces: list[str] | None = None
        ) -> str:
            """
            Search Confluence documentation with semantic search.
            
            Returns relevant passages with exact citations and source references.
            Use this for finding procedures, troubleshooting guides,
            and technical documentation.
            """
            config = SearchConfig(
                top_k=top_k,
                include_citations=include_citations
            )
            
            response = await self.search.search(query, config)
            
            # Format for Claude-friendly output
            return self._format_search_results(response)
        
        @self.server.tool()
        async def get_confluence_page(
            page_id: str | None = None,
            page_title: str | None = None,
            space_key: str | None = None
        ) -> str:
            """
            Retrieve a specific Confluence page.
            Provide either page_id OR (page_title + space_key).
            """
            conn = self.db.connect()
            
            if page_id:
                page = conn.execute(
                    "SELECT * FROM pages WHERE page_id = $1",
                    [page_id]
                ).fetchone()
            elif page_title and space_key:
                page = conn.execute(
                    "SELECT * FROM pages WHERE title ILIKE $1 AND space_key = $2",
                    [f"%{page_title}%", space_key]
                ).fetchone()
            else:
                return "Error: Provide either page_id or (page_title + space_key)"
            
            if not page:
                return "Page not found"
            
            # Convert to dict
            columns = [desc[0] for desc in conn.description]
            page_dict = dict(zip(columns, page))
            
            chunks = conn.execute(
                "SELECT content, heading_context FROM chunks WHERE page_id = $1 ORDER BY position_in_page",
                [page_dict["page_id"]]
            ).fetchall()
            
            return self._format_page(page_dict, chunks)
        
        @self.server.tool()
        async def list_confluence_spaces() -> str:
            """
            List available Confluence spaces in the cache.
            """
            conn = self.db.connect()
            
            spaces = conn.execute("""
                SELECT 
                    space_key,
                    COUNT(*) as page_count,
                    MAX(synced_at) as last_sync
                FROM pages
                GROUP BY space_key
                ORDER BY space_key
            """).fetchall()
            
            result = "## Available Confluence Spaces\n\n"
            for space in spaces:
                result += f"- **{space[0]}**: {space[1]} pages (sync: {space[2]})\n"
            
            return result
        
        @self.server.tool()
        async def get_confluence_stats() -> str:
            """
            Get statistics about the Confluence RAG cache.
            """
            conn = self.db.connect()
            
            try:
                stats = conn.execute("""
                    SELECT
                        (SELECT COUNT(*) FROM pages) as total_pages,
                        (SELECT COUNT(*) FROM chunks) as total_chunks,
                        (SELECT COUNT(*) FROM chunk_embeddings) as total_embeddings,
                        (SELECT MAX(synced_at) FROM pages) as last_sync
                """).fetchone()
                
                result = "## Confluence RAG Cache Statistics\n\n"
                result += f"- **Total Pages**: {stats[0]}\n"
                result += f"- **Total Chunks**: {stats[1]}\n"
                result += f"- **Total Embeddings**: {stats[2]}\n"
                result += f"- **Last Sync**: {stats[3]}\n"
                
                return result
            except:
                return "Cache empty or not initialized"
    
    def _format_search_results(self, response: SearchResponse) -> str:
        """Format search results for Claude output"""
        
        output = f"## Search Results for: \"{response.query}\"\n\n"
        output += f"*{response.total_results} results in {response.search_time_ms:.0f}ms*\n\n"
        
        for i, result in enumerate(response.results, 1):
            output += f"### {i}. {result.page.title}\n"
            output += f"**Space:** {result.page.space_key} | "
            output += f"**Section:** {' > '.join(result.context_path)}\n"
            output += f"**Relevance:** {result.relevance_score:.2%}\n\n"
            
            # Content preview
            output += f"{result.content[:300]}{'...' if len(result.content) > 300 else ''}\n\n"
            
            # Citations
            if result.citations:
                output += "**Citations:**\n"
                for citation in result.citations:
                    output += f'> "{citation.quote}"\n'
                    output += f'> — [{citation.page_title}]({citation.page_url})'
                    if citation.section:
                        output += f' § {citation.section}'
                    output += f' (confidence: {citation.confidence_score:.0%})\n\n'
            
            output += f"🔗 [Open in Confluence]({result.page.url})\n\n"
            output += "---\n\n"
        
        return output
    
    def _format_page(self, page: dict, chunks: list) -> str:
        """Format a page for output"""
        output = f"# {page['title']}\n\n"
        output += f"**Space:** {page['space_key']} | "
        output += f"**Updated:** {page['updated_at']} by {page['updated_by']}\n"
        output += f"**URL:** {page['url']}\n\n"
        output += "---\n\n"
        
        current_heading = None
        for chunk in chunks:
            # chunk is (content, heading_context)
            if chunk[1] != current_heading:
                current_heading = chunk[1]
                if current_heading:
                    output += f"## {current_heading}\n\n"
            
            output += f"{chunk[0]}\n\n"
        
        return output
    
    async def run(self):
        """Start the MCP server"""
        # FastMCP run() handles stdio automatically
        await self.server.run_stdio_async()
