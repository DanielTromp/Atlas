"""Registry for LangChain tool instances used by agents."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from langchain_core.tools import BaseTool

from enreach_tools.infrastructure.tools import (
    AdminBackupStatusTool,
    AdminConfigSurveyTool,
    ConfluenceSearchTool,
    ExportRunTool,
    ExportStatusTool,
    JiraSearchTool,
    NetboxSearchTool,
    ZabbixGroupSearchTool,
    ZabbixHistoryTool,
    ZabbixProblemsTool,
)

__all__ = ["ToolFactory", "build_tool_registry"]

ToolFactory = Callable[[], BaseTool]


def build_tool_registry() -> dict[str, BaseTool]:
    """Instantiate all first-party tools and return them in a keyed mapping."""

    factories: Mapping[str, ToolFactory] = {
        "zabbix_current_alerts": ZabbixProblemsTool,
        "zabbix_history_search": ZabbixHistoryTool,
        "zabbix_group_search": ZabbixGroupSearchTool,
        "netbox_live_search": NetboxSearchTool,
        "jira_issue_search": JiraSearchTool,
        "confluence_search": ConfluenceSearchTool,
        "export_run_job": ExportRunTool,
        "export_status_overview": ExportStatusTool,
        "admin_config_overview": AdminConfigSurveyTool,
        "admin_backup_status": AdminBackupStatusTool,
    }
    return {key: factory() for key, factory in factories.items()}
