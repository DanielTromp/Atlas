# Feature Request: Unify AI Chat with Playground Agents

**Created:** 2026-01-24
**Updated:** 2026-01-24
**Priority:** High
**Status:** Open

## Summary

Replace AI Chat's tool-based approach with Playground's agent-based approach. Users should get the full power of Playground agents (@ops, @triage, etc.) directly in AI Chat, with the ability to select providers and models.

## Requirements

1. **Default agent**: `@ops` (fast, operations-focused)
2. **Provider selection**: Keep current provider dropdown (Anthropic, OpenAI, Gemini, etc.)
3. **Model dropdown**: Show all models available from the selected provider
4. **Agent selection**: Allow switching between @ops, @triage, @engineer, etc.

## Current Architecture

### AI Chat (`/api/ai/*`)

- **Providers:** OpenAI, Azure OpenAI, Anthropic, Gemini, OpenRouter, Claude Code
- **Tool System:** 40+ tools defined as HTTP API calls
- **Execution:** Direct LLM calls with tool definitions
- **Roles:** `triage`, `engineer`, `general` (filter tools, not true agents)

### Playground (`/api/playground/*`)

- **Backend:** LangChain with ChatAnthropic
- **Agents:** @ops, @triage, @engineer (true ReAct agents)
- **Skills:** Full skill integration (jira, netbox, zabbix, vcenter, confluence, export)
- **Execution:** Agent loop with reasoning

## Proposed Changes

### 1. Add Model Lists to Providers

Each provider should expose its available models:

```python
# Already exists in AnthropicProvider
MODELS = {
    "claude-opus-4-5-20251101": {"context_window": 200000, "max_output": 16384},
    "claude-sonnet-4-5-20250929": {"context_window": 200000, "max_output": 16384},
    "claude-haiku-4-5-20251001": {"context_window": 200000, "max_output": 16384},
}

def list_models(self) -> list[dict[str, Any]]:
    """List available models."""
    return [{"id": model_id, "name": model_id, ...} for model_id in self.MODELS]
```

**Action:** Add MODELS dict to all providers:
- `OpenAIProvider` - gpt-4o, gpt-4o-mini, gpt-4-turbo, etc.
- `GeminiProvider` - gemini-1.5-pro, gemini-1.5-flash, etc.
- `OpenRouterProvider` - Dynamic from API or common models
- `AzureOpenAIProvider` - From deployment configuration

### 2. API Endpoint for Provider Models

```python
# interfaces/api/routes/ai_chat.py
@router.get("/providers/{provider}/models")
async def get_provider_models(provider: str):
    """Get available models for a provider."""
    registry = get_provider_registry()
    p = registry.get_provider(provider)
    return {"models": p.list_models()}
```

### 3. Make Playground Runtime Provider-Agnostic

Currently Playground hardcodes ChatAnthropic. Make it use the selected provider:

```python
# agents/playground.py
class PlaygroundRuntime:
    def __init__(
        self,
        agent_id: str = "ops",
        provider: str = "anthropic",  # NEW
        model: str | None = None,     # NEW - if None, use agent default
        ...
    ):
        self.provider = provider
        self.model = model or self._get_agent_default_model(agent_id)
```

### 4. Update AI Chat to Use Playground

Replace AI Chat's direct LLM calls with PlaygroundRuntime:

```python
# interfaces/api/routes/ai_chat.py
@router.post("/chat")
async def chat_completion(request: ChatRequest):
    runtime = PlaygroundRuntime(
        agent_id=request.agent or "ops",
        provider=request.provider,
        model=request.model,
        skills_registry=get_skills_registry(),
    )

    async for event in runtime.chat(request.messages[-1].content, session_id):
        yield event.to_sse()
```

### 5. Frontend Changes

```javascript
// Update AI Chat UI
const providerSelect = document.getElementById('ai-provider');
const modelSelect = document.getElementById('ai-model');
const agentSelect = document.getElementById('ai-agent');  // NEW

// When provider changes, fetch models
providerSelect.addEventListener('change', async () => {
    const models = await fetch(`/ai/providers/${providerSelect.value}/models`);
    modelSelect.innerHTML = models.map(m => `<option value="${m.id}">${m.name}</option>`);
});

// Agent options
const AGENTS = [
    { id: 'ops', name: '@ops', description: 'Fast operations queries' },
    { id: 'triage', name: '@triage', description: 'Ticket triage and analysis' },
    { id: 'engineer', name: '@engineer', description: 'Deep technical investigation' },
];
```

## Provider Model Lists

### Anthropic (Already Done)
```python
MODELS = {
    "claude-opus-4-5-20251101": {...},
    "claude-sonnet-4-5-20250929": {...},
    "claude-haiku-4-5-20251001": {...},
}
```

### OpenAI (To Add)
```python
MODELS = {
    "gpt-4o": {"context_window": 128000},
    "gpt-4o-mini": {"context_window": 128000},
    "gpt-4-turbo": {"context_window": 128000},
    "gpt-4": {"context_window": 8192},
    "gpt-3.5-turbo": {"context_window": 16385},
}
```

### Gemini (To Add)
```python
MODELS = {
    "gemini-1.5-pro": {"context_window": 1000000},
    "gemini-1.5-flash": {"context_window": 1000000},
    "gemini-1.0-pro": {"context_window": 32000},
}
```

## Implementation Plan

### Phase 1: Add Model Lists to Providers
1. Add `MODELS` dict to each provider
2. Ensure `list_models()` method exists on all providers
3. Add `/ai/providers/{provider}/models` endpoint

### Phase 2: Make Playground Provider-Agnostic
1. Abstract LLM instantiation in PlaygroundRuntime
2. Add provider/model parameters
3. Support LangChain wrappers for each provider (langchain-openai, langchain-google-genai, etc.)

### Phase 3: Update AI Chat API
1. Add `agent` parameter to chat endpoint
2. Route to PlaygroundRuntime instead of direct LLM
3. Maintain streaming support

### Phase 4: Update Frontend
1. Add model dropdown that updates on provider change
2. Add agent selector (default: @ops)
3. Update chat request to include agent/provider/model

## Benefits

- **Unified experience**: Same agents in Playground and AI Chat
- **Full skills access**: All tools available through skills
- **Provider flexibility**: Use any configured provider
- **Model selection**: Choose appropriate model for task
- **Consistent behavior**: No more confusion about tools vs skills

## Related Files

- `src/infrastructure_atlas/ai/providers/*.py` - Add MODELS to each
- `src/infrastructure_atlas/ai/providers/registry.py` - Provider management
- `src/infrastructure_atlas/agents/playground.py` - Make provider-agnostic
- `src/infrastructure_atlas/interfaces/api/routes/ai_chat.py` - Route to Playground
- `src/infrastructure_atlas/api/static/app.js` - Frontend updates

## Acceptance Criteria

- [ ] All providers expose list of available models
- [ ] `/ai/providers/{provider}/models` endpoint works
- [ ] AI Chat uses PlaygroundRuntime with selected agent
- [ ] Default agent is @ops
- [ ] Model dropdown updates when provider changes
- [ ] Streaming continues to work
- [ ] Usage tracking preserved
