# Agent Playground

The Agent Playground is an interactive environment for testing and chatting with Atlas AI agents. It provides a web-based interface and API for direct agent interaction without the full workflow orchestration pipeline.

## Table of Contents

- [Overview](#overview)
- [Available Agents](#available-agents)
- [Web Interface](#web-interface)
- [API Reference](#api-reference)
- [Configuration](#configuration)
- [Usage Tracking](#usage-tracking)
- [CLI Commands](#cli-commands)

## Overview

The Playground provides:

- **Interactive Chat**: Real-time streaming conversations with AI agents
- **Multiple Agents**: Specialized agents for different tasks (Triage, Engineer, Reviewer)
- **Skill Integration**: Agents have access to infrastructure skills (Jira, NetBox, Zabbix, etc.)
- **Session Management**: Persistent chat sessions with history
- **Usage Analytics**: Token tracking, cost monitoring, and activity logs
- **Multi-Client Support**: Access via web UI, Telegram, Slack, or Teams bots

## Available Agents

### Triage Agent

**Purpose**: Ticket categorization and initial assessment

| Property | Value |
|----------|-------|
| ID | `triage` |
| Default Model | `claude-haiku-4-5-20251001` |
| Temperature | 0.3 |
| Skills | Jira, Confluence |

**Use cases**:
- Analyze incoming tickets
- Categorize issues by type and severity
- Assess complexity
- Suggest assignees

**Example**:
```
@triage Show me the newest tickets in project ESD
```

### Engineer Agent

**Purpose**: Technical investigation and problem solving

| Property | Value |
|----------|-------|
| ID | `engineer` |
| Default Model | `claude-sonnet-4-5-20250929` |
| Temperature | 0.5 |
| Skills | Jira, NetBox, Zabbix, vCenter, Commvault |

**Use cases**:
- Investigate technical issues
- Analyze system health
- Cross-reference infrastructure data
- Propose solutions

**Example**:
```
@engineer Check if server web-prod-01 has any active alerts and recent backups
```

### Reviewer Agent

**Purpose**: Quality assurance and validation

| Property | Value |
|----------|-------|
| ID | `reviewer` |
| Default Model | `claude-haiku-4-5-20251001` |
| Temperature | 0.2 |
| Skills | Jira, Confluence |

**Use cases**:
- Review agent decisions
- Validate proposed solutions
- Ensure quality standards
- Document findings

**Example**:
```
@reviewer Review the triage assessment for ticket ESD-12345
```

## Web Interface

Access the Playground at `/app/#playground` in the Atlas web UI.

### Features

- **Agent Selection**: Click agent cards to switch between agents
- **Chat Interface**: Real-time streaming responses with tool call visibility
- **Session Management**: Sessions persist across page reloads
- **Configuration Panel**: Adjust model, temperature, and enabled skills
- **Usage Stats**: View token usage and costs per session

### Chat Commands

Type messages directly to chat with the selected agent. Messages are processed in real-time with streaming responses.

**Tool Calls**: When an agent uses a skill (like searching Jira), you'll see tool call indicators showing which tools are being used.

## API Reference

### List Agents

```http
GET /api/playground/agents
```

**Response**:
```json
[
  {
    "id": "triage",
    "name": "Triage Agent",
    "role": "Ticket categorization specialist",
    "description": "Analyzes incoming tickets...",
    "skills": ["jira", "confluence"],
    "default_model": "claude-haiku-4-5-20251001",
    "default_temperature": 0.3
  }
]
```

### Get Agent Details

```http
GET /api/playground/agents/{agent_id}
```

### Create/Get Session

```http
POST /api/playground/sessions
Content-Type: application/json

{
  "agent_id": "triage"
}
```

**Response**:
```json
{
  "session_id": "abc123",
  "agent_id": "triage",
  "created_at": "2026-01-18T12:00:00Z"
}
```

### Chat with Agent (Streaming)

```http
POST /api/playground/chat
Content-Type: application/json

{
  "session_id": "abc123",
  "agent_id": "triage",
  "message": "Show new tickets for Systems team",
  "config": {
    "model": "claude-haiku-4-5-20251001",
    "temperature": 0.3,
    "enabled_skills": ["jira", "confluence"]
  }
}
```

**Response**: Server-Sent Events (SSE) stream

```
event: message_start
data: {"type": "message_start", "data": {}}

event: tool_start
data: {"type": "tool_start", "data": {"tool": "jira_search"}}

event: tool_end
data: {"type": "tool_end", "data": {"tool": "jira_search", "duration_ms": 245}}

event: message_delta
data: {"type": "message_delta", "data": {"content": "I found 5 new tickets..."}}

event: message_end
data: {"type": "message_end", "data": {"input_tokens": 1200, "output_tokens": 350}}
```

### Get Session History

```http
GET /api/playground/sessions/{session_id}/messages
```

### Get Usage Statistics

```http
GET /api/admin/playground/usage?days=30
```

**Response**:
```json
{
  "total_requests": 150,
  "total_input_tokens": 45000,
  "total_output_tokens": 12000,
  "total_tokens": 57000,
  "total_cost_usd": 0.0234,
  "avg_duration_ms": 2500,
  "period_days": 30
}
```

### Get Recent Activity

```http
GET /api/admin/playground/usage/recent?limit=20
```

## Configuration

### Environment Variables

```bash
# Required: Anthropic API key for Claude models
ANTHROPIC_API_KEY=sk-ant-your-key

# Optional: Default model override
PLAYGROUND_DEFAULT_MODEL=claude-haiku-4-5-20251001
```

### Model Options

| Model | ID | Best For |
|-------|----|----|
| Haiku 4.5 | `claude-haiku-4-5-20251001` | Fast, cost-effective responses |
| Sonnet 4.5 | `claude-sonnet-4-5-20250929` | Balanced performance |
| Opus 4.5 | `claude-opus-4-5-20251101` | Complex reasoning tasks |

### Per-Session Configuration

Override defaults per chat session:

```json
{
  "model": "claude-sonnet-4-5-20250929",
  "temperature": 0.5,
  "max_tokens": 4096,
  "enabled_skills": ["jira", "netbox", "zabbix"]
}
```

## Usage Tracking

The Playground tracks comprehensive usage metrics for monitoring and cost analysis.

### Tracked Metrics

- **Per-Request**: Session ID, agent ID, model, tokens (input/output), cost, duration, tool calls
- **Per-User**: Username, client (web/telegram/slack/teams), request counts
- **Per-Agent**: Usage by agent type, popular agents

### Database Tables

- `playground_sessions`: Session metadata and configuration
- `playground_usage`: Per-request usage logs with full details

### Admin Dashboard

Access usage analytics at `/app/#admin` → **Playground** tab:

- **Overview Cards**: Total requests, tokens, costs, unique users
- **Users Table**: Per-user usage breakdown
- **Recent Activity**: Live log of recent requests with client, agent, model, tokens, cost

### Cost Calculation

Costs are calculated based on model pricing:

| Model | Input (per 1M) | Output (per 1M) |
|-------|----------------|-----------------|
| Haiku 4.5 | $1.00 | $5.00 |
| Sonnet 4.5 | $3.00 | $15.00 |
| Opus 4.5 | $15.00 | $75.00 |

## CLI Commands

### Quick Test

```bash
# Chat with an agent from CLI (requires API server running)
curl -X POST http://localhost:8000/api/playground/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ATLAS_API_TOKEN" \
  -d '{
    "agent_id": "triage",
    "message": "Hello, what can you help with?"
  }'
```

### Check Usage

```bash
# Get usage statistics
curl http://localhost:8000/api/admin/playground/usage?days=7 \
  -H "Authorization: Bearer $ATLAS_API_TOKEN"
```

## Integration with Bots

The Playground runtime powers bot integrations. When users chat via Telegram, Slack, or Teams, their messages are routed through the same Playground infrastructure:

- Bot messages use the same agent system
- Usage is tracked with the `client` field indicating the source platform
- Sessions are maintained per conversation

See [Bot System Documentation](bots.md) for details on configuring platform bots.

## Troubleshooting

### Agent Not Responding

1. Check `ANTHROPIC_API_KEY` is set
2. Verify API server is running: `uv run atlas api serve`
3. Check logs for errors: `LOG_LEVEL=debug uv run atlas api serve`

### Tool Calls Failing

1. Verify skill dependencies are configured (Jira, NetBox, etc.)
2. Check module status: `uv run atlas modules status`
3. Ensure required environment variables are set

### High Costs

1. Use Haiku model for simple queries
2. Limit enabled skills to reduce context size
3. Start new sessions periodically to clear history

## Related Documentation

- [Atlas Agents Platform](atlas_agents_platform.md) - Full workflow orchestration
- [AI Chat System](ai-chat.md) - Multi-provider AI chat
- [Bot System](bots.md) - Telegram, Slack, Teams integration
- [Skills System](atlas_agents_platform.md#skills) - Available skill integrations
