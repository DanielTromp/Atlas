from __future__ import annotations

from types import SimpleNamespace

from enreach_tools.agents.context import AgentContext
from enreach_tools.api.app import _apply_chat_variables


def test_agent_context_prompt_fragment_formats_variables() -> None:
    ctx = AgentContext(session_id="c-42", user="ops", variables={"b": 2, "a": "x"})

    fragment = ctx.as_prompt_fragment()

    assert "session.id = c-42" in fragment
    assert "session.user = ops" in fragment
    assert 'context.vars = {"a": "x", "b": 2}' in fragment


def test_apply_chat_variables_merges_and_prunes() -> None:
    session = SimpleNamespace(context_variables={"timezone": "UTC", "defaultTeam": "Ops"})

    result = _apply_chat_variables(
        session,
        {"timezone": "Europe/Amsterdam", "defaultTeam": None, "datasetPref": "devices"},
    )

    assert result == {"timezone": "Europe/Amsterdam", "datasetPref": "devices"}
    assert session.context_variables == result
