# Feature Request: Bridge AI Chat and Playground Systems

**Created:** 2026-01-24
**Priority:** Medium
**Status:** Proposed

## Summary

AI Chat and Playground are currently separate systems with independent tool/agent architectures. Users expect Playground agents (like `@triage`, `@ops`) to be accessible from AI Chat, but they operate on different underlying systems.

## Current Architecture

### AI Chat (`/api/ai/*`)

- **Location:** `src/infrastructure_atlas/ai/`
- **Providers:** OpenAI, Azure OpenAI, Anthropic, Gemini, OpenRouter, Claude Code
- **Tool System:** `ai/tools/definitions.py` - 40+ tools defined as `ToolDefinition` objects
- **Execution:** HTTP API calls via `ToolRegistry._api_mappings`
- **Roles:** `triage`, `engineer`, `general` (filter available tools)

**Tools include:**
- Infrastructure: `netbox_search`, `atlas_host_info`, `atlas_host_context`
- Monitoring: `zabbix_alerts`, `zabbix_host_search`, `commvault_backup_status`
- Ticketing: `jira_search`, `jira_create_issue`, `jira_update_issue`, `jira_add_comment`
- Documentation: `confluence_search`, `search_confluence_docs`, `confluence_create_page`
- Virtualization: `vcenter_list_instances`, `vcenter_get_vms`
- Export: `export_to_xlsx`

### Playground (`/api/playground/*`)

- **Location:** `src/infrastructure_atlas/agents/playground/`
- **Backend:** LangChain with ReAct pattern
- **Agents:** `@triage`, `@ops`, and others defined in `AVAILABLE_AGENTS`
- **Tool System:** Skills via `SkillsRegistry` in `src/infrastructure_atlas/skills/`
- **Execution:** Direct Python function calls with autonomous reasoning

**Agents include:**
- `@triage` - Fast host lookups and issue triage
- `@ops` - Operations-focused with expanded tool access

## The Gap

| Aspect | AI Chat | Playground |
|--------|---------|------------|
| Architecture | Multi-provider, stateless tools | LangChain, stateful agents |
| Tool Definition | OpenAI function format | LangChain Tool objects |
| Execution Model | Request → Tool → Response | ReAct loop with reasoning |
| User Expectation | "Use @triage agent" | Works natively |

**User Impact:** When users try to invoke Playground agents from AI Chat (e.g., "use @triage to check server X"), AI Chat doesn't have access to these agents. It has similar tools but not the same agent abstraction.

## Proposed Solutions

### Option 1: Expose Playground Agents as AI Chat Tools (Recommended)

Create a bridge that exposes Playground agents as callable tools in AI Chat:

```python
# ai/tools/definitions.py
ToolDefinition(
    name="invoke_agent",
    description="Invoke a specialized agent for complex tasks",
    parameters={
        "type": "object",
        "properties": {
            "agent": {
                "type": "string",
                "enum": ["triage", "ops"],
                "description": "Agent to invoke"
            },
            "task": {
                "type": "string",
                "description": "Task description for the agent"
            }
        },
        "required": ["agent", "task"]
    }
)
```

**Pros:**
- Minimal changes to AI Chat
- Preserves Playground agent capabilities
- Users can explicitly invoke agents

**Cons:**
- Adds latency (nested agent calls)
- Token usage increases

### Option 2: Unify Tool Systems

Refactor both systems to share a common tool registry:

```python
# infrastructure/tools/unified_registry.py
class UnifiedToolRegistry:
    """Shared registry for both AI Chat and Playground"""

    def register_tool(self, tool: UnifiedTool): ...
    def get_tools_for_provider(self, provider: str): ...
    def get_tools_for_langchain(self): ...
```

**Pros:**
- Single source of truth
- Consistent capabilities across systems
- Easier maintenance

**Cons:**
- Significant refactoring effort
- Risk of breaking existing functionality

### Option 3: Agent Routing in AI Chat

Add agent detection to AI Chat that routes to Playground when needed:

```python
# In chat completion handler
if message.startswith("@") or "use agent" in message.lower():
    # Route to Playground agent
    return await invoke_playground_agent(agent_name, message)
```

**Pros:**
- Seamless user experience
- No explicit tool invocation needed

**Cons:**
- Complex routing logic
- Potential for misrouting

## Implementation Plan (Option 1)

1. **Create Agent Bridge Tool** - New tool in `ai/tools/definitions.py`
2. **Add API Endpoint** - `/api/playground/invoke` that accepts agent name and task
3. **Register Handler** - In `ToolRegistry._api_mappings`
4. **Update System Prompt** - Inform AI about available agents
5. **Test Integration** - Verify agent invocation from AI Chat

### Estimated Effort

- Option 1: ~2-3 days
- Option 2: ~1-2 weeks
- Option 3: ~3-5 days

## Acceptance Criteria

- [ ] Users can invoke Playground agents from AI Chat
- [ ] Agent responses are properly streamed back
- [ ] Token usage is tracked for nested calls
- [ ] Error handling covers agent failures
- [ ] Documentation updated

## Related Files

- `src/infrastructure_atlas/ai/tools/definitions.py` - AI Chat tool definitions
- `src/infrastructure_atlas/ai/tools/registry.py` - Tool execution registry
- `src/infrastructure_atlas/agents/playground/` - Playground agents
- `src/infrastructure_atlas/skills/` - Skills registry
- `src/infrastructure_atlas/interfaces/api/routes/ai_chat.py` - AI Chat API
- `src/infrastructure_atlas/interfaces/api/routes/playground.py` - Playground API

## References

- AI Chat roles: `AGENT_ROLES` in `ai/tools/definitions.py`
- Playground agents: `AVAILABLE_AGENTS` in `agents/playground/`
- Tool execution: `ToolRegistry.execute()` in `ai/tools/registry.py`
