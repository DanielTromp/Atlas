#!/usr/bin/env node
import fs from 'fs';
import path from 'path';
import os from 'os';

const CONFIG_PATH = path.join(os.homedir(), 'Library', 'Application Support', 'Claude', 'claude_desktop_config.json');

interface MCPConfig {
  mcpServers: {
    [key: string]: {
      command: string;
      args: string[];
      env?: {
        [key: string]: string;
      };
    };
  };
}

const SERVER_NAME = 'Infrastructure Atlas';
const SERVER_PATH = path.resolve(__dirname, 'index.ts');

// Ensure we use the correct npx/tsx command
const COMMAND = 'npx';
const ARGS = ['-y', 'tsx', SERVER_PATH];
const ENV = {
  "ATLAS_API_URL": "http://127.0.0.1:8000"
};

function readConfig(): MCPConfig {
  if (!fs.existsSync(CONFIG_PATH)) {
    return { mcpServers: {} };
  }
  try {
    return JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf-8'));
  } catch (error) {
    console.error(`Error reading config from ${CONFIG_PATH}:`, error);
    process.exit(1);
  }
}

function writeConfig(config: MCPConfig) {
  try {
    const dir = path.dirname(CONFIG_PATH);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }
    fs.writeFileSync(CONFIG_PATH, JSON.stringify(config, null, 2));
    console.log(`Updated configuration at ${CONFIG_PATH}`);
  } catch (error) {
    console.error(`Error writing config to ${CONFIG_PATH}:`, error);
    process.exit(1);
  }
}

function install() {
  console.log('Installing Infrastructure Atlas MCP server...');
  const config = readConfig();
  
  config.mcpServers = config.mcpServers || {};
  config.mcpServers[SERVER_NAME] = {
    command: COMMAND,
    args: ARGS,
    env: ENV
  };
  
  writeConfig(config);
  console.log('Installation complete! Please restart Claude Desktop.');
}

function uninstall() {
  console.log('Uninstalling Infrastructure Atlas MCP server...');
  const config = readConfig();
  
  if (config.mcpServers && config.mcpServers[SERVER_NAME]) {
    delete config.mcpServers[SERVER_NAME];
    writeConfig(config);
    console.log('Uninstallation complete! Please restart Claude Desktop.');
  } else {
    console.log('Server not found in configuration. Nothing to uninstall.');
  }
}

const action = process.argv[2];

if (action === 'install') {
  install();
} else if (action === 'uninstall') {
  uninstall();
} else {
  console.log('Usage: node setup.js [install|uninstall]');
  process.exit(1);
}
