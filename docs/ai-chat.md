# Atlas AI Chat System

The Atlas AI Chat system provides a modular, multi-provider AI assistant that can interact with your infrastructure through natural language. It supports multiple AI providers, tool calling for infrastructure operations, and provides a flexible architecture for future extensions.

## Features

- **Multi-Provider Support**: Azure OpenAI, OpenAI, Anthropic (Claude), OpenRouter, Google Gemini
- **Per-Agent Configuration**: Each chat agent can use a different provider/model
- **Tool Calling**: Integrate AI with NetBox, Zabbix, Jira, Confluence, vCenter
- **Slash Commands**: Quick actions with `/help`, `/tools`, `/models`, etc.
- **Chat History**: Persistent conversation storage with timestamps
- **Streaming**: Real-time response streaming for better UX
- **Admin Console**: Configure providers, test connections, manage agents

## Table of Contents

1. [Provider Setup](#provider-setup)
2. [Configuration](#configuration)
3. [Token Limits](#token-limits)
4. [API Usage](#api-usage)
5. [Slash Commands](#slash-commands)
6. [Tool Calling](#tool-calling)
7. [Usage Tracking](#usage-tracking)
8. [Admin Operations](#admin-operations)
9. [Extending the System](#extending-the-system)

---

## Provider Setup

### Azure OpenAI

Azure OpenAI provides enterprise-grade access to OpenAI models with enhanced security and compliance.

**Required Environment Variables:**

```bash
# Azure OpenAI Configuration
AZURE_OPENAI_API_KEY=your-api-key-here
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=your-deployment-name
AZURE_OPENAI_API_VERSION=2024-08-01-preview  # Optional, defaults to this

# Optional
AZURE_OPENAI_DEFAULT_MODEL=gpt-4o-mini
```

**Setup Steps:**

1. Create an Azure OpenAI resource in the Azure Portal
2. Deploy a model (e.g., gpt-4o-mini, gpt-4o)
3. Copy the endpoint URL and API key from the "Keys and Endpoint" section
4. Note the deployment name you created

**Supported Models:**
- gpt-4o (128K context, vision support)
- gpt-4o-mini (128K context, cost-effective)
- gpt-4-turbo (128K context)
- gpt-4 (8K context)
- gpt-35-turbo (16K context)

---

### OpenAI (Direct)

Use OpenAI's API directly for access to the latest models.

**Required Environment Variables:**

```bash
OPENAI_API_KEY=sk-your-api-key-here

# Optional
OPENAI_DEFAULT_MODEL=gpt-4o-mini
```

**Setup Steps:**

1. Create an account at [platform.openai.com](https://platform.openai.com)
2. Navigate to API Keys and create a new key
3. Add billing information to enable API access

**Supported Models:**
- gpt-4o, gpt-4o-mini
- gpt-4-turbo, gpt-4
- gpt-3.5-turbo
- o1-preview, o1-mini (reasoning models)

---

### Anthropic (Claude)

Access Claude models for their strong reasoning and analysis capabilities.

**Required Environment Variables:**

```bash
ANTHROPIC_API_KEY=sk-ant-your-api-key-here

# Optional
ANTHROPIC_DEFAULT_MODEL=claude-3-5-sonnet-20241022
```

**Setup Steps:**

1. Create an account at [console.anthropic.com](https://console.anthropic.com)
2. Navigate to API Keys and generate a new key
3. Add billing information

**Supported Models:**
- claude-3-5-sonnet-20241022 (latest, recommended)
- claude-3-5-haiku-20241022 (fast, cost-effective)
- claude-3-opus-20240229 (most capable)
- claude-3-sonnet-20240229
- claude-3-haiku-20240307

---

### OpenRouter

OpenRouter provides access to multiple AI providers through a single API, great for testing and fallback scenarios.

**Required Environment Variables:**

```bash
OPENROUTER_API_KEY=sk-or-v1-your-api-key-here

# Optional
OPENROUTER_DEFAULT_MODEL=openrouter/auto
OPENROUTER_REFERRER=https://your-app.com
OPENROUTER_TITLE=Infrastructure Atlas
```

**Setup Steps:**

1. Create an account at [openrouter.ai](https://openrouter.ai)
2. Generate an API key from the dashboard
3. Add credits to your account

**Popular Models:**
- `openrouter/auto` (automatic model selection)
- `openai/gpt-4o`, `openai/gpt-4o-mini`
- `anthropic/claude-3.5-sonnet`
- `google/gemini-pro-1.5`
- `meta-llama/llama-3.1-405b-instruct`
- `mistralai/mistral-large`

---

### Google Gemini

Access Google's Gemini models with very large context windows.

**Required Environment Variables:**

```bash
GOOGLE_API_KEY=your-api-key-here
# or
GEMINI_API_KEY=your-api-key-here

# Optional
GEMINI_DEFAULT_MODEL=gemini-1.5-flash
```

**Setup Steps:**

1. Go to [makersuite.google.com](https://makersuite.google.com) or Google Cloud Console
2. Create a new API key
3. Enable the Generative Language API

**Supported Models:**
- gemini-2.0-flash-exp (latest experimental)
- gemini-1.5-pro (2M context window)
- gemini-1.5-flash (1M context, fast)
- gemini-1.5-flash-8b (cost-effective)

---

## Configuration

### Environment Variables Summary

Add these to your `.env` file:

```bash
# ===========================================
# AI Chat Configuration
# ===========================================

# Azure OpenAI (Primary - Recommended for Enterprise)
AZURE_OPENAI_API_KEY=your-key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-4o-mini
AZURE_OPENAI_API_VERSION=2024-08-01-preview

# OpenAI Direct (Fallback)
OPENAI_API_KEY=sk-your-key

# Anthropic/Claude (Alternative)
ANTHROPIC_API_KEY=sk-ant-your-key

# OpenRouter (Multi-model access)
OPENROUTER_API_KEY=sk-or-v1-your-key

# Google Gemini
GOOGLE_API_KEY=your-key

# Default Settings
CHAT_DEFAULT_PROVIDER=azure_openai
CHAT_DEFAULT_MODEL=gpt-4o-mini
CHAT_DEFAULT_TEMPERATURE=0.7
```

### Database Migration

Run the database migration to enable AI chat features:

```bash
uv run alembic upgrade head
```

This creates tables for:
- `ai_provider_configs` - Provider configurations
- `ai_agent_configs` - Agent configurations
- `ai_activity_logs` - Usage tracking and activity logs
- `ai_model_configs` - Custom model configurations and pricing
- Enhanced `chat_sessions` with provider/model tracking
- Enhanced `chat_messages` with tool call metadata

---

## Token Limits

### Understanding Token Limits

There are two types of token limits to understand:

1. **Max Output Tokens**: The maximum length of the AI's response (configurable)
2. **Context Window**: The total input tokens the model can process (model-dependent)

### Configuring Max Output Tokens

The default max tokens is **16,384**. You can adjust this in:

**Admin UI**: Go to **Admin → AI Settings** and modify "Max Tokens"

**API Request**: Override per-request:

```bash
curl -X POST http://localhost:8000/ai/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Write a detailed report...",
    "max_tokens": 32000
  }'
```

**Valid Range**: 100 - 128,000 tokens

### Context Window Limits by Model

Different models have different context window sizes:

| Model | Context Window | Notes |
|-------|---------------|-------|
| GPT-4 Turbo | 128K tokens | Recommended for long conversations |
| GPT-4o / GPT-4o-mini | 128K tokens | Latest OpenAI models |
| GPT-5 Mini (OpenRouter) | 128K tokens | Cost-effective |
| Claude 3.5 Sonnet | 200K tokens | Largest context |
| Claude 3 Opus | 200K tokens | Most capable |
| Gemini 1.5 Pro | 2M tokens | Extremely large context |
| Gemini 1.5 Flash | 1M tokens | Fast with large context |
| GPT-3.5 Turbo | 16K tokens | Smaller context |

### Token Usage Monitoring

Each message shows token usage:
- **Prompt tokens**: Input context size (your messages + history)
- **Completion tokens**: Response length
- **Total tokens**: Combined usage
- **Cost**: Estimated cost in USD

### Truncation Warning

If the AI's response is cut off due to token limits, you'll see a warning:

> ⚠️ Response truncated due to token limit. You can increase max tokens in Admin → AI Settings.

**Solutions:**
1. Increase max tokens in Admin → AI Settings
2. Start a new chat session to clear context
3. Use a model with larger context window

### Best Practices

1. **Monitor prompt tokens**: If consistently high (50K+), consider starting a new chat
2. **Set appropriate max tokens**: Higher for detailed responses, lower for quick queries
3. **Use efficient prompts**: Be concise to preserve context window space
4. **Clear history**: Use `/clear` command to reset conversation context

---

## API Usage

### Create a Chat Session

```bash
curl -X POST http://localhost:8000/ai/sessions \
  -H "Content-Type: application/json" \
  -d '{"title": "Infrastructure Check", "provider": "azure_openai", "model": "gpt-4o-mini"}'
```

### Send a Message (Streaming)

```bash
curl -X POST http://localhost:8000/ai/chat/stream \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Show me all critical Zabbix alerts",
    "session_id": "ai_abc123",
    "provider": "azure_openai",
    "tools_enabled": true
  }'
```

### Send a Message (Non-Streaming)

```bash
curl -X POST http://localhost:8000/ai/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Search for server webprod01 in NetBox",
    "session_id": "ai_abc123"
  }'
```

### List Available Providers

```bash
curl http://localhost:8000/ai/providers
```

### Test a Provider

```bash
curl -X POST http://localhost:8000/ai/providers/azure_openai/test
```

### Get System Status

```bash
curl http://localhost:8000/ai/status
```

---

## Slash Commands

Type these commands in the chat for quick actions:

| Command | Description | Example |
|---------|-------------|---------|
| `/help` | Show all available commands | `/help` or `/help tools` |
| `/tools` | List available AI tools | `/tools` or `/tools monitoring` |
| `/models` | List models for current provider | `/models` or `/models anthropic` |
| `/providers` | Show configured providers | `/providers` |
| `/agent` | View/change agent configuration | `/agent set model=gpt-4o` |
| `/clear` | Clear conversation history | `/clear` |
| `/history` | Show conversation summary | `/history 10` |
| `/usage` | Show token usage statistics | `/usage` |
| `/search` | Quick search across all systems | `/search webserver01` |
| `/alerts` | Show Zabbix alerts | `/alerts high 10` |
| `/status` | Show Atlas system status | `/status` |
| `/settings` | View/modify chat settings | `/settings temperature=0.5` |
| `/export` | Export conversation | `/export json` |

---

## Tool Calling

The AI can automatically call tools to gather information from your infrastructure:

### Available Tool Categories

#### Inventory Tools
- **netbox_search**: Search devices, VMs, IPs in NetBox

#### Monitoring Tools
- **zabbix_alerts**: Get current alerts and problems
- **zabbix_host_search**: Search for hosts by name
- **zabbix_group_search**: Search for host groups (to get group IDs for filtering)

#### Issue Tracking
- **jira_search**: Search Jira issues

#### Documentation
- **confluence_search**: Search wiki pages

#### Virtualization
- **vcenter_list_instances**: List vCenter instances
- **vcenter_get_vms**: Get VMs from vCenter

#### Search
- **search_aggregate**: Search across all systems at once

#### Admin
- **monitoring_stats**: Get token usage statistics
- **performance_metrics**: Get system performance

### Example Tool Interactions

**User:** "What are the current critical alerts for the production servers?"

**AI:**
1. Calls `zabbix_alerts` with severity filter
2. Presents formatted results

**User:** "Find information about server web-prod-01"

**AI:**
1. Calls `search_aggregate` for comprehensive search
2. Shows results from NetBox, Zabbix, Jira, Confluence

---

## Usage Tracking

The AI chat system includes comprehensive usage tracking for monitoring costs, analyzing patterns, and auditing API usage.

### Admin UI - AI Usage Tab

Access via **Admin → AI Usage** to see:

- **Dashboard**: Total requests, tokens, costs, and trends
- **Model Configs**: Custom pricing and model configurations
- **Pricing Reference**: Built-in pricing for common models

### Admin UI - API Activity Tab

Access via **Admin → API Activity** for detailed logs:

- **Activity Log**: All AI API calls with timestamps
- **Filters**: Filter by provider, model, date range
- **Export**: Download activity as CSV

### Tracked Metrics

Each API call logs:
- Provider and model used
- Token counts (prompt, completion, reasoning)
- Cost calculation (USD)
- Generation time (ms)
- Finish reason (stop, length, etc.)
- Session ID for grouping conversations
- User ID for attribution

### API Endpoints

**Get Dashboard Statistics:**

```bash
curl http://localhost:8000/api/ai-usage/dashboard \
  -H "Authorization: Bearer $ATLAS_API_TOKEN"
```

**Get Activity Logs:**

```bash
curl "http://localhost:8000/api/ai-usage/activity?limit=50" \
  -H "Authorization: Bearer $ATLAS_API_TOKEN"
```

**Export to CSV:**

```bash
curl "http://localhost:8000/api/ai-usage/activity/export?days=30" \
  -H "Authorization: Bearer $ATLAS_API_TOKEN" \
  -o activity.csv
```

**Get/Update Model Pricing:**

```bash
# List custom model configs
curl http://localhost:8000/api/ai-usage/models \
  -H "Authorization: Bearer $ATLAS_API_TOKEN"

# Add/update custom pricing
curl -X POST http://localhost:8000/api/ai-usage/models \
  -H "Authorization: Bearer $ATLAS_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "openrouter",
    "model": "custom/model",
    "display_name": "Custom Model",
    "price_input_per_million": 1.50,
    "price_output_per_million": 2.00
  }'
```

### Cost Calculation

Costs are calculated using:
1. Custom model configs (if defined)
2. Built-in pricing table for common models
3. Provider API pricing data (when available)

Formula: `cost = (prompt_tokens × input_price + completion_tokens × output_price) / 1,000,000`

---

## Admin Operations

### Provider Testing

Test each provider's connectivity and response time:

```bash
# Test Azure OpenAI
curl -X POST http://localhost:8000/ai/providers/azure_openai/test

# Test all providers
for provider in azure_openai openai anthropic openrouter gemini; do
  echo "Testing $provider..."
  curl -s -X POST http://localhost:8000/ai/providers/$provider/test | jq
done
```

### View System Status

```bash
curl http://localhost:8000/ai/status | jq
```

Response includes:
- Provider status (configured, connected, response times)
- Available tools count
- Default configuration

### List Available Models

```bash
# For a specific provider
curl http://localhost:8000/ai/providers/azure_openai/models

# All tools
curl http://localhost:8000/ai/tools
```

---

## Extending the System

### Adding a New Provider

1. Create a new provider class in `src/infrastructure_atlas/ai/providers/`:

```python
from .base import AIProvider

class MyCustomProvider(AIProvider):
    provider_name = "my_provider"
    
    async def complete(self, messages, **kwargs):
        # Implementation
        pass
    
    async def stream(self, messages, **kwargs):
        # Implementation
        pass
    
    async def test_connection(self):
        # Test and return status
        pass
    
    def list_models(self):
        return [{"id": "model-1", "name": "Model 1"}]
```

2. Register in `providers/registry.py`:

```python
from .my_provider import MyCustomProvider

PROVIDER_CLASSES[ProviderType.MY_PROVIDER] = MyCustomProvider
```

3. Add environment configuration in `_config_from_env()`.

### Adding a New Tool

1. Add definition in `src/infrastructure_atlas/ai/tools/definitions.py`:

```python
ToolDefinition(
    name="my_custom_tool",
    description="Description for the AI",
    parameters={
        "type": "object",
        "properties": {
            "param1": {"type": "string", "description": "Parameter description"},
        },
        "required": ["param1"],
    },
    category="custom",
)
```

2. Add API mapping in `tools/registry.py`:

```python
self._api_mappings["my_custom_tool"] = {
    "method": "GET",
    "endpoint": "/my-endpoint",
    "params": ["param1"],
}
```

### Adding a New Slash Command

1. Add definition in `src/infrastructure_atlas/ai/commands/definitions.py`:

```python
CommandDefinition(
    name="mycommand",
    description="What it does",
    usage="/mycommand [args]",
    examples=["/mycommand example"],
)
```

2. Add handler in `commands/handler.py`:

```python
async def _cmd_mycommand(self, args: list[str]) -> CommandResult:
    # Implementation
    return CommandResult(True, "Response message")
```

---

## Security Considerations

1. **API Keys**: Store all API keys in environment variables or secure settings, never in code
2. **Rate Limiting**: The system includes rate limiting to prevent abuse
3. **Tool Permissions**: Tools execute via the Atlas API with proper authentication
4. **User Sessions**: Chat sessions are associated with authenticated users
5. **Audit Logging**: All AI interactions are logged for auditing

---

## Troubleshooting

### Provider Connection Issues

```bash
# Check provider status
curl http://localhost:8000/ai/status

# Verify environment variables
env | grep -E "(AZURE|OPENAI|ANTHROPIC|OPENROUTER|GOOGLE|GEMINI)"
```

### Tool Execution Failures

Check that the Atlas API is running and accessible:

```bash
curl http://localhost:8000/health
```

Verify tool API endpoints are working:

```bash
curl http://localhost:8000/zabbix/problems?limit=5
curl http://localhost:8000/netbox/search?q=test
```

### Database Migration Issues

```bash
# Check current migration state
uv run alembic current

# Upgrade to latest
uv run alembic upgrade head

# Rollback if needed
uv run alembic downgrade -1
```

---

## Quick Start Example

1. Set up Azure OpenAI (minimum configuration):

```bash
export AZURE_OPENAI_API_KEY="<your_api_key>"
export AZURE_OPENAI_ENDPOINT="https://dt-openai.openai.azure.com/"
export AZURE_OPENAI_DEPLOYMENT="gpt-4o-mini"
```

2. Run the migration:

```bash
uv run alembic upgrade head
```

3. Start the server:

```bash
uv run atlas api serve
```

4. Test the AI chat:

```bash
curl -X POST http://localhost:8000/ai/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello, what can you help me with?"}'
```

5. Try with tools:

```bash
curl -X POST http://localhost:8000/ai/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Show me the available tools", "tools_enabled": true}'
```

