# Authentication Fix for Atlas MCP Server

## Problem

The Atlas API has two layers of authentication:

1. **Middleware Layer**: Validates the Bearer token
2. **User Layer**: Requires an authenticated User object from the database

The vCenter endpoints (and most other endpoints) use `CurrentUserDep` which requires a User object. The Bearer token alone passes the middleware check but doesn't populate `request.state.user`, causing a "Not authenticated" error.

## Solution

The MCP server now supports **session-based authentication** using username/password login, which properly creates a user session.

### How It Works

1. MCP server logs in with username/password via `/auth/login`
2. Atlas returns a session cookie
3. All subsequent requests use the session cookie
4. The AuthMiddleware populates `request.state.user` from the session
5. The `CurrentUserDep` dependency gets the User object successfully

## Configuration

### Atlas (.env)

```bash
# Create a default admin user on first startup
ATLAS_DEFAULT_ADMIN_USERNAME=admin
ATLAS_DEFAULT_ADMIN_PASSWORD=atlas-admin-2024

# API token (still needed for some endpoints)
ATLAS_API_TOKEN=atlas-Sk_1NgRWRNTQuFQ2pI-a9ReObuTgVUn0ao8kQ_XjRUo
```

### MCP Server (.env)

```bash
ATLAS_API_URL=https://localhost:8443

# Use session authentication
ATLAS_USERNAME=admin
ATLAS_PASSWORD=atlas-admin-2024

# SSL verification
ATLAS_VERIFY_SSL=false
```

### Claude Desktop Config

```json
{
  "mcpServers": {
    "atlas": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/Users/daniel/Documents/code/Atlas/mcp-server",
        "atlas-mcp"
      ],
      "env": {
        "ATLAS_API_URL": "https://localhost:8443",
        "ATLAS_USERNAME": "admin",
        "ATLAS_PASSWORD": "atlas-admin-2024",
        "ATLAS_VERIFY_SSL": "false"
      }
    }
  }
}
```

## Testing

### 1. Restart Atlas API

The API server must be restarted to create the admin user:

```bash
pkill -f "atlas api serve"
cd /Users/daniel/Documents/code/Atlas
uv run atlas api serve --host 0.0.0.0 --port 8443 --ssl-certfile certs/localhost.pem --ssl-keyfile certs/localhost-key.pem
```

### 2. Test API Access

```bash
# Test health endpoint (no auth required)
curl -k https://localhost:8443/health

# Test login
curl -k -X POST https://localhost:8443/auth/login \
  -d "username=admin&password=atlas-admin-2024" \
  -c cookies.txt \
  -v

# Test vCenter endpoint with session
curl -k -b cookies.txt https://localhost:8443/vcenter/instances
```

### 3. Test MCP Server

```bash
cd /Users/daniel/Documents/code/Atlas/mcp-server
uv run pytest  # Should pass all tests
```

### 4. Test in Claude Desktop

1. Update `~/Library/Application Support/Claude/claude_desktop_config.json` with the config above
2. Restart Claude Desktop
3. Look for the 🔌 icon showing "atlas" as connected
4. Ask: "Show me all vCenter instances in Atlas"

## Code Changes

### AtlasAPIClient (`server.py`)

Added session management:
- Accepts `username` and `password` parameters
- Automatically logs in on first request
- Stores session cookies
- Reuses the same HTTP client for all requests

### Environment Variables

New variables:
- `ATLAS_USERNAME` - Atlas login username
- `ATLAS_PASSWORD` - Atlas login password

Still supported:
- `ATLAS_API_TOKEN` - Bearer token (for endpoints that don't require user context)

## Why Not Just Fix the Bearer Token?

We could modify Atlas to populate `request.state.user` when using a Bearer token, but:

1. **Security**: The Bearer token is meant to be stateless - tying it to a specific user breaks that model
2. **Complexity**: Would need to create a "system user" or "API user" concept
3. **Session Auth Works**: The existing session authentication already solves the problem

## Alternative: API User Support

If you want Bearer token authentication to work properly, you could:

1. Create an "API User" in the database
2. Modify the `AuthMiddleware` to load that user when the Bearer token is valid
3. Set `request.state.user` to the API user

This would require changes to `src/infrastructure_atlas/api/app.py` around line 505-509.

## Summary

✅ Session authentication works with all endpoints
✅ Tests pass
✅ No Atlas code changes required
⚠️ Bearer token authentication still limited to endpoints without user requirements
