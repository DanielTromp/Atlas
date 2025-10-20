from __future__ import annotations

from dataclasses import dataclass

import pytest

from infrastructure_atlas.agents.context import AgentContext
from infrastructure_atlas.agents.router import RouterAgent


@dataclass
class _StubMessage:
    content: str


class _StubLLM:
    def __init__(self, response: str) -> None:
        self._response = response
        self.invocations: list[list] = []

    def bind(self) -> _StubLLM:
        return self

    def invoke(self, messages, *args, **kwargs):
        self.invocations.append(messages)
        return _StubMessage(self._response)


@pytest.mark.parametrize(("tool_hint", "expected_domain"), [
    ("jira_issue_search", "jira"),
    ("zabbix_current_alerts", "zabbix"),
])
def test_router_respects_tool_hint(tool_hint: str, expected_domain: str) -> None:
    router = RouterAgent(_StubLLM("{}"))
    decision = router.route("anything", AgentContext(), tool_hint=tool_hint)
    assert decision.domain == expected_domain
    assert decision.tool_key == tool_hint


def test_router_llm_routing_includes_context() -> None:
    llm = _StubLLM('{"domain": "netbox", "reason": "context"}')
    router = RouterAgent(llm)
    context = AgentContext(session_id="c-1", user="alice", variables={"datasetPref": "devices"})

    decision = router.route("List NetBox devices", context)

    assert decision.domain == "netbox"
    assert len(llm.invocations) == 1
    messages = llm.invocations[0]
    assert messages, "router should send messages to the LLM"
    human_content = messages[-1].content
    assert "context.vars" in human_content
    assert "datasetPref" in human_content


def test_router_fallback_to_heuristics_when_llm_unparsable() -> None:
    llm = _StubLLM("not json")
    router = RouterAgent(llm)
    context = AgentContext()

    decision = router.route("Show current Zabbix alerts", context)

    assert decision.domain == "zabbix"
    assert decision.reason.startswith("Keyword")
