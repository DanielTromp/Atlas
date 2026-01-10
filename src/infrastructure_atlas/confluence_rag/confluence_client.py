import httpx
from typing import AsyncIterator
from datetime import datetime

class ConfluenceClient:
    """Async Confluence API client"""
    
    def __init__(self, base_url: str, username: str, api_token: str):
        self.base_url = base_url.rstrip('/')
        self.auth = (username, api_token)
        self.client = httpx.AsyncClient(
            base_url=f"{self.base_url}/wiki/rest/api",
            auth=self.auth,
            timeout=30.0
        )
    
    async def get_pages_in_space(
        self, 
        space_key: str, 
        labels: list[str] | None = None,
        updated_after: datetime | None = None,
        ancestor_id: str | None = None
    ) -> AsyncIterator[dict]:
        """Fetch all pages from a space, optionally filtered"""
        # Use CQL for efficient filtering
        cql_parts = [f'space = "{space_key}"', 'type = "page"']
        
        if labels:
            label_cql = ' OR '.join(f'label = "{l}"' for l in labels)
            cql_parts.append(f'({label_cql})')
            
        if ancestor_id:
            # Fetch descendants AND the page itself
            # CQL: ancestor = 123 OR id = 123
            # But combined with other filters (space, etc)
            # Note: space is implied by ancestor usually but good to keep
            cql_parts.append(f'(ancestor = "{ancestor_id}" OR id = "{ancestor_id}")')
        
        if updated_after:
            # Format datetime for CQL: "yyyy-MM-dd HH:mm" or similar
            # Confluence expects "yyyy-MM-dd" or "yyyy-MM-dd HH:mm"
            # Using simple format
            date_str = updated_after.strftime("%Y-%m-%d %H:%M")
            cql_parts.append(f'lastModified > "{date_str}"')
        
        cql = ' AND '.join(cql_parts)
        # Log the generated CQL for debugging
        print(f"DEBUG: Executing CQL: {cql}")
        
        start = 0
        limit = 50
        
        while True:
            response = await self.client.get(
                "/content/search",
                params={
                    "cql": cql,
                    "start": start,
                    "limit": limit,
                    "expand": "version,ancestors,metadata.labels,body.storage"
                }
            )
            response.raise_for_status()
            data = response.json()
            
            for page in data["results"]:
                yield page
            
            if len(data["results"]) < limit:
                break
            start += limit
    
    async def get_page_content(self, page_id: str) -> dict:
        """Fetch full page content"""
        response = await self.client.get(
            f"/content/{page_id}",
            params={
                "expand": "body.storage,body.view,version,ancestors,metadata.labels"
            }
        )
        response.raise_for_status()
        return response.json()
    
    async def export_page_html(self, page_id: str) -> str:
        """Export page as HTML for Docling processing"""
        response = await self.client.get(
            f"/content/{page_id}",
            params={"expand": "body.export_view"}
        )
        response.raise_for_status()
        body = response.json()["body"]
        if "export_view" in body:
             return body["export_view"]["value"]
        # Fallback to storage or view if export_view not available
        if "view" in body:
             return body["view"]["value"]
        if "storage" in body:
             return body["storage"]["value"]
        return ""

    async def close(self):
        await self.client.aclose()
