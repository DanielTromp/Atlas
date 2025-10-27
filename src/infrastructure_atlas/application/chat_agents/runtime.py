"""Utilities for executing the LangChain agent stack inside chat flows."""

from __future__ import annotations

import copy
import json
import os
import re
from collections.abc import Mapping, Sequence
from contextlib import nullcontext
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Literal

try:
    from langchain_classic.agents import AgentExecutor
except ImportError:
    # Fallback for older langchain versions
    try:
        from langchain.agents import AgentExecutor
    except ImportError:
        from langchain.agents.agent import AgentExecutor
from langchain_core.language_models import BaseLanguageModel

from infrastructure_atlas.agents import (
    DOMAIN_SPECS,
    AgentContext,
    RouterAgent,
    RouterDecision,
    build_router_agent,
    build_tool_registry,
    chat_history_from_messages,
)
from infrastructure_atlas.application.chat_agents.callbacks import (
    TokenUsageCallback,
    merge_token_usage,
)
from infrastructure_atlas.infrastructure.logging import get_logger

try:  # optional dependency for telemetry
    from langchain_community.callbacks.manager import get_openai_callback
except Exception:  # pragma: no cover - fallback when callbacks unavailable
    get_openai_callback = None  # type: ignore

__all__ = ["AgentRunResult", "AgentRuntime", "AgentRuntimeError"]


class AgentRuntimeError(RuntimeError):
    """Raised when the agent runtime cannot be initialised or executed."""


@dataclass(slots=True)
class AgentRunResult:
    """Outcome returned after executing the router + domain agent pipeline."""

    text: str
    decision: RouterDecision
    intermediate_steps: Sequence[dict[str, Any]]
    tool_outputs: Sequence[dict[str, Any]]
    usage: dict[str, int] | None = None


@dataclass(frozen=True)
class _ZabbixFallbackQuery:
    """Derived information from a Zabbix-related user request for fallback execution."""

    mode: Literal["group_lookup", "alerts"]
    group_name: str
    require_unack: bool = False
    severities: tuple[int, ...] = ()


logger = get_logger(__name__)


