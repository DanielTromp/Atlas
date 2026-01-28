# Multi-Platform Bot System

The Atlas Bot System enables users to interact with AI agents via Telegram, Slack, and Microsoft Teams. Users can chat with Atlas as a general assistant or directly mention specific agents for specialized tasks.

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [User Account Linking](#user-account-linking)
- [Telegram Bot](#telegram-bot)
- [Slack Bot](#slack-bot)
- [Microsoft Teams Bot](#microsoft-teams-bot)
- [CLI Commands](#cli-commands)
- [API Reference](#api-reference)
- [Troubleshooting](#troubleshooting)

## Overview

### Features

- **User Authorization**: Only linked Atlas users can interact with bots
- **Agent Mentions**: Direct interaction with specific agents using `@agent_name`
- **Default Routing**: Messages without mentions are routed to the Triage agent
- **Platform-Aware Formatting**: Responses optimized for each platform (compact for Telegram, rich for Slack/Teams)
- **Comprehensive Logging**: All bot interactions are logged and visible in the web UI
- **Usage Tracking**: Token and cost tracking per user, per platform

### Interaction Modes

1. **General Chat**: Send a message to get help from the default agent (Triage)
   ```
   What are the new tickets for the Systems team?
   ```

2. **Direct Agent Mention**: Target a specific agent
   ```
   @engineer Check the backup status for server web-prod-01
   ```

### Available Agents

| Agent | ID | Use Case |
|-------|----|----|
| Triage | `@triage` | Ticket analysis, categorization, quick lookups |
| Engineer | `@engineer` | Technical investigation, infrastructure queries |
| Reviewer | `@reviewer` | Quality review, validation |

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Platform Clients                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                       │
│  │ Telegram │  │  Slack   │  │  Teams   │                       │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘                       │
└───────┼─────────────┼─────────────┼─────────────────────────────┘
        │             │             │
        ▼             ▼             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Bot Adapters                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │TelegramAdapter│  │ SlackAdapter │  │ TeamsAdapter │           │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘           │
└─────────┼─────────────────┼─────────────────┼───────────────────┘
          │                 │                 │
          ▼                 ▼                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Bot Orchestrator                              │
│  - User authorization (linked accounts)                          │
│  - Agent mention parsing (@agent_name)                           │
│  - Message routing                                               │
│  - Response formatting                                           │
│  - Logging                                                       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Playground Runtime                            │
│  - Agent execution                                               │
│  - Skill integration                                             │
│  - Streaming responses                                           │
│  - Usage tracking                                                │
└─────────────────────────────────────────────────────────────────┘
```

## User Account Linking

Users must link their platform accounts to their Atlas user account before they can use bots. This ensures proper authorization and usage attribution.

### Linking Flow

1. **Generate Code**: Admin or user generates a verification code
   ```bash
   uv run atlas bots link-user <username> telegram
   ```

2. **Send Code**: User sends `/link <code>` to the bot
   ```
   /link 123456
   ```

3. **Verification**: Bot verifies the code and links the accounts
   - Codes are valid for 10 minutes
   - One platform account per Atlas user per platform

### Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message and instructions |
| `/link <code>` | Link platform account with verification code |
| `/help` | Show available agents and usage |
| `/agents` | List available agents |

## Telegram Bot

### Setup

1. **Create Bot with BotFather**
   - Message [@BotFather](https://t.me/BotFather) on Telegram
   - Send `/newbot` and follow prompts
   - Copy the bot token

2. **Configure Environment**
   ```bash
   # Add to .env
   TELEGRAM_BOT_TOKEN=your-bot-token-here
   ```

3. **Enable Module**
   ```bash
   ATLAS_MODULE_BOTS_ENABLED=1
   ```

4. **Verify Setup**
   ```bash
   uv run atlas bots setup-telegram --token $TELEGRAM_BOT_TOKEN
   ```

### Running Modes

#### Polling Mode (Recommended for Internal Use)

No public URL required. The bot polls Telegram for updates.

**Local Development:**
```bash
uv run atlas bots run-telegram
```

**Docker/Container Deployment (Production):**
```bash
# Start the Telegram bot container
docker compose --profile bots up -d telegram-bot

# View logs
docker compose logs -f telegram-bot

# Stop
docker compose stop telegram-bot
```

- Runs as a long-lived process
- Use `Ctrl+C` to stop (local) or `docker compose stop` (container)
- Ideal for internal/private deployments

#### Webhook Mode (For Public Deployments)

Requires a public HTTPS endpoint.

```bash
uv run atlas bots setup-telegram \
  --token $TELEGRAM_BOT_TOKEN \
  --webhook-url https://your-domain.com/webhooks/bots/telegram/secret \
  --webhook-secret your-secret-token
```

### Message Formatting

Telegram responses use MarkdownV2 formatting:
- **Bold** for emphasis
- `Code` for technical terms
- Compact responses (4096 char limit)
- Tool calls shown as italics

### Testing

```bash
# Send test message to a chat
uv run atlas bots test-telegram <chat_id>

# Check webhook status
uv run atlas bots webhook-info
```

## Slack Bot

Full-featured Slack integration using Socket Mode (no public endpoints required).

### Setup

1. **Create Slack App**
   - Go to [api.slack.com/apps](https://api.slack.com/apps)
   - Create a new app from scratch
   - Enable Socket Mode in Settings > Socket Mode
   - Generate an App-Level Token with `connections:write` scope

2. **Configure Bot Scopes**
   Navigate to OAuth & Permissions and add these Bot Token Scopes:
   - `app_mentions:read` - Receive @mentions
   - `chat:write` - Send messages
   - `files:write` - Upload files (for Excel exports)
   - `im:history` - Read DMs
   - `im:read` - View basic DM info
   - `im:write` - Start DMs
   - `users:read` - Get user info
   - `users:read.email` - Get user email

3. **Enable Events**
   In Event Subscriptions, subscribe to:
   - `message.im` - Direct messages
   - `app_mention` - @mentions in channels

4. **Configure Environment**
   ```bash
   # Add to .env
   SLACK_BOT_TOKEN=xoxb-your-bot-token
   SLACK_APP_TOKEN=xapp-your-app-level-token
   ```

5. **Install App**
   Install the app to your workspace from OAuth & Permissions

### Running

#### Local Development

```bash
# Start the Slack bot
uv run atlas bots run-slack
```

#### Docker/Container Deployment (Production)

```bash
# Start the Slack bot container
docker compose --profile bots up -d slack-bot

# View logs
docker compose logs -f slack-bot

# Stop
docker compose stop slack-bot
```

The bot uses Socket Mode, which creates an outbound WebSocket connection to Slack. No public URLs or webhooks required.

### Features

- **Rich Block Kit Formatting**: Messages use sections, dividers, and context blocks
- **Thread Support**: Each thread maintains separate conversation memory
- **File Exports**: Excel/CSV exports uploaded directly to Slack
- **Platform-Aware Markdown**: Converts standard markdown to Slack mrkdwn format

### Commands

| Command | Description |
|---------|-------------|
| `!help` | Show available commands and agents |
| `!link <code>` | Link Slack account with verification code |
| `!status` | Check account linking status |
| `!agents` | List available AI agents |
| `!test` | Test message formatting |

### Message Formatting

Slack uses "mrkdwn" format which differs from standard Markdown:
- `*bold*` for bold (not `**bold**`)
- `_italic_` for italic
- `` `code` `` for inline code
- No native table support (converted to list format)

### Testing

```bash
# Check bot status
uv run atlas bots status

# View linked accounts
uv run atlas bots list-accounts --platform slack
```

## Microsoft Teams Bot

> **Status**: Planned for Phase 4

### Configuration

```bash
# Add to .env
TEAMS_APP_ID=your-app-id
TEAMS_APP_PASSWORD=your-app-password
```

### Features (Planned)

- Adaptive Cards formatting
- Proactive messaging
- Meeting integrations

## CLI Commands

### Module Management

```bash
# Check bot platform status
uv run atlas bots status

# Show all linked accounts
uv run atlas bots list-accounts

# Filter by platform
uv run atlas bots list-accounts --platform telegram
```

### User Linking

```bash
# Generate verification code
uv run atlas bots link-user <username> <platform>

# Example
uv run atlas bots link-user john.doe telegram
# Output: Code: 123456 (valid for 10 minutes)

# Unlink a user
uv run atlas bots unlink-user john.doe telegram
```

### Telegram-Specific

```bash
# Configure bot
uv run atlas bots setup-telegram --token $TELEGRAM_BOT_TOKEN

# Configure with webhook
uv run atlas bots setup-telegram \
  --token $TELEGRAM_BOT_TOKEN \
  --webhook-url https://example.com/webhooks/bots/telegram/secret

# Run in polling mode
uv run atlas bots run-telegram

# Send test message
uv run atlas bots test-telegram <chat_id>

# Check webhook info
uv run atlas bots webhook-info
```

### Usage Statistics

```bash
# Show usage for last 30 days
uv run atlas bots usage

# Custom time range
uv run atlas bots usage --days 7

# Filter by platform
uv run atlas bots usage --platform telegram
```

## API Reference

### Webhook Endpoints

#### Telegram Webhook

```http
POST /webhooks/bots/telegram/{webhook_secret}
Content-Type: application/json

{
  "update_id": 123456789,
  "message": {
    "message_id": 1,
    "from": {"id": 12345, "username": "user"},
    "chat": {"id": 12345, "type": "private"},
    "text": "@triage Show new tickets"
  }
}
```

### Admin Endpoints

#### List Platform Status

```http
GET /api/admin/bots/platforms
Authorization: Bearer <token>
```

**Response**:
```json
{
  "platforms": [
    {
      "platform": "telegram",
      "configured": true,
      "enabled": true,
      "linked_users": 5,
      "messages_24h": 42
    }
  ]
}
```

#### List Linked Accounts

```http
GET /api/admin/bots/accounts?platform=telegram
Authorization: Bearer <token>
```

#### Unlink Account

```http
DELETE /api/admin/bots/accounts/{account_id}
Authorization: Bearer <token>
```

#### Get Conversations

```http
GET /api/admin/bots/conversations?platform=telegram&limit=50
Authorization: Bearer <token>
```

#### Get Conversation Messages

```http
GET /api/admin/bots/conversations/{conversation_id}/messages
Authorization: Bearer <token>
```

#### Get Usage Statistics

```http
GET /api/admin/bots/usage?days=30&platform=telegram
Authorization: Bearer <token>
```

## Database Schema

### Bot Platform Accounts

Links external platform users to Atlas users.

| Column | Type | Description |
|--------|------|-------------|
| id | int | Primary key |
| user_id | str | Atlas user ID (FK) |
| platform | str | telegram/slack/teams |
| platform_user_id | str | Platform-specific user ID |
| platform_username | str | Display name |
| verified | bool | Account verified |
| verification_code | str | Pending verification code |
| verification_expires | datetime | Code expiry time |

### Bot Conversations

Tracks bot conversation sessions.

| Column | Type | Description |
|--------|------|-------------|
| id | int | Primary key |
| platform | str | Platform name |
| platform_conversation_id | str | Chat/channel ID |
| platform_account_id | int | Linked account (FK) |
| agent_id | str | Current agent |
| session_id | str | Playground session ID |

### Bot Messages

Logs all bot messages for audit and display.

| Column | Type | Description |
|--------|------|-------------|
| id | int | Primary key |
| conversation_id | int | Conversation (FK) |
| direction | str | inbound/outbound |
| content | text | Message content |
| agent_id | str | Processing agent |
| tool_calls | json | Tool calls made |
| input_tokens | int | Input token count |
| output_tokens | int | Output token count |
| cost_usd | float | Request cost |
| duration_ms | int | Processing time |
| error | str | Error message if any |

## Container Deployment

Both Slack and Telegram bots can run as separate containers for production deployments.

### Quick Start

```bash
# Start all bots
docker compose --profile bots up -d

# Or start specific bot
docker compose --profile bots up -d slack-bot
docker compose --profile bots up -d telegram-bot
```

### Required Environment Variables

Add to your `.env` file:

```bash
# Enable bots module
ATLAS_MODULE_BOTS_ENABLED=1

# Slack (Socket Mode - no public URL needed)
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-app-level-token

# Telegram (Polling Mode - no public URL needed)
TELEGRAM_BOT_TOKEN=your-bot-token-from-botfather
```

### Container Networking for RAG

When running bots in containers with the `--profile bots` or `--profile full` option, the bot containers need to access other services (MongoDB, Qdrant) by container hostname, not `localhost`.

The `docker-compose.yml` already sets `MONGODB_URI=mongodb://mongodb:27017` for the bot containers. If using Confluence RAG search, ensure `ATLAS_RAG_QDRANT_HOST` is set to the Qdrant container name:

```yaml
# In docker-compose.yml, under slack-bot/telegram-bot environment:
environment:
  - ATLAS_RAG_QDRANT_HOST=qdrant  # Use container name, not localhost
```

Without this, RAG searches will fail with "connection refused" errors because the bot container tries to connect to `localhost:6333` instead of the Qdrant container.

### Container Features

The bot containers include:

- **Auto-restart**: Containers restart automatically on failure
- **Log rotation**: Logs limited to 10MB with 3 file rotation
- **VPN DNS**: Internal DNS servers configured for VPN access to internal services
- **MongoDB integration**: Uses shared MongoDB for conversation storage

### Monitoring

```bash
# View bot logs
docker compose logs -f slack-bot
docker compose logs -f telegram-bot

# Check bot status
docker compose ps slack-bot telegram-bot

# Restart a bot
docker compose restart slack-bot
```

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Docker Compose Stack                          │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │  atlas       │  │  slack-bot   │  │ telegram-bot │          │
│  │  (API/UI)    │  │  (Socket)    │  │  (Polling)   │          │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘          │
│         │                 │                 │                   │
│         └────────────────┼────────────────┘                    │
│                          │                                      │
│                   ┌──────▼───────┐                              │
│                   │   mongodb    │                              │
│                   │  (Database)  │                              │
│                   └──────────────┘                              │
└─────────────────────────────────────────────────────────────────┘
```

### Profiles

| Profile | Services Included |
|---------|-------------------|
| (none) | atlas, mongodb |
| `bots` | + slack-bot, telegram-bot |
| `rag` | + qdrant |
| `full` | All services |

```bash
# Examples
docker compose up -d                      # Core only
docker compose --profile bots up -d       # Core + bots
docker compose --profile full up -d       # Everything
```

## Troubleshooting

### Bot Not Responding

1. **Check module is enabled**:
   ```bash
   uv run atlas bots status
   ```

2. **Verify bot token**:
   ```bash
   uv run atlas bots setup-telegram --token $TELEGRAM_BOT_TOKEN
   ```

3. **Check logs**:
   ```bash
   LOG_LEVEL=debug uv run atlas bots run-telegram
   ```

### "Account not linked" Error

User needs to link their account:
```bash
# Generate code for user
uv run atlas bots link-user <username> telegram

# User sends to bot
/link <code>
```

### Webhook Not Receiving Updates

1. **Check webhook status**:
   ```bash
   uv run atlas bots webhook-info
   ```

2. **Verify HTTPS certificate**: Telegram requires valid SSL

3. **Check pending updates**: May be queued if webhook was down

4. **Use polling mode**: For internal deployments without public URL

### Message Formatting Issues

Telegram MarkdownV2 requires escaping special characters. If you see parse errors:
- The system auto-retries without formatting
- Check logs for specific escape issues

### Database Errors

If seeing SQLite I/O errors:
- Ensure only one process writes to database
- Stop any running MCP servers that might conflict

## Related Documentation

- [Agent Playground](playground.md) - Underlying agent runtime
- [Atlas Agents Platform](atlas_agents_platform.md) - Full workflow system
- [Web UI Guide](web-ui.md) - Admin panel for bot management
