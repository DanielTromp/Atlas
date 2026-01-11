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
        # Add ORDER BY to ensure consistent pagination
        cql += ' ORDER BY id ASC'

        # Confluence Cloud uses cursor-based pagination, not offset-based
        # We must follow _links.next URL, not increment start parameter
        next_path: str | None = "/content/search"
        params: dict | None = {
            "cql": cql,
            "limit": 50,
            "expand": "version,ancestors,metadata.labels,body.storage"
        }

        while next_path:
            # For first request, use params; for subsequent, next_path has cursor embedded
            if params:
                response = await self.client.get(next_path, params=params)
                params = None  # Clear params, subsequent requests use next_path directly
            else:
                response = await self.client.get(next_path)

            response.raise_for_status()
            data = response.json()

            results = data.get("results", [])
            if not results:
                break

            for page in results:
                yield page

            # Get next page URL (contains cursor parameter)
            # The path is like "/rest/api/content/search?cursor=..."
            # We need to strip "/rest/api" since base_url already includes it
            raw_next = data.get("_links", {}).get("next")
            if raw_next:
                # Strip the /rest/api prefix since our client base_url is /wiki/rest/api
                if raw_next.startswith("/rest/api/"):
                    next_path = raw_next[len("/rest/api"):]
                else:
                    next_path = raw_next
            else:
                next_path = None
    
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
    
    async def export_page_html(self, page_id: str) -> tuple[str, str | None]:
        """Export page as HTML for Docling processing.

        Returns:
            Tuple of (html_content, warning_message)
            warning_message is None if content was retrieved successfully
        """
        response = await self.client.get(
            f"/content/{page_id}",
            params={"expand": "body.export_view,body.view,body.storage"}
        )
        response.raise_for_status()
        data = response.json()

        body = data.get("body", {})

        # Try export_view first (best for Docling)
        if "export_view" in body and body["export_view"].get("value"):
            return body["export_view"]["value"], None

        # Fallback to view
        if "view" in body and body["view"].get("value"):
            return body["view"]["value"], "using view fallback"

        # Fallback to storage (raw Confluence XML)
        if "storage" in body and body["storage"].get("value"):
            return body["storage"]["value"], "using storage fallback"

        # No content found - check why
        page_type = data.get("type", "unknown")
        status = data.get("status", "unknown")

        return "", f"no body content (type={page_type}, status={status})"

    async def close(self):
        await self.client.aclose()