class AgentRuntime:
    """Coordinate the router and domain agent execution for a chat turn."""

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        api_key: str,
        temperature: float | None = None,
    ) -> None:
        provider = (provider or "").strip().lower()
        if not provider:
            raise AgentRuntimeError("Provider is required for agent execution")
        if not model:
            raise AgentRuntimeError("Model is required for agent execution")
        if not api_key:
            raise AgentRuntimeError(f"Provider '{provider}' not configured (missing API key)")
        self._provider = provider
        self._model = model
        self._api_key = api_key
        self._temperature = None if temperature is None else float(temperature)
        self._logger = logger

    def run(  # noqa: PLR0913
        self,
        *,
        session_id: str | None,
        user_label: str | None,
        variables: Mapping[str, Any] | None,
        history: Sequence[dict[str, str]],
        message: str,
        tool_hint: str | None = None,
    ) -> AgentRunResult:
        if not message:
            raise AgentRuntimeError("Cannot execute agent with empty message")

        context_variables = copy.deepcopy(dict(variables or {}))
        context = AgentContext(
            session_id=session_id,
            user=user_label,
            variables=context_variables,
        )

        decision = self._route_with_retry(message=message, context=context, tool_hint=tool_hint)

        registry = build_tool_registry()
        domain_spec = next((spec for spec in DOMAIN_SPECS if spec.key == decision.domain), None)
        if domain_spec is None:
            raise AgentRuntimeError(f"Router selected unknown domain: {decision.domain}")

        chat_history = chat_history_from_messages(history)
        raw_output = self._invoke_domain_agent(
            domain_spec=domain_spec,
            context=context,
            registry=registry,
            message=message,
            chat_history=chat_history,
        )
        raw_response, usage = raw_output

        text, steps, tool_outputs = self._parse_agent_result(raw_response)
        if usage:
            self._logger.info(
                "Agent usage recorded",
                extra={
                    "event": "chat_agent_usage",
                    "provider": self._provider,
                    "model": self._model,
                    "domain": decision.domain,
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "total_tokens": usage.get("total_tokens"),
                },
            )
        return AgentRunResult(
            text=text,
            decision=decision,
            intermediate_steps=steps,
            tool_outputs=tool_outputs,
            usage=usage,
        )

    def _build_llm(self, temperature_override: float | None = ...) -> BaseLanguageModel:
        temperature = self._temperature if temperature_override is ... else temperature_override
        self._logger.debug(
            "Building chat LLM",
            extra={
                "event": "agent_build_llm",
                "provider": self._provider,
                "model": self._model,
                "temperature": temperature,
            },
        )
        if self._provider in {"openai", "openrouter"}:
            from langchain_openai import ChatOpenAI

            kwargs: dict[str, Any] = {
                "model": self._model,
                "max_retries": 2,
                "openai_api_key": self._api_key,
            }
            if temperature is not None:
                kwargs["temperature"] = temperature
            if self._provider == "openrouter":
                kwargs["base_url"] = "https://openrouter.ai/api/v1"
                headers: dict[str, str] = {}
                referer = os.getenv("OPENROUTER_REFERRER", "").strip()
                title = os.getenv("OPENROUTER_TITLE", "Infrastructure Atlas").strip()
                if referer:
                    headers["HTTP-Referer"] = referer
                if title:
                    headers["X-Title"] = title
                if headers:
                    kwargs["default_headers"] = headers
            return ChatOpenAI(**kwargs)
        if self._provider == "claude":
            try:
                from langchain_anthropic import ChatAnthropic
            except ImportError as exc:  # pragma: no cover - optional dependency
                raise AgentRuntimeError("langchain-anthropic is required for Claude providers") from exc

            kwargs = {
                "model": self._model,
                "api_key": self._api_key,
                "max_output_tokens": 800,
            }
            if temperature is not None:
                kwargs["temperature"] = temperature
            return ChatAnthropic(**kwargs)
        if self._provider == "gemini":
            try:
                from langchain_google_genai import ChatGoogleGenerativeAI
            except ImportError as exc:  # pragma: no cover - optional dependency
                raise AgentRuntimeError("langchain-google-genai is required for Gemini providers") from exc

            kwargs = {
                "model": self._model,
                "google_api_key": self._api_key,
                "max_output_tokens": 800,
                "convert_system_message_to_human": True,
            }
            if temperature is not None:
                kwargs["temperature"] = temperature
            return ChatGoogleGenerativeAI(**kwargs)
        raise AgentRuntimeError(f"Unsupported provider for agents: {self._provider}")

    def _build_router(self, temperature_override: float | None = ...) -> RouterAgent:
        llm = self._build_llm(temperature_override=temperature_override)
        return build_router_agent(llm)

    def _route_with_retry(
        self,
        *,
        message: str,
        context: AgentContext,
        tool_hint: str | None,
    ) -> RouterDecision:
        router = self._build_router()
        try:
            return router.route(message, context, tool_hint=tool_hint)
        except Exception as exc:
            if self._temperature is None:
                raise AgentRuntimeError(str(exc)) from exc

        fallback_router = self._build_router(temperature_override=None)
        self._logger.info(
            "Router retry with provider default temperature",
            extra={
                "event": "agent_router_retry",
                "provider": self._provider,
                "model": self._model,
            },
        )
        try:
            return fallback_router.route(message, context, tool_hint=tool_hint)
        except Exception as exc:  # pragma: no cover - fallback attempt failed
            raise AgentRuntimeError(str(exc)) from exc

    def _invoke_domain_agent(
        self,
        *,
        domain_spec,
        context: AgentContext,
        registry: Mapping[str, Any],
        message: str,
        chat_history,
    ) -> tuple[Any, dict[str, int] | None]:
        domain_llm = self._build_llm()
        agent_executor = domain_spec.build(domain_llm, context, registry)
        start = perf_counter()
        try:
            result = self._invoke_with_usage(agent_executor, message, chat_history)
            duration_ms = int((perf_counter() - start) * 1000)
            self._logger.info(
                "Domain agent completed",
                extra={
                    "event": "agent_domain_completed",
                    "provider": self._provider,
                    "model": self._model,
                    "domain": domain_spec.key,
                    "duration_ms": duration_ms,
                },
            )
            return result
        except Exception as exc:
            duration_ms = int((perf_counter() - start) * 1000)
            self._logger.warning(
                "Domain agent failed",
                extra={
                    "event": "agent_domain_error",
                    "provider": self._provider,
                    "model": self._model,
                    "domain": domain_spec.key,
                    "duration_ms": duration_ms,
                    "error": str(exc),
                },
            )
            fallback_response = self._attempt_domain_fallback(
                domain_spec=domain_spec,
                registry=registry,
                message=message,
            )
            if fallback_response is not None:
                return fallback_response, None
            if self._temperature is None:
                raise self._normalise_provider_error(exc, domain_spec.key) from exc

        # Retry without explicit temperature when the provider rejects overrides.
        fallback_llm = self._build_llm(temperature_override=None)
        agent_executor_fallback = domain_spec.build(fallback_llm, context, registry)
        self._logger.info(
            "Agent retry with provider default temperature",
            extra={
                "event": "agent_domain_retry",
                "provider": self._provider,
                "model": self._model,
                "domain": domain_spec.key,
            },
        )
        start = perf_counter()
        try:
            result = self._invoke_with_usage(agent_executor_fallback, message, chat_history)
            duration_ms = int((perf_counter() - start) * 1000)
            self._logger.info(
                "Domain agent completed (fallback)",
                extra={
                    "event": "agent_domain_completed",
                    "provider": self._provider,
                    "model": self._model,
                    "domain": domain_spec.key,
                    "duration_ms": duration_ms,
                    "fallback": True,
                },
            )
            return result
        except Exception as exc:  # pragma: no cover - fallback attempt failed
            duration_ms = int((perf_counter() - start) * 1000)
            self._logger.error(
                "Domain agent fallback failed",
                extra={
                    "event": "agent_domain_error",
                    "provider": self._provider,
                    "model": self._model,
                    "domain": domain_spec.key,
                    "duration_ms": duration_ms,
                    "fallback": True,
                    "error": str(exc),
                },
            )
            fallback_response = self._attempt_domain_fallback(
                domain_spec=domain_spec,
                registry=registry,
                message=message,
            )
            if fallback_response is not None:
                return fallback_response, None
            raise self._normalise_provider_error(exc, domain_spec.key) from exc

    def _invoke_with_usage(
        self,
        executor: AgentExecutor,
        message: str,
        chat_history,
    ) -> tuple[Any, dict[str, int] | None]:
        usage_handler = TokenUsageCallback()
        if self._should_collect_usage():
            callback_factory = get_openai_callback  # type: ignore[misc]
            cm = callback_factory() if callback_factory is not None else nullcontext()
        else:
            cm = nullcontext()

        with cm as cb:
            runner = executor.with_config(callbacks=[usage_handler])
            result = runner.invoke({"input": message, "chat_history": chat_history})

        usage_from_handler = usage_handler.snapshot()
        usage_from_callback = self._usage_from_callback(cb) if self._should_collect_usage() else None
        usage = merge_token_usage(usage_from_handler, usage_from_callback)
        return result, usage

    def _normalise_provider_error(self, error: Exception, domain_key: str) -> AgentRuntimeError:
        status = None
        for attr in ("status_code", "status", "http_status"):
            value = getattr(error, attr, None)
            if isinstance(value, int):
                status = value
                break
        message = getattr(error, "message", None)
        if not message:
            message = str(error)
        detail = message.strip()
        if detail.lower().startswith("error code:"):
            parts = detail.split("-", 1)
            if len(parts) == 2:
                detail = parts[1].strip()
        if len(detail) > 400:
            detail = detail[:400] + "…"

        summary = "Upstream model provider returned an error"
        if status:
            summary += f" (HTTP {status})"
        self._logger.error(
            "Provider error during agent execution",
            extra={
                "event": "agent_provider_error",
                "provider": self._provider,
                "model": self._model,
                "domain": domain_key,
                "status": status,
                "provider_error": str(error),
            },
        )
        return AgentRuntimeError(f"{summary}. Please retry. Provider message: {detail}")

    def _attempt_domain_fallback(
        self,
        *,
        domain_spec,
        registry: Mapping[str, Any],
        message: str,
    ) -> str | None:
        if domain_spec.key != "zabbix":
            return None
        query = self._parse_zabbix_request(message)
        if query is None:
            return None

        group_tool = registry.get("zabbix_group_search")
        if group_tool is None:
            return None

        groups = self._perform_group_search(group_tool, query.group_name)
        if groups is None:
            return None

        if query.mode == "group_lookup":
            return self._format_group_lookup_response(query.group_name, groups)

        problem_tool = registry.get("zabbix_current_alerts")
        if problem_tool is None:
            return None

        if not groups:
            return f"No Zabbix groups found matching '{query.group_name}'."

        group_ids = [int(entry["groupid"]) for entry in groups if "groupid" in entry]
        params: dict[str, Any] = {
            "limit": 40,
            "include_subgroups": True,
        }
        if group_ids:
            params["groupids"] = ",".join(str(gid) for gid in group_ids)
        if query.require_unack:
            params["unacknowledged"] = True
        if query.severities:
            params["severities"] = ",".join(str(level) for level in sorted(set(query.severities)))

        try:
            raw = problem_tool.invoke(params)
            data = json.loads(raw) if isinstance(raw, str) else raw
        except Exception as exc:  # pragma: no cover - defensive fallback
            self._logger.error(
                "Fallback Zabbix alerts failed",
                extra={
                    "event": "agent_fallback_error",
                    "domain": "zabbix",
                    "error": str(exc),
                },
            )
            return None

        if not isinstance(data, Mapping):
            return None
        items = data.get("items") or []
        summary = self._format_alert_summary(query, groups, items)
        self._logger.info(
            "Served response via Zabbix fallback",
            extra={
                "event": "agent_domain_fallback",
                "domain": "zabbix",
                "group_query": query.group_name,
                "result_count": len(items) if isinstance(items, list) else 0,
                "fallback_mode": "alerts",
            },
        )
        return summary

    @staticmethod
    def _parse_zabbix_request(message: str) -> _ZabbixFallbackQuery | None:
        if not message:
            return None
        lowered = message.lower()
        group_name = None
        patterns = [
            r"group id for (?P<name>.+?)\.?$",
            r"group id of (?P<name>.+?)\.?$",
            r"alerts? for (?P<name>.+?) group",
            r"alerts? for (?P<name>.+?)$",
            r"hostgroup (?:called|named)? (?P<name>.+?)\.?$",
            r"group (?P<name>.+?)$",
        ]
        for pattern in patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                name = match.group("name").strip(" .!?")
                group_name = name
                break
        if not group_name:
            return None

        severities: list[int] = []
        severity_map = {
            "disaster": 5,
            "critical": 5,
            "high": 4,
            "average": 3,
            "moderate": 3,
            "warning": 2,
            "info": 1,
            "information": 1,
        }
        for keyword, level in severity_map.items():
            if keyword in lowered:
                severities.append(level)

        require_unack = any(label in lowered for label in ("unack", "not acknowledged", "un-ack"))

        mode: Literal["group_lookup", "alerts"] = "alerts"
        if "group id" in lowered or "groupid" in lowered:
            mode = "group_lookup"

        return _ZabbixFallbackQuery(
            mode=mode,
            group_name=group_name,
            require_unack=require_unack,
            severities=tuple(severities),
        )

    @staticmethod
    def _perform_group_search(group_tool: Any, group_name: str) -> list[dict[str, Any]] | None:
        try:
            raw = group_tool.invoke({"name": group_name, "limit": 20})
            data = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            return None
        groups: list[dict[str, Any]] = []
        if isinstance(data, Mapping):
            payload = data.get("groups") or []
            if isinstance(payload, list):
                for item in payload:
                    if isinstance(item, Mapping):
                        groups.append(dict(item))
        return groups

    @staticmethod
    def _format_group_lookup_response(group_name: str, groups: list[dict[str, Any]]) -> str:
        if not groups:
            return f"No Zabbix groups found matching '{group_name}'."
        lines = [f"Found {len(groups)} group(s) matching '{group_name}':"]
        for entry in groups[:5]:
            gid = entry.get("groupid")
            name = entry.get("name")
            if gid is None or name is None:
                continue
            lines.append(f"• {name} (ID {gid})")
        if len(groups) > 5:
            lines.append("Showing first 5 results.")
        return "\n".join(lines)

    @staticmethod
    def _format_alert_summary(
        query: _ZabbixFallbackQuery,
        groups: list[dict[str, Any]],
        items: Any,
    ) -> str:
        group_names = [entry.get("name") for entry in groups if isinstance(entry, Mapping)]
        target = group_names[0] if group_names else query.group_name
        if not isinstance(items, list) or not items:
            qualifier = "unacknowledged " if query.require_unack else ""
            return f"No {qualifier}alerts found for the {target} group."

        severity_labels = {
            0: "Not classified",
            1: "Information",
            2: "Warning",
            3: "Average",
            4: "High",
            5: "Disaster",
        }
        counts: dict[int, int] = {}
        lines = [
            f"Showing {min(len(items), 5)} of {len(items)} active alerts for {target}.",
        ]
        for entry in items:
            if not isinstance(entry, Mapping):
                continue
            severity = int(entry.get("severity", -1))
            counts[severity] = counts.get(severity, 0) + 1
        if counts:
            summary_bits = []
            for level in sorted(counts, reverse=True):
                label = severity_labels.get(level, f"Severity {level}")
                summary_bits.append(f"{label}: {counts[level]}")
            lines.append("Severity totals — " + ", ".join(summary_bits))

        for entry in items[:5]:
            if not isinstance(entry, Mapping):
                continue
            severity = severity_labels.get(int(entry.get("severity", -1)), "Severity ?")
            host = entry.get("host") or entry.get("host_name") or "(unknown host)"
            name = entry.get("name") or entry.get("opdata") or "(unnamed alert)"
            acknowledged = "Yes" if int(entry.get("acknowledged", 0)) else "No"
            lines.append(f"• {severity} - {host}: {name} (Ack: {acknowledged})")
        if len(items) > 5:
            lines.append("Showing first 5 results.")
        return "\n".join(lines)

    def _should_collect_usage(self) -> bool:
        return self._provider in {"openai", "openrouter"} and get_openai_callback is not None

    @staticmethod
    def _usage_from_callback(callback: Any) -> dict[str, int] | None:
        if callback is None:
            return None
        try:
            usage = {
                "prompt_tokens": int(getattr(callback, "prompt_tokens", 0) or 0),
                "completion_tokens": int(getattr(callback, "completion_tokens", 0) or 0),
                "total_tokens": int(getattr(callback, "total_tokens", 0) or 0),
            }
        except Exception:
            return None
        if not any(usage.values()):
            return None
        return usage

    @staticmethod
    def _parse_agent_result(raw_output: Any) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
        text = ""
        steps: list[dict[str, Any]] = []
        tool_outputs: list[dict[str, Any]] = []

        if isinstance(raw_output, dict):
            text = str(raw_output.get("output") or "").strip()
            raw_steps = raw_output.get("intermediate_steps") or []
        else:
            text = str(raw_output or "").strip()
            raw_steps = []

        for item in raw_steps:
            if not isinstance(item, tuple | list) or len(item) != 2:
                continue
            action, observation = item
            action_payload = {
                "tool": getattr(action, "tool", None),
                "input": getattr(action, "tool_input", None),
                "log": getattr(action, "log", None),
            }
            obs_value = AgentRuntime._coerce_observation(observation)
            steps.append({"action": action_payload, "observation": obs_value})
            if obs_value is not None:
                tool_outputs.append(
                    {
                        "tool": action_payload["tool"],
                        "output": obs_value,
                    }
                )
        return text or "", steps, tool_outputs

    @staticmethod
    def _coerce_observation(observation: Any) -> Any:
        if observation is None:
            return None
        if isinstance(observation, dict | list | int | float | bool):
            return observation
        if isinstance(observation, str):
            text = observation.strip()
            if not text:
                return ""
            try:
                return json.loads(text)
            except Exception:
                return text
        return str(observation)
