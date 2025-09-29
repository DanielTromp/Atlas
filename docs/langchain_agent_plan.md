# LangChain Migration Plan

This document tracks progress on the LangChain agent refactor. We will pause after each major milestone for review before moving to the next step.

## High-Level Migration Plan

- **Introduce LangChain layer**
  - Add an `enreach_tools/agents/` package (shared helpers, router, domain agents)
  - Use LangChain `AgentExecutor` instances with deterministic prompts and AMS timezone formatting
- **Tool wrappers**
  - Wrap existing integrations as LangChain Tools with clean schemas, retries, and secret redaction
  - Resolve credentials server-side only (env + existing secret store)
- **Chat variables**
  - Accept and persist optional `variables` per session
  - Inject into router/domain prompts and tool parameter resolution under `context.vars`
- **Agent execution path**
  - Route chat requests via RouterAgent → DomainAgent → Tool chain
  - Maintain concise responses, map timestamps to Europe/Amsterdam (CET/CEST)
- **Tools catalogue & samples**
  - Keep `/tools` endpoint for the UI, but surface agent-backed descriptions and examples
  - “Run sample” triggers the same agent/tool workflow as chat
- **Testing & validation**
  - Add router dispatch tests and domain happy paths
  - Document configuration notes and ensure no secrets reach the frontend

- [x] **Step 1 – Tool Wrappers**
  - Implement LangChain `Tool` abstractions for each backend (Zabbix, NetBox, Jira, Confluence, Export, Admin)
  - Enforce credential loading and error normalization inside the wrappers
  - Add timeout/retry policies and redact secrets in logs

- [x] **Step 2 – Agents**
  - Build RouterAgent and domain-specific AgentExecutors
  - Wire prompts with deterministic tone (temp 0.2) and AMS timezone handling
  - Inject chat variables into agent context under `context.vars`

- [x] **Step 3 – Chat & Catalogue Integration**
  - Extend `/chat` endpoints to accept/persist `variables`
  - Route chat messages through the Router → Domain agent flow
  - Update `/tools` catalogue and “Run sample” to call agents instead of raw fetches
  - Ensure UI continues working without changes to UX

- [x] **Step 4 – Tests & Validation**
  - Add router dispatch tests and one happy-path per domain agent
  - Cover chat variable propagation and tool summaries
  - Document configuration/setup changes

We will check in after each step before proceeding.
