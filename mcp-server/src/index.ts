
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  Tool,
} from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";
import fs from "fs";
import path from "path";
import os from "os";
import http from "http";
import { exec } from "child_process";
import axios from "axios";

// Configuration
const CONFIG_DIR = path.join(os.homedir(), ".config", "atlas");
const CONFIG_FILE = path.join(CONFIG_DIR, "mcp-config.json");
const ATLAS_API_URL = process.env.ATLAS_API_URL || "http://127.0.0.1:8000";

// Ensure config dir exists
if (!fs.existsSync(CONFIG_DIR)) {
  fs.mkdirSync(CONFIG_DIR, { recursive: true });
}

interface Config {
  token?: string;
  username?: string;
  api_url?: string;
}

class ConfigManager {
  private config: Config = {};

  constructor() {
    this.load();
  }

  load() {
    try {
      if (fs.existsSync(CONFIG_FILE)) {
        this.config = JSON.parse(fs.readFileSync(CONFIG_FILE, "utf-8"));
      }
    } catch (error) {
      console.error("Failed to load config:", error);
    }
  }

  save() {
    try {
      fs.writeFileSync(CONFIG_FILE, JSON.stringify(this.config, null, 2));
    } catch (error) {
      console.error("Failed to save config:", error);
    }
  }

  get token() {
    return this.config.token;
  }

  set token(value: string | undefined) {
    this.config.token = value;
    this.save();
  }
  
  get username() {
      return this.config.username;
  }
  
  set username(value: string | undefined) {
      this.config.username = value;
      this.save();
  }
}

const configManager = new ConfigManager();

async function authenticate() {
  if (configManager.token) {
    // Verify token validity?
    try {
        await axios.get(`${ATLAS_API_URL}/auth/me`, {
            headers: { Authorization: `Bearer ${configManager.token}` }
        });
        return; // Valid
    } catch (e: any) {
        if (e.response && e.response.status === 401) {
            console.error("Token invalid or expired, re-authenticating...");
            configManager.token = undefined;
        } else {
            console.error("Could not verify token. Assuming valid for now, or network error. Error:", e.message);
            // If network error, we might still want to proceed if we can't keycloak? 
            // But we can't do anything without API anyway.
            // Let's prompt auth if strictly 401.
        }
    }
  }

  if (!configManager.token) {
    console.error("Authentication required. Please log in via the browser.");
    await startLocalAuthServer();
  }
}

async function startLocalAuthServer() {
  return new Promise<void>((resolve) => {
    const server = http.createServer((req, res) => {
      const url = new URL(req.url || "/", `http://${req.headers.host}`);
      
      if (url.pathname === "/callback") {
        const token = url.searchParams.get("token");
        const username = url.searchParams.get("username");

        if (token) {
          configManager.token = token;
          if (username) configManager.username = username;
          
          res.writeHead(200, { "Content-Type": "text/html" });
          res.end(`
            <html>
                <body style="font-family: system-ui; text-align: center; padding: 50px;">
                    <h1>Authenticated!</h1>
                    <p>You can now close this window and return to Claude.</p>
                    <script>window.close()</script>
                </body>
            </html>
          `);
          
          server.close();
          resolve();
        } else {
          res.writeHead(400);
          res.end("Missing token");
        }
      } else {
        res.writeHead(404);
        res.end("Not found");
      }
    });

    server.listen(0, () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      const callbackUrl = `http://localhost:${port}/callback`;
      const authUrl = `${ATLAS_API_URL}/auth/authorize-mcp?callback=${encodeURIComponent(callbackUrl)}`;
      
      console.error(`Please log in at: ${authUrl}`);
      // Try to open browser
      const openCmd = process.platform === 'darwin' ? 'open' : 
                      process.platform === 'win32' ? 'start' : 'xdg-open';
      exec(`${openCmd} "${authUrl}"`);
    });
  });
}

