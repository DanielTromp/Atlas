"""Utility helpers for constructing agent toolsets."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from langchain_core.tools import BaseTool

__all__ = ["select_tools"]


def select_tools(registry: Mapping[str, BaseTool], keys: Iterable[str]) -> list[BaseTool]:
    """Return tools matching the provided keys, preserving order."""

    selected: list[BaseTool] = []
    for key in keys:
        tool = registry.get(key)
        if tool is not None:
            selected.append(tool)
    return selected
