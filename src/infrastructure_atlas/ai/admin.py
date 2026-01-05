"""Admin API for AI chat system configuration and testing."""

from __future__ import annotations

import os
from typing import Any

from infrastructure_atlas.ai.models import ProviderType
from infrastructure_atlas.ai.providers import ProviderRegistry, get_provider_registry
from infrastructure_atlas.ai.tools import get_tool_registry
from infrastructure_atlas.infrastructure.logging import get_logger

logger = get_logger(__name__)


class AIAdminService:
    """Admin service for managing AI providers, agents, and configurations."""

    def __init__(self, provider_registry: ProviderRegistry | None = None):
        self._provider_registry = provider_registry

    @property
    def provider_registry(self) -> ProviderRegistry:
        if self._provider_registry is None:
            self._provider_registry = get_provider_registry()
        return self._provider_registry

    # Provider Management
    def list_providers(self) -> list[dict[str, Any]]:
        """List all available providers with their configuration status."""
        providers = []

        for provider_type in ProviderType:
            name = provider_type.value

            # Check environment-based configuration
            env_configured = self._check_env_config(provider_type)

            providers.append(
                {
                    "name": name,
                    "type": provider_type.value,
                    "configured": env_configured,
                    "env_vars": self._get_required_env_vars(provider_type),
                    "default_model": self._get_default_model(provider_type),
                }
            )

        return providers

    def _check_env_config(self, provider_type: ProviderType) -> bool:
        """Check if a provider is configured via environment variables."""
        if provider_type == ProviderType.AZURE_OPENAI:
            return bool(
                os.getenv("AZURE_OPENAI_API_KEY")
                and os.getenv("AZURE_OPENAI_ENDPOINT")
                and os.getenv("AZURE_OPENAI_DEPLOYMENT")
            )
        elif provider_type == ProviderType.OPENAI:
            return bool(os.getenv("OPENAI_API_KEY"))
        elif provider_type == ProviderType.ANTHROPIC:
            return bool(os.getenv("ANTHROPIC_API_KEY"))
        elif provider_type == ProviderType.OPENROUTER:
            return bool(os.getenv("OPENROUTER_API_KEY"))
        elif provider_type == ProviderType.GEMINI:
            return bool(os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"))
        return False

    def _get_required_env_vars(self, provider_type: ProviderType) -> list[str]:
        """Get required environment variables for a provider."""
        if provider_type == ProviderType.AZURE_OPENAI:
            return [
                "AZURE_OPENAI_API_KEY",
                "AZURE_OPENAI_ENDPOINT",
                "AZURE_OPENAI_DEPLOYMENT",
            ]
        elif provider_type == ProviderType.OPENAI:
            return ["OPENAI_API_KEY"]
        elif provider_type == ProviderType.ANTHROPIC:
            return ["ANTHROPIC_API_KEY"]
        elif provider_type == ProviderType.OPENROUTER:
            return ["OPENROUTER_API_KEY"]
        elif provider_type == ProviderType.GEMINI:
            return ["GOOGLE_API_KEY (or GEMINI_API_KEY)"]
        return []

    def _get_default_model(self, provider_type: ProviderType) -> str:
        """Get default model for a provider."""
        defaults = {
            ProviderType.AZURE_OPENAI: os.getenv("AZURE_OPENAI_DEFAULT_MODEL", "gpt-4o-mini"),
            ProviderType.OPENAI: os.getenv("OPENAI_DEFAULT_MODEL", "gpt-4o-mini"),
            ProviderType.ANTHROPIC: os.getenv("ANTHROPIC_DEFAULT_MODEL", "claude-3-5-sonnet-20241022"),
            ProviderType.OPENROUTER: os.getenv("OPENROUTER_DEFAULT_MODEL", "openai/gpt-5-mini"),
            ProviderType.GEMINI: os.getenv("GEMINI_DEFAULT_MODEL", "gemini-1.5-flash"),
        }
        return defaults.get(provider_type, "")

    async def test_provider(self, provider_name: str) -> dict[str, Any]:
        """Test a provider connection."""
        try:
            provider = self.provider_registry.get_provider(provider_name)
            result = await provider.test_connection()
            return result
        except Exception as e:
            return {
                "status": "error",
                "provider": provider_name,
                "error": str(e),
            }

    def get_provider_models(self, provider_name: str) -> list[dict[str, Any]]:
        """Get available models for a provider."""
        try:
            provider = self.provider_registry.get_provider(provider_name)
            return provider.list_models()
        except Exception as e:
            return [{"error": str(e)}]

    # Agent Management
    def get_default_agent_config(self) -> dict[str, Any]:
        """Get the default agent configuration."""
        # Determine best available provider
        for provider_type in [
            ProviderType.AZURE_OPENAI,
            ProviderType.OPENAI,
            ProviderType.ANTHROPIC,
            ProviderType.OPENROUTER,
            ProviderType.GEMINI,
        ]:
            if self._check_env_config(provider_type):
                return {
                    "provider_type": provider_type.value,
                    "model": self._get_default_model(provider_type),
                    "tools_enabled": True,
                    "streaming_enabled": True,
                }

        return {
            "provider_type": None,
            "model": None,
            "tools_enabled": True,
            "streaming_enabled": True,
            "error": "No AI providers configured",
        }

    # Tool Management
    def list_tools(self) -> list[dict[str, Any]]:
        """List all available tools."""
        tool_registry = get_tool_registry()
        return tool_registry.get_tool_info()

    def get_tools_by_category(self) -> dict[str, list[dict[str, Any]]]:
        """Get tools organized by category."""
        tools = self.list_tools()
        by_category: dict[str, list[dict[str, Any]]] = {}
        for tool in tools:
            cat = tool.get("category", "general")
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(tool)
        return by_category

    # System Status
    async def get_system_status(self) -> dict[str, Any]:
        """Get overall AI system status."""
        providers_status = []

        for provider_type in ProviderType:
            name = provider_type.value
            configured = self._check_env_config(provider_type)

            status = {
                "name": name,
                "configured": configured,
                "status": "unknown",
            }

            if configured:
                try:
                    result = await self.test_provider(name)
                    status["status"] = result.get("status", "error")
                    if result.get("response_time_ms"):
                        status["response_time_ms"] = result["response_time_ms"]
                except Exception as e:
                    status["status"] = "error"
                    status["error"] = str(e)
            else:
                status["status"] = "not_configured"

            providers_status.append(status)

        return {
            "providers": providers_status,
            "tools_count": len(self.list_tools()),
            "default_config": self.get_default_agent_config(),
        }


# Global admin service instance
_admin_service: AIAdminService | None = None


def get_ai_admin_service() -> AIAdminService:
    """Get the global AI admin service."""
    global _admin_service
    if _admin_service is None:
        _admin_service = AIAdminService()
    return _admin_service