// Server implementation
const server = new Server(
  {
    name: "Infrastructure Atlas",
    version: "1.0.0",
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

// Tools
server.setRequestHandler(ListToolsRequestSchema, async () => {
    return {
        tools: [
            {
                name: "atlas_vcenter_list_instances",
                description: "List all configured vCenter instances with status and details",
                inputSchema: {
                    type: "object",
                    properties: {},
                }
            },
            {
                name: "atlas_vcenter_get_vms",
                description: "Get VMs from a specific vCenter",
                inputSchema: {
                    type: "object",
                    properties: {
                        config_id: { type: "string", description: "The ID of the vCenter configuration" },
                        limit: { type: "integer", description: "Using limit (max 50) of VMs to return", default: 20 }
                    },
                }
            },
            {
                name: "atlas_netbox_search",
                description: "Search NetBox for devices, VMs, or IP addresses",
                inputSchema: {
                    type: "object",
                    properties: {
                        query: { type: "string", description: "Search query" },
                    },
                    required: ["query"]
                }
            },
            {
                name: "atlas_zabbix_alerts",
                description: "Get current Zabbix alerts (problems)",
                inputSchema: {
                     type: "object",
                     properties: {
                         severity: { type: "integer", description: "Minimum severity level (0-5)" },
                         group_id: { type: "string", description: "Filter by host group ID" }
                     }
                }
            },
            {
                name: "atlas_jira_search",
                description: "Search Jira issues",
                inputSchema: {
                    type: "object",
                    properties: {
                        jql: { type: "string", description: "JQL query string" },
                        limit: { type: "integer", default: 10 }
                    },
                    required: ["jql"]
                }

            },
            {
                name: "createJiraRemoteLink",
                description: "Create a remote link from a Jira issue to a Confluence page",
                inputSchema: {
                    type: "object",
                    properties: {
                         issueIdOrKey: { type: "string", description: "Jira issue key (e.g., ESD-123)" },
                         confluencePageId: { type: "string", description: "Confluence page ID" },
                         title: { type: "string", description: "Link title (optional)" },
                         relationship: { type: "string", description: "Relationship type (default: 'Wiki Page')", default: "Wiki Page" }
                    },
                    required: ["issueIdOrKey", "confluencePageId"]
                }
            },
            {
                name: "getJiraRemoteLinks",
                description: "Get remote links for a Jira issue",
                inputSchema: {
                    type: "object",
                    properties: {
                        issueIdOrKey: { type: "string", description: "Jira issue key" }
                    },
                    required: ["issueIdOrKey"]
                }
            },
            {
                name: "deleteJiraRemoteLink",
                description: "Delete a remote link from a Jira issue",
                inputSchema: {
                    type: "object",
                    properties: {
                        issueIdOrKey: { type: "string", description: "Jira issue key" },
                        linkId: { type: "string", description: "ID of the remote link to delete" }
                    },
                    required: ["issueIdOrKey", "linkId"]
                }
            },
            {
                name: "atlas_confluence_search",
                description: "Search Confluence pages",
                inputSchema: {
                    type: "object",
                    properties: {
                        cql: { type: "string", description: "CQL query string" },
                        limit: { type: "integer", default: 10 }
                    },
                    required: ["cql"]
                }
            },
            {
                name: "atlas_search",
                description: "Search across all Atlas systems (vCenter, NetBox, Zabbix, Jira, Confluence)",
                inputSchema: {
                    type: "object",
                    properties: {
                        query: { type: "string", description: "Search query (hostname, IP, ticket ID, etc.)" },
                        limit: { type: "integer", description: "Limit results per system", default: 10 }
                    },
                    required: ["query"]
                }
            },
            {
                name: "atlas_commvault_info",
                description: "Get Commvault backup status and job history for a specific hostname",
                inputSchema: {
                    type: "object",
                    properties: {
                        hostname: { type: "string", description: "Target hostname or client ID" },
                        hours: { type: "integer", description: "Hours of history to fetch (default: 24)", default: 24 }
                    },
                    required: ["hostname"]
                }
            }
        ]
    };
});

server.setRequestHandler(CallToolRequestSchema, async (request) => {
    // Ensure we are authenticated before any tool call
    if (!configManager.token) {
        throw new Error("Authentication required. Please restart the MCP server to trigger login.");
    }
    
    const api = axios.create({
        baseURL: ATLAS_API_URL,
        headers: { Authorization: `Bearer ${configManager.token}` }
    });

    try {
        switch (request.params.name) {
            case "atlas_vcenter_list_instances": {
                const response = await api.get("/vcenter/instances");
                return {
                    content: [{
                        type: "text",
                        text: JSON.stringify(response.data, null, 2)
                    }]
                };
            }
            case "atlas_vcenter_get_vms": {
                const params = request.params.arguments as any;
                const response = await api.get(`/vcenter/${params.config_id}/vms`, {
                    params: { limit: params.limit || 20 }
                });
                return {
                    content: [{
                        type: "text",
                        text: JSON.stringify(response.data, null, 2)
                    }]
                };
            }
            case "atlas_netbox_search": {
                const params = request.params.arguments as any;
                const response = await api.get("/netbox/search", { params: { q: params.query } });
                 return {
                    content: [{
                        type: "text",
                        text: JSON.stringify(response.data, null, 2)
                    }]
                };
            }
            case "atlas_zabbix_alerts": {
                const params = request.params.arguments as any;
                const response = await api.get("/zabbix/alerts", { 
                    params: { 
                        min_severity: params.severity,
                        group_ids: params.group_id
                    } 
                });
                 return {
                    content: [{
                        type: "text",
                        text: JSON.stringify(response.data, null, 2)
                    }]
                };
            }
            case "atlas_jira_search": {
                const params = request.params.arguments as any;
                const response = await api.get("/jira/search", { 
                    params: { jql: params.jql, limit: params.limit, expand: "names" } 
                });
                 return {
                    content: [{
                        type: "text",
                        text: JSON.stringify(response.data, null, 2)
                    }]
                };

            }
            case "createJiraRemoteLink": {
                const params = request.params.arguments as any;
                const response = await api.post(`/jira/issue/${params.issueIdOrKey}/remotelink/confluence`, { 
                    page_id: params.confluencePageId,
                    title: params.title,
                    relationship: params.relationship
                });
                 return {
                    content: [{
                        type: "text",
                        text: JSON.stringify(response.data, null, 2)
                    }]
                };
            }
            case "getJiraRemoteLinks": {
                const params = request.params.arguments as any;
                const response = await api.get(`/jira/issue/${params.issueIdOrKey}/remotelink`);
                 return {
                    content: [{
                        type: "text",
                        text: JSON.stringify(response.data, null, 2)
                    }]
                };
            }
            case "deleteJiraRemoteLink": {
                const params = request.params.arguments as any;
                const response = await api.delete(`/jira/issue/${params.issueIdOrKey}/remotelink/${params.linkId}`);
                 return {
                    content: [{
                        type: "text",
                        text: JSON.stringify(response.data, null, 2)
                    }]
                };
            }
            case "atlas_confluence_search": {
                const params = request.params.arguments as any;
                const response = await api.get("/confluence/search", { 
                    params: { cql: params.cql, limit: params.limit } 
                });
                 return {
                    content: [{
                        type: "text",
                        text: JSON.stringify(response.data, null, 2)
                    }]
                };
            }
            case "atlas_search": {
                const params = request.params.arguments as any;
                const limit = params.limit || 10;
                const response = await api.get("/search/aggregate", { 
                    params: { 
                        q: params.query,
                        zlimit: limit,
                        jlimit: limit,
                        climit: limit,
                        vlimit: limit
                    } 
                });
                 return {
                    content: [{
                        type: "text",
                        text: JSON.stringify(response.data, null, 2)
                    }]
                };
            }
            case "atlas_commvault_info": {
                const params = request.params.arguments as any;
                const hours = params.hours || 24;
                const response = await api.get("/commvault/server-info", { 
                    params: { 
                        hostname: params.hostname,
                        hours: hours,
                        limit: 10
                    } 
                });
                 return {
                    content: [{
                        type: "text",
                        text: JSON.stringify(response.data, null, 2)
                    }]
                };
            }
            default:
                throw new Error(`Unknown tool: ${request.params.name}`);
        }
    } catch (error: any) {
         return {
            content: [{
                type: "text",
                text: `Error: ${error.message} - ${JSON.stringify(error.response?.data || {})}`
            }],
            isError: true,
        };
    }
});

async function main() {
    // Attempt auth strictly on startup?
    // Or lazy load?
    // Better on startup to prompt user immediately.
    await authenticate();
    
    const transport = new StdioServerTransport();
    await server.connect(transport);
    console.error("Atlas MCP Server running on stdio");
}

main().catch((error) => {
  console.error("Fatal error:", error);
  process.exit(1);
});
