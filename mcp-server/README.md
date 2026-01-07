# Infrastructure Atlas MCP Server

An [MCP](https://modelcontextprotocol.io) server that integrates with your Infrastructure Atlas dashboard, allowing Claude to inspect vCenter, NetBox, Zabbix, Jira, and Confluence.

This server is written in TypeScript and integrates directly with the Atlas API.

## Features

- **Portal Authentication**: Securely authenticates with your local Atlas instance via the browser.
- **vCenter Integration**: List instances and retrieve VM details.
- **Tools**:
    - `atlas_vcenter_list_instances`
    - `atlas_vcenter_get_vms`
    - `atlas_netbox_search`
    - `atlas_zabbix_alerts`
    - `atlas_jira_search`
    - `atlas_confluence_search`
    - `atlas_search`
    - `atlas_commvault_info`

## Prerequisites

- Node.js (v18 or higher)
- Running instance of Infrastructure Atlas API

## Installation

You can automatically configure Claude Desktop to use this server.

1. Navigate to this directory:
   ```bash
   cd mcp-server-ts
   ```

2. Install dependencies:
   ```bash
   npm install
   ```

3. Run the installation script:
   ```bash
   npm run install:mcp
   ```
   This will update your `~/Library/Application Support/Claude/claude_desktop_config.json` to point to this server.

4. Restart Claude Desktop.

## Uninstallation

To remove the server configuration from Claude Desktop:

1. Run the uninstallation script:
   ```bash
   npm run uninstall:mcp
   ```

2. Restart Claude Desktop.

## Usage

Once installed and Claude Desktop is restarted:

1. You will see "Infrastructure Atlas" in the available MCP servers.
2. When you use a tool for the first time, it will open your browser to authenticate with the Atlas Portal.
3. After logging in, you will be redirected back to a local callback server which saves your token.
4. Subsequent requests will use this stored token.

## Configuration

Configuration is stored in `~/.config/atlas/mcp-config.json`. You typically do not need to edit this manually.
