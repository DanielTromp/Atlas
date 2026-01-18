# Atlas Agents Platform

The Atlas Agents Platform is a multi-agent DevOps automation system that enables intelligent workflow orchestration with human-in-the-loop capabilities. It integrates with infrastructure systems (Jira, Zabbix, NetBox, Confluence, vCenter) to automate common operations tasks.

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [API Reference](#api-reference)
- [Workflows](#workflows)
- [Skills](#skills)
- [Worker Agents](#worker-agents)
- [Examples](#examples)

## Overview

The platform provides:

- **Workflow Engine**: LangGraph-based orchestration with state management and checkpointing
- **Worker Agents**: Specialized AI agents (Triage, Engineer, Reviewer) for different tasks
- **Skills System**: Pluggable integrations with infrastructure tools
- **Human-in-the-Loop**: Pause workflows for human approval before destructive actions
- **Real-time Updates**: WebSocket notifications for workflow progress

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        API Layer                                │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────────┐ │
│  │  /workflows │  │ /executions  │  │ /ws/executions/{id}     │ │
│  └─────────────┘  └──────────────┘  └─────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────────┐
│                     Workflow Engine                             │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────────┐ │
│  │ StateGraph  │  │ Checkpointer │  │  Human Interrupts       │ │
│  └─────────────┘  └──────────────┘  └─────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────────┐
│                      Worker Agents                              │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────────────┐ │
│  │TriageAgent  │  │EngineerAgent │  │    ReviewerAgent        │ │
│  └─────────────┘  └──────────────┘  └─────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────────┐
│                        Skills Layer                             │
│  ┌───────┐ ┌────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐  │
│  │ Jira  │ │ Zabbix │ │  NetBox  │ │Confluence│ │  vCenter   │  │
│  └───────┘ └────────┘ └──────────┘ └──────────┘ └────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## Quick Start

### 1. Database Migration

The platform tables are created automatically via Alembic migration:

```bash
uv run alembic upgrade head
```

### 2. Start the API Server

```bash
uv run atlas api serve --host 127.0.0.1 --port 8000
```

### 3. Create a Workflow

```bash
curl -X POST http://localhost:8000/workflows \
  -H "Authorization: Bearer $ATLAS_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "ESD Ticket Triage",
    "description": "Automated triage for infrastructure tickets",
    "trigger_type": "manual",
    "graph_definition": {
      "nodes": ["fetch_ticket", "triage", "enrich"],
      "edges": [
        {"from": "fetch_ticket", "to": "triage"},
        {"from": "triage", "to": "enrich"}
      ]
    },
    "visual_definition": {
      "nodes": [
        {"id": "fetch_ticket", "position": {"x": 100, "y": 100}},
        {"id": "triage", "position": {"x": 300, "y": 100}},
        {"id": "enrich", "position": {"x": 500, "y": 100}}
      ]
    }
  }'
```

### 4. Execute the Workflow

```bash
curl -X POST http://localhost:8000/workflows/{workflow_id}/execute \
  -H "Authorization: Bearer $ATLAS_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "trigger_data": {
      "ticket_key": "ESD-12345"
    }
  }'
```

### 5. Monitor via WebSocket

```javascript
const ws = new WebSocket('ws://localhost:8000/ws/executions/{execution_id}');

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('Update:', data.type, data);
};
```

## API Reference

### Workflows

#### List Workflows
```http
GET /workflows?is_active=true&trigger_type=manual&limit=50&offset=0
```

#### Create Workflow
```http
POST /workflows
Content-Type: application/json

{
  "name": "My Workflow",
  "description": "Description of the workflow",
  "trigger_type": "manual|webhook|schedule|event",
  "trigger_config": {},
  "graph_definition": {...},
  "visual_definition": {...}
}
```

#### Get Workflow
```http
GET /workflows/{workflow_id}
```

#### Update Workflow
```http
PUT /workflows/{workflow_id}
Content-Type: application/json

{
  "name": "Updated Name",
  "is_active": false
}
```

#### Delete Workflow
```http
DELETE /workflows/{workflow_id}
```

#### Execute Workflow
```http
POST /workflows/{workflow_id}/execute
Content-Type: application/json

{
  "trigger_data": {"key": "value"},
  "initial_state": {}
}
```

#### List Workflow Executions
```http
GET /workflows/{workflow_id}/executions?status=running&limit=20
```

### Executions

#### List All Executions
```http
GET /executions?workflow_id={id}&status=running&limit=20&offset=0
```

#### Get Execution Details
```http
GET /executions/{execution_id}
```

Response includes:
- Current status and node
- All execution steps
- Pending human intervention (if any)

#### Get Execution Steps
```http
GET /executions/{execution_id}/steps?limit=100&offset=0
```

#### Get Execution State
```http
GET /executions/{execution_id}/state
```

#### Resume Execution (after human intervention)
```http
POST /executions/{execution_id}/resume
Content-Type: application/json

{
  "decision": "approve|modify|reject",
  "feedback": "Optional feedback message",
  "modifications": {"key": "modified_value"}
}
```

#### Cancel Execution
```http
POST /executions/{execution_id}/cancel
```

#### Get Interventions
```http
GET /executions/{execution_id}/interventions
```

### WebSocket

Connect to receive real-time updates:

```
ws://localhost:8000/ws/executions/{execution_id}
```

#### Message Types

**Server → Client:**

```json
// Initial state
{"type": "init", "status": "running", "current_node": "triage", ...}

// Status change
{"type": "status", "status": "waiting_human", "timestamp": "..."}

// Step completion
{"type": "step", "step": {"node_id": "triage", "status": "completed"}, ...}

// Human intervention required
{"type": "intervention", "intervention": {"prompt": "Approve action?", ...}}

// Error
{"type": "error", "message": "Something went wrong"}

// Execution complete
{"type": "complete", "summary": {...}}

// Keepalive
{"type": "ping"}
```

**Client → Server:**

```json
// Keepalive response
{"type": "pong"}

// Request state refresh
{"type": "refresh"}
```

## Workflows

### Workflow Definition

A workflow consists of:

- **Nodes**: Processing steps (functions)
- **Edges**: Connections between nodes
- **Conditional Edges**: Dynamic routing based on state
- **Interrupt Points**: Where to pause for human input

### Built-in Nodes

Located in `workflows/nodes.py`:

| Node | Description |
|------|-------------|
| `fetch_ticket` | Fetch Jira ticket details |
| `triage` | Classify and prioritize ticket |
| `enrich` | Add context from NetBox, Zabbix, Confluence |
| `investigate` | Deep investigation with tools |
| `review` | Review proposed actions |
| `wait_for_human` | Pause for human approval |
| `apply_actions` | Execute approved actions |
| `finalize` | Complete and update ticket |

### ESD Triage Workflow

The built-in ESD Triage workflow (`workflows/definitions/esd_triage.py`):

```
fetch_ticket → triage → enrich → investigate? → review → wait_for_human → apply_actions → finalize
```

#### Usage

```python
from infrastructure_atlas.workflows.definitions.esd_triage import create_esd_triage_workflow
from infrastructure_atlas.workflows.engine import WorkflowEngine

engine = WorkflowEngine()
workflow = create_esd_triage_workflow(engine)

# Execute
execution_id = engine.execute(
    workflow_id="esd-triage",
    trigger_type="manual",
    trigger_data={"ticket_key": "ESD-12345"}
)

# Check state
state = engine.get_state(execution_id)
print(f"Status: {state['status']}, Node: {state['current_node']}")

# Resume after human approval
engine.resume(execution_id, {"decision": "approve"})
```

### Creating Custom Workflows

```python
from infrastructure_atlas.workflows.engine import WorkflowEngine
from infrastructure_atlas.workflows.state import WorkflowState

def my_custom_node(state: WorkflowState) -> dict:
    """Custom processing node."""
    # Access state
    ticket = state.get("ticket")

    # Do processing
    result = process_something(ticket)

    # Return state updates
    return {
        "custom_data": result,
        "messages": [{"role": "assistant", "content": f"Processed: {result}"}]
    }

def should_continue(state: WorkflowState) -> str:
    """Conditional routing."""
    if state.get("needs_review"):
        return "review"
    return "finalize"

# Build workflow
engine = WorkflowEngine()
engine.register_node("my_node", my_custom_node)

workflow = engine.compile_workflow(
    workflow_id="my-workflow",
    nodes=["fetch_ticket", "my_node", "review", "finalize"],
    edges=[
        ("fetch_ticket", "my_node"),
        ("review", "finalize"),
    ],
    conditional_edges=[
        ("my_node", should_continue, {"review": "review", "finalize": "finalize"})
    ],
    interrupt_before=["review"]  # Pause for human approval
)
```

## Skills

Skills provide tool capabilities to agents. Each skill wraps an external system.

### Available Skills

#### JiraSkill

```python
from infrastructure_atlas.skills.jira import JiraSkill

skill = JiraSkill()
skill.initialize()

# Get issue
result = skill.execute("get_issue", {"issue_key": "ESD-12345"})

# Search issues
result = skill.execute("search_issues", {
    "jql": "project = ESD AND status = Open",
    "max_results": 20
})

# Update issue
result = skill.execute("update_issue", {
    "issue_key": "ESD-12345",
    "fields": {"priority": {"name": "High"}}
})

# Add comment
result = skill.execute("add_comment", {
    "issue_key": "ESD-12345",
    "body": "Investigation complete. Root cause identified."
})

# Transition issue
result = skill.execute("transition_issue", {
    "issue_key": "ESD-12345",
    "transition_name": "In Progress"
})

# Assign issue
result = skill.execute("assign_issue", {
    "issue_key": "ESD-12345",
    "assignee": "john.doe"
})

# Find similar issues
result = skill.execute("get_similar_issues", {
    "issue_key": "ESD-12345",
    "max_results": 5
})
```

#### ZabbixSkill

```python
from infrastructure_atlas.skills.zabbix import ZabbixSkill

skill = ZabbixSkill()
skill.initialize()

# Get host details
result = skill.execute("get_host", {"host_id": "10084"})

# Search hosts
result = skill.execute("search_hosts", {
    "pattern": "web-*",
    "limit": 50
})

# Get current problems/alerts
result = skill.execute("get_problems", {
    "min_severity": 3,  # Average and above
    "unacknowledged_only": True,
    "hours": 24,
    "limit": 100
})

# Get problems for specific host
result = skill.execute("get_host_problems", {
    "host_id": "10084",
    "min_severity": 2
})

# Acknowledge a problem
result = skill.execute("acknowledge_problem", {
    "event_id": "12345",
    "message": "Investigating issue"
})

# Get interfaces by IP
result = skill.execute("get_interfaces", {
    "ip_address": "192.168.1.100"
})
```

#### NetBoxSkill

```python
from infrastructure_atlas.skills.netbox import NetBoxSkill

skill = NetBoxSkill()
skill.initialize()

# Get device by ID
result = skill.execute("get_device", {"device_id": 123})

# Get VM by ID
result = skill.execute("get_vm", {"vm_id": 456})

# Search devices
result = skill.execute("search_devices", {
    "pattern": "srv-db-.*",
    "limit": 50
})

# Search VMs
result = skill.execute("search_vms", {
    "pattern": "vm-web-.*",
    "limit": 50
})

# List devices with filters
result = skill.execute("list_devices", {
    "site": "DC1",
    "role": "server",
    "status": "active",
    "limit": 100
})

# List VMs with filters
result = skill.execute("list_vms", {
    "cluster": "prod-cluster",
    "status": "active",
    "limit": 100
})

# Get device by exact name
result = skill.execute("get_device_by_name", {"name": "srv-db-01"})

# Get VM by exact name
result = skill.execute("get_vm_by_name", {"name": "vm-web-01"})
```

#### ConfluenceSkill

```python
from infrastructure_atlas.skills.confluence import ConfluenceSkill

skill = ConfluenceSkill()
skill.initialize()

# Semantic search
result = skill.execute("search", {
    "query": "how to restart database service",
    "top_k": 10,
    "min_score": 0.3,
    "include_citations": True
})

# Get specific page
result = skill.execute("get_page", {"page_id": "123456"})

# Find runbooks for a topic
result = skill.execute("find_runbook", {
    "topic": "database failover",
    "top_k": 5
})

# Search within specific space
result = skill.execute("search_by_space", {
    "query": "deployment procedure",
    "space_key": "OPS",
    "top_k": 10
})

# Find related pages
result = skill.execute("get_related_pages", {
    "page_id": "123456",
    "top_k": 5
})
```

#### VCenterSkill

```python
from infrastructure_atlas.skills.vcenter import VCenterSkill

skill = VCenterSkill()
skill.initialize()

# Get VM details
result = skill.execute("get_vm", {
    "vm_name": "web-server-01",
    "config_id": "optional-vcenter-id"
})

# Search VMs
result = skill.execute("search_vms", {
    "pattern": "db-.*",
    "limit": 50
})

# List all VMs from a vCenter
result = skill.execute("list_vms", {
    "config_id": "vcenter-prod",
    "power_state": "POWERED_ON",
    "limit": 100
})

# List configured vCenters
result = skill.execute("list_vcenter_configs", {})

# Find VM by IP
result = skill.execute("get_vm_by_ip", {
    "ip_address": "192.168.1.50"
})

# Quick power state check
result = skill.execute("get_vm_power_state", {
    "vm_name": "web-server-01"
})
```

### Using Skills with Agents

Skills are automatically loaded by the SkillsRegistry:

```python
from infrastructure_atlas.skills.registry import get_skills_registry

# Get the global registry
registry = get_skills_registry()

# Auto-discover all skills
registry.auto_discover_skills()

# Initialize all skills
registry.initialize_all()

# Get all tools for an agent
tools = registry.get_all_tools()

# Get tools from specific skills
tools = registry.get_tools_by_names(["jira", "zabbix"])

# Execute skill action directly
jira = registry.get("jira")
result = jira.execute("get_issue", {"issue_key": "ESD-123"})
```

### Creating Custom Skills

```python
from infrastructure_atlas.skills.base import BaseSkill
from infrastructure_atlas.infrastructure.logging import get_logger

logger = get_logger(__name__)

class MyCustomSkill(BaseSkill):
    name = "my_skill"
    description = "My custom integration"
    category = "custom"

    def initialize(self) -> None:
        """Register actions."""
        self.register_action(
            name="do_something",
            func=self._do_something,
            description="Perform a custom action",
            is_destructive=False,
        )

        self.register_action(
            name="dangerous_action",
            func=self._dangerous_action,
            description="Action requiring confirmation",
            is_destructive=True,
            requires_confirmation=True,
        )

    def _do_something(self, param1: str, param2: int = 10) -> dict:
        """Implementation of the action."""
        try:
            result = external_api_call(param1, param2)
            return {"success": True, "data": result}
        except Exception as e:
            logger.error(f"Action failed: {e}")
            return {"success": False, "error": str(e)}

    def _dangerous_action(self, target: str) -> dict:
        """Destructive action that needs approval."""
        # This will be marked for human review in workflows
        result = perform_destructive_operation(target)
        return {"success": True, "result": result}
```

Place in `skills/my_skill/skill.py` with an `__init__.py` for auto-discovery.

## Worker Agents

### TriageAgent

Classifies and prioritizes tickets:

```python
from infrastructure_atlas.agents.workers.triage import TriageAgent
from infrastructure_atlas.skills.registry import get_skills_registry

registry = get_skills_registry()
registry.auto_discover_skills()
registry.initialize_all()

agent = TriageAgent(skills_registry=registry)

result = agent.process({
    "ticket": {
        "key": "ESD-12345",
        "summary": "Database connection timeouts",
        "description": "Users reporting slow queries..."
    }
})

print(f"Priority: {result.get('priority')}")
print(f"Category: {result.get('category')}")
print(f"Reasoning: {result.get('triage_reasoning')}")
```

### EngineerAgent

Investigates and proposes solutions:

```python
from infrastructure_atlas.agents.workers.engineer import EngineerAgent

agent = EngineerAgent(skills_registry=registry)

result = agent.process({
    "ticket": {...},
    "triage_result": {...},
    "enrichment_data": {...}
})

print(f"Root Cause: {result.get('root_cause')}")
print(f"Proposed Actions: {result.get('proposed_actions')}")
```

### ReviewerAgent

Reviews proposed actions before execution:

```python
from infrastructure_atlas.agents.workers.reviewer import ReviewerAgent

agent = ReviewerAgent(skills_registry=registry)

result = agent.process({
    "ticket": {...},
    "proposed_actions": [...],
    "investigation_notes": "..."
})

print(f"Approved: {result.get('review_approved')}")
print(f"Feedback: {result.get('review_feedback')}")
print(f"Risk Assessment: {result.get('risk_assessment')}")
```

## Examples

### Example 1: Automated Ticket Triage

```python
import asyncio
from infrastructure_atlas.workflows.definitions.esd_triage import create_esd_triage_workflow
from infrastructure_atlas.workflows.engine import WorkflowEngine
from infrastructure_atlas.skills.registry import get_skills_registry

async def triage_ticket(ticket_key: str):
    # Initialize
    registry = get_skills_registry()
    registry.auto_discover_skills()
    registry.initialize_all()

    engine = WorkflowEngine()
    workflow = create_esd_triage_workflow(engine)

    # Execute
    execution_id = engine.execute(
        workflow_id="esd-triage",
        trigger_type="manual",
        trigger_data={"ticket_key": ticket_key}
    )

    # Wait for completion or human intervention
    while True:
        state = engine.get_state(execution_id)

        if state["status"] == "completed":
            print("Triage complete!")
            break
        elif state["status"] == "waiting_human":
            print("Waiting for approval...")
            # In production, this would be handled via API
            engine.resume(execution_id, {"decision": "approve"})
        elif state["status"] == "failed":
            print(f"Failed: {state.get('error')}")
            break

        await asyncio.sleep(1)

asyncio.run(triage_ticket("ESD-12345"))
```

### Example 2: Monitoring Alert Response

```python
from infrastructure_atlas.skills.zabbix import ZabbixSkill
from infrastructure_atlas.skills.jira import JiraSkill
from infrastructure_atlas.skills.confluence import ConfluenceSkill

def respond_to_alert(event_id: str):
    zabbix = ZabbixSkill()
    jira = JiraSkill()
    confluence = ConfluenceSkill()

    for skill in [zabbix, jira, confluence]:
        skill.initialize()

    # Get alert details
    problems = zabbix.execute("get_problems", {"limit": 100})
    alert = next((p for p in problems["problems"] if p["event_id"] == event_id), None)

    if not alert:
        return {"error": "Alert not found"}

    # Find relevant runbook
    runbooks = confluence.execute("find_runbook", {
        "topic": alert["name"],
        "top_k": 3
    })

    # Create Jira ticket
    ticket = jira.execute("create_issue", {
        "project": "ESD",
        "summary": f"[Alert] {alert['name']} on {alert['host_name']}",
        "description": f"""
## Alert Details
- **Host**: {alert['host_name']}
- **Severity**: {alert['severity_name']}
- **Duration**: {alert['duration']}

## Relevant Runbooks
{chr(10).join(f"- [{r['title']}]({r['url']})" for r in runbooks.get('runbooks', []))}
        """,
        "issue_type": "Incident"
    })

    # Acknowledge alert
    zabbix.execute("acknowledge_problem", {
        "event_id": event_id,
        "message": f"Ticket created: {ticket.get('key')}"
    })

    return {"ticket": ticket.get("key"), "runbooks": runbooks}
```

### Example 3: Infrastructure Lookup

```python
from infrastructure_atlas.skills.netbox import NetBoxSkill
from infrastructure_atlas.skills.vcenter import VCenterSkill
from infrastructure_atlas.skills.zabbix import ZabbixSkill

def get_host_info(hostname: str):
    """Get comprehensive info about a host from all systems."""
    netbox = NetBoxSkill()
    vcenter = VCenterSkill()
    zabbix = ZabbixSkill()

    for skill in [netbox, vcenter, zabbix]:
        skill.initialize()

    info = {"hostname": hostname}

    # Check NetBox (physical device)
    device = netbox.execute("get_device_by_name", {"name": hostname})
    if device.get("success"):
        info["netbox"] = device["device"]
        info["type"] = "physical"
    else:
        # Check NetBox (VM)
        vm = netbox.execute("get_vm_by_name", {"name": hostname})
        if vm.get("success"):
            info["netbox"] = vm["vm"]
            info["type"] = "virtual"

    # Check vCenter for VMs
    if info.get("type") == "virtual":
        vcenter_vm = vcenter.execute("get_vm", {"vm_name": hostname})
        if vcenter_vm.get("success"):
            info["vcenter"] = vcenter_vm["vm"]

    # Check Zabbix for monitoring
    hosts = zabbix.execute("search_hosts", {"pattern": hostname, "limit": 1})
    if hosts.get("success") and hosts["hosts"]:
        host = hosts["hosts"][0]
        info["zabbix"] = host

        # Get current problems
        problems = zabbix.execute("get_host_problems", {"host_id": host["id"]})
        if problems.get("success"):
            info["active_problems"] = problems["problems"]

    return info

# Usage
info = get_host_info("web-server-01")
print(f"Type: {info.get('type')}")
print(f"IP: {info.get('netbox', {}).get('primary_ip')}")
print(f"Active Problems: {len(info.get('active_problems', []))}")
```

### Example 4: Bulk VM Status Check

```python
from infrastructure_atlas.skills.vcenter import VCenterSkill

def check_vm_status(pattern: str):
    """Check status of VMs matching a pattern."""
    vcenter = VCenterSkill()
    vcenter.initialize()

    # Search for VMs
    result = vcenter.execute("search_vms", {"pattern": pattern, "limit": 100})

    if not result.get("success"):
        return {"error": result.get("error")}

    # Categorize by power state
    powered_on = []
    powered_off = []
    other = []

    for vm in result["vms"]:
        state = vm.get("power_state", "").upper()
        if state == "POWERED_ON":
            powered_on.append(vm["name"])
        elif state == "POWERED_OFF":
            powered_off.append(vm["name"])
        else:
            other.append({"name": vm["name"], "state": state})

    return {
        "total": len(result["vms"]),
        "powered_on": len(powered_on),
        "powered_off": len(powered_off),
        "other": len(other),
        "details": {
            "on": powered_on,
            "off": powered_off,
            "other": other
        }
    }

# Usage
status = check_vm_status("db-.*")
print(f"Total: {status['total']}")
print(f"Running: {status['powered_on']}")
print(f"Stopped: {status['powered_off']}")
```

## Environment Variables

Required for skills:

```bash
# Jira/Confluence
ATLASSIAN_BASE_URL=https://your-instance.atlassian.net
ATLASSIAN_EMAIL=your-email@example.com
ATLASSIAN_API_TOKEN=your-api-token

# Zabbix
ZABBIX_API_URL=https://zabbix.example.com/api_jsonrpc.php
ZABBIX_API_TOKEN=your-api-token
ZABBIX_WEB_URL=https://zabbix.example.com  # Optional

# NetBox
NETBOX_URL=https://netbox.example.com
NETBOX_TOKEN=your-api-token

# vCenter (configured via database/UI)
# Individual vCenter credentials stored in secret store

# AI Provider
ANTHROPIC_API_KEY=your-anthropic-key
```

## Troubleshooting

### Skills Not Loading

Check that environment variables are set:

```bash
uv run python -c "
from infrastructure_atlas.skills.registry import get_skills_registry
registry = get_skills_registry()
count = registry.auto_discover_skills()
print(f'Loaded {count} skills')
for s in registry.list_skills():
    print(f'  - {s[\"name\"]}: {len(s[\"actions\"])} actions')
"
```

### Workflow Stuck

Check execution state:

```bash
curl http://localhost:8000/executions/{execution_id} \
  -H "Authorization: Bearer $ATLAS_API_TOKEN" | jq
```

### WebSocket Not Connecting

Ensure the execution exists and check logs:

```bash
LOG_LEVEL=debug uv run atlas api serve
```
