"""Router agent that selects an appropriate domain agent."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from textwrap import dedent

from langchain_core.language_models import BaseLanguageModel
from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate

from .context import AgentContext
from .domains import DOMAIN_SPECS, DomainSpec

__all__ = ["RouterAgent", "RouterDecision", "build_router_agent"]


@dataclass(frozen=True)
class RouterDecision:
    domain: str
    reason: str
    tool_key: str | None = None


class RouterAgent:
    """Select the most appropriate domain agent for a user instruction."""

    def __init__(
        self,
        llm: BaseLanguageModel,
        domains: Sequence[DomainSpec] | None = None,
    ) -> None:
        self._llm = self._configure_llm(llm)
        self._domains = tuple(domains or DOMAIN_SPECS)
        self._domain_index: Mapping[str, DomainSpec] = {spec.key: spec for spec in self._domains}
        tool_map: dict[str, str] = {}
        for spec in self._domains:
            for tool_key in spec.tool_keys:
                tool_map[tool_key] = spec.key
        self._tool_domains = tool_map
        self._prompt = self._build_prompt()

    def _configure_llm(self, llm: BaseLanguageModel) -> BaseLanguageModel:
        binder = getattr(llm, "bind", None)
        if callable(binder):
            try:
                return binder()
            except Exception:
                pass
        return llm

    def _build_prompt(self) -> ChatPromptTemplate:
        lines = ["You are the RouterAgent. Choose the best domain for the request."]
        lines.append("Return a JSON object with fields: domain, reason, tool_key (optional).")
        lines.append("Domains: " + ", ".join(f"{spec.key} ({spec.label})" for spec in self._domains))
        lines.append("If uncertain, pick the closest domain and explain why.")
        lines.append("Never invent new domains or tools.")

        system_prompt = "\n".join(lines)

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", system_prompt),
                (
                    "human",
                    dedent(
                        """
                        User message:
                        {message}

                        Tool hint: {tool_hint}
                        Chat variables:
                        {context_block}

                        Available tools by domain:
                        {domain_catalogue}
                        """
                    ).strip(),
                ),
            ]
        )
        return prompt

    def route(
        self,
        message: str,
        context: AgentContext,
        tool_hint: str | None = None,
    ) -> RouterDecision:
        if tool_hint and tool_hint in self._tool_domains:
            domain = self._tool_domains[tool_hint]
            return RouterDecision(
                domain=domain,
                reason=f"Tool hint '{tool_hint}' maps to domain {domain}",
                tool_key=tool_hint,
            )

        prompt_value = self._prompt.format_prompt(
            message=message,
            tool_hint=tool_hint or "(none)",
            context_block=context.as_prompt_fragment(),
            domain_catalogue=self._format_catalogue(),
        )
        response = self._llm.invoke(prompt_value.to_messages())
        decision = self._parse_response(response)
        if decision is not None:
            return decision
        # Fallback heuristic when parsing failed
        return self._heuristic_route(message, tool_hint)

    def _format_catalogue(self) -> str:
        rows: list[str] = []
        for spec in self._domains:
            tools = ", ".join(spec.tool_keys) if spec.tool_keys else "(domain-defined)"
            rows.append(f"- {spec.key}: tools = {tools}")
        return "\n".join(rows)

    def _parse_response(self, response: BaseMessage | None) -> RouterDecision | None:
        if response is None:
            return None
        content = str(getattr(response, "content", "")).strip()
        if not content:
            return None
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            # Some models wrap JSON in text blocks; try to extract
            try:
                start = content.index("{")
                end = content.rindex("}") + 1
                data = json.loads(content[start:end])
            except Exception:
                return None
        if not isinstance(data, dict):
            return None
        domain = str(data.get("domain") or "").strip().lower()
        if domain not in self._domain_index:
            return None
        reason = str(data.get("reason") or "Chosen by router").strip()
        tool_key = data.get("tool_key") or data.get("tool")
        tool_value = str(tool_key).strip() if isinstance(tool_key, str) else None
        if tool_value and tool_value not in self._tool_domains:
            tool_value = None
        return RouterDecision(domain=domain, reason=reason, tool_key=tool_value)

    def _heuristic_route(self, message: str, tool_hint: str | None) -> RouterDecision:
        text = (message or "").lower()
        mapping: tuple[tuple[str, str], ...] = (
            ("alert", "zabbix"),
            ("zabbix", "zabbix"),
            ("netbox", "netbox"),
            ("inventory", "netbox"),
            ("jira", "jira"),
            ("ticket", "jira"),
            ("incident", "jira"),
            ("confluence", "confluence"),
            ("runbook", "confluence"),
            ("backup", "admin"),
            ("user", "admin"),
        )
        for keyword, domain in mapping:
            if keyword in text:
                return RouterDecision(
                    domain=domain,
                    reason=f"Keyword '{keyword}' matched heuristics",
                    tool_key=tool_hint if tool_hint in self._tool_domains else None,
                )
        # Default to Jira for general operational chatter
        return RouterDecision(
            domain="jira",
            reason="Fallback domain",
            tool_key=tool_hint if tool_hint in self._tool_domains else None,
        )


def build_router_agent(llm: BaseLanguageModel) -> RouterAgent:
    return RouterAgent(llm)
