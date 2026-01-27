"""Registry for LangChain tool instances used by agents."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from langchain_core.tools import BaseTool

from infrastructure_atlas.infrastructure.tools import (
    AdminBackupStatusTool,
    AdminConfigSurveyTool,
    ConfluenceAppendToPageTool,
    ConfluenceConvertMarkdownTool,
    ConfluenceCreatePageTool,
    ConfluenceDeletePageTool,
    ConfluenceGetPageByTitleTool,
    ConfluenceGetPageTool,
    ConfluenceSearchTool,
    ConfluenceUpdatePageTool,
    DraftTicketCreateTool,
    DraftTicketGetTool,
    DraftTicketListTool,
    DraftTicketSearchTool,
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
        "confluence_get_page_content": ConfluenceGetPageTool,
        "confluence_get_page_by_title": ConfluenceGetPageByTitleTool,
        "confluence_update_page": ConfluenceUpdatePageTool,
        "confluence_create_page": ConfluenceCreatePageTool,
        "confluence_append_to_page": ConfluenceAppendToPageTool,
        "confluence_convert_markdown_to_storage": ConfluenceConvertMarkdownTool,
        "confluence_delete_page": ConfluenceDeletePageTool,
        "admin_config_overview": AdminConfigSurveyTool,
        "admin_backup_status": AdminBackupStatusTool,
        "ticket_list": DraftTicketListTool,
        "ticket_create": DraftTicketCreateTool,
        "ticket_get": DraftTicketGetTool,
        "ticket_search": DraftTicketSearchTool,
    }
    return {key: factory() for key, factory in factories.items()}
