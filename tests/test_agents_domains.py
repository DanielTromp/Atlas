from __future__ import annotations

from collections.abc import Callable, Iterable
from unittest.mock import patch

import pytest

from enreach_tools.agents import AgentContext
from enreach_tools.agents.admin import ADMIN_TOOL_KEYS, build_admin_agent
from enreach_tools.agents.confluence import CONFLUENCE_TOOL_KEYS, build_confluence_agent
from enreach_tools.agents.export import EXPORT_TOOL_KEYS, build_export_agent
from enreach_tools.agents.jira import JIRA_TOOL_KEYS, build_jira_agent
from enreach_tools.agents.netbox import NETBOX_TOOL_KEYS, build_netbox_agent
from enreach_tools.agents.zabbix import ZABBIX_TOOL_KEYS, build_zabbix_agent

BuilderFunc = Callable[[object, AgentContext, dict[str, object]], object]


def _registry(keys: Iterable[str]) -> dict[str, object]:
    return {key: object() for key in keys}


@pytest.mark.parametrize(
    ("builder", "tool_keys", "agent_name", "instruction_fragment"),
    [
        (build_zabbix_agent, ZABBIX_TOOL_KEYS, "Zabbix Agent", "host group"),
        (build_netbox_agent, NETBOX_TOOL_KEYS, "NetBox Agent", "inventory"),
        (build_jira_agent, JIRA_TOOL_KEYS, "Jira Agent", "Jira"),
        (build_confluence_agent, CONFLUENCE_TOOL_KEYS, "Confluence Agent", "runbooks"),
        (build_export_agent, EXPORT_TOOL_KEYS, "Export Agent", "data export"),
        (build_admin_agent, ADMIN_TOOL_KEYS, "Admin Agent", "administrative operations"),
    ],
)
def test_domain_agent_builders_pass_configuration(
    builder: BuilderFunc,
    tool_keys: tuple[str, ...],
    agent_name: str,
    instruction_fragment: str,
) -> None:
    llm = object()
    context = AgentContext(session_id="c-1", user="ops", variables={"datasetPref": "devices"})
    tools = _registry(tool_keys)
    captured: dict[str, object] = {}

    def _fake_executor(llm_arg, config, ctx):
        captured["llm"] = llm_arg
        captured["config"] = config
        captured["context"] = ctx
        return "executor"

    module_path = builder.__module__
    with patch(f"{module_path}.build_agent_executor", side_effect=_fake_executor):
        result = builder(llm, context, tools)

    assert result == "executor"
    assert captured["llm"] is llm
    assert captured["context"] is context

    config = captured["config"]
    assert config.name == agent_name
    assert instruction_fragment in config.instructions
    expected_tools = [tools[key] for key in tool_keys if key in tools]
    assert list(config.tools) == expected_tools
