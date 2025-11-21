#!/usr/bin/env python3
"""Helper script to configure Atlas MCP server in Claude Desktop."""

import json
import os
import platform
import sys
from pathlib import Path


def get_claude_config_path() -> Path:
    """Get the Claude Desktop configuration file path for this platform."""
    system = platform.system()

    if system == "Darwin":  # macOS
        config_dir = Path.home() / "Library" / "Application Support" / "Claude"
    elif system == "Windows":
        config_dir = Path(os.getenv("APPDATA", "")) / "Claude"
    elif system == "Linux":
        config_dir = Path.home() / ".config" / "Claude"
    else:
        raise RuntimeError(f"Unsupported platform: {system}")

    return config_dir / "claude_desktop_config.json"


def main():
    """Configure Atlas MCP server in Claude Desktop."""
    # Get current directory (mcp-server)
    mcp_dir = Path(__file__).parent.absolute()
    atlas_api_url = os.getenv("ATLAS_API_URL", "http://127.0.0.1:8000")
    atlas_api_token = os.getenv("ATLAS_API_TOKEN", "")

    # Prompt for configuration
    print("Atlas MCP Server Setup")
    print("=" * 50)
    print()

    if not atlas_api_token:
        print("⚠️  ATLAS_API_TOKEN not set in environment")
        atlas_api_token = input("Enter your Atlas API token: ").strip()

    if not atlas_api_token:
        print("❌ API token is required")
        sys.exit(1)

    print()
    print(f"API URL: {atlas_api_url}")
    print(f"API Token: {'*' * len(atlas_api_token)}")
    print(f"MCP Directory: {mcp_dir}")
    print()

    # Get Claude config path
    try:
        config_path = get_claude_config_path()
    except RuntimeError as e:
        print(f"❌ {e}")
        sys.exit(1)

    print(f"Claude Config: {config_path}")
    print()

    # Load existing config or create new
    if config_path.exists():
        with open(config_path, "r") as f:
            config = json.load(f)
        print("✓ Found existing Claude configuration")
    else:
        config = {"mcpServers": {}}
        config_path.parent.mkdir(parents=True, exist_ok=True)
        print("✓ Creating new Claude configuration")

    # Ensure mcpServers exists
    if "mcpServers" not in config:
        config["mcpServers"] = {}

    # Add Atlas MCP server
    config["mcpServers"]["atlas"] = {
        "command": "uv",
        "args": ["run", "--directory", str(mcp_dir), "atlas-mcp"],
        "env": {
            "ATLAS_API_URL": atlas_api_url,
            "ATLAS_API_TOKEN": atlas_api_token,
        },
    }

    # Save configuration
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    print()
    print("✅ Atlas MCP server configured successfully!")
    print()
    print("Next steps:")
    print("1. Restart Claude Desktop")
    print("2. Look for the 🔌 icon to confirm MCP servers are loaded")
    print("3. Try asking: 'Show me all vCenter instances in Atlas'")
    print()


if __name__ == "__main__":
    main()
