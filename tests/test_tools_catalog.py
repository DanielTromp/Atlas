from __future__ import annotations

import asyncio

from starlette.requests import Request

from enreach_tools.interfaces.api.routes import tools as tools_router


async def _empty_receive():
    return {"type": "http.request", "body": b"", "more_body": False}


def _make_request() -> Request:
    scope = {"type": "http", "method": "GET", "path": "/", "headers": []}
    request = Request(scope, _empty_receive)
    request.state.user = None
    return request


def test_tool_catalog_includes_agent_metadata() -> None:
    catalog = asyncio.run(tools_router.list_tools(_make_request()))
    assert catalog.tools, "expected at least one tool definition"

    zabbix = next(tool for tool in catalog.tools if tool.key == "zabbix_current_alerts")
    assert zabbix.agent == "zabbix"
    assert "Zabbix agent" in zabbix.description
    assert zabbix.sample == {"limit": 50, "include_subgroups": True}

    limit_param = next(param for param in zabbix.parameters if param.name == "limit")
    assert limit_param.location == "body"
    assert limit_param.type == "integer"
    assert limit_param.default == 300
    assert not limit_param.required


def test_tool_catalog_detail_lookup() -> None:
    detail = asyncio.run(tools_router.get_tool("netbox_live_search", _make_request()))
    assert detail.agent == "netbox"
    assert "inventory" in detail.summary.lower()
    assert detail.examples
    assert detail.path.endswith("/tools/netbox_live_search/sample")
