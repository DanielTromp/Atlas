"""Provider registry for managing AI provider instances."""

from __future__ import annotations

import os
from typing import Any

from infrastructure_atlas.ai.models import ProviderConfig, ProviderType
from infrastructure_atlas.infrastructure.logging import get_logger

from .anthropic import AnthropicProvider
from .azure_openai import AzureOpenAIProvider
from .base import AIProvider, ProviderError
from .claude_code import ClaudeCodeProvider
from .gemini import GeminiProvider
from .openai_provider import OpenAIProvider
from .openrouter import OpenRouterProvider

logger = get_logger(__name__)


class ProviderRegistry:
    """Registry for managing AI provider instances.

    Supports lazy initialization and caching of provider instances.
    """

    PROVIDER_CLASSES: dict[ProviderType, type[AIProvider]] = {
        ProviderType.AZURE_OPENAI: AzureOpenAIProvider,
        ProviderType.OPENAI: OpenAIProvider,
        ProviderType.ANTHROPIC: AnthropicProvider,
        ProviderType.OPENROUTER: OpenRouterProvider,
        ProviderType.GEMINI: GeminiProvider,
        ProviderType.CLAUDE_CODE: ClaudeCodeProvider,
    }

    def __init__(self):
        self._providers: dict[str, AIProvider] = {}
        self._configs: dict[str, ProviderConfig] = {}

    def register_config(self, name: str, config: ProviderConfig) -> None:
        """Register a provider configuration."""
        self._configs[name] = config
        # Clear cached provider if config changes
        if name in self._providers:
            del self._providers[name]

    def get_provider(self, name: str) -> AIProvider:
        """Get a provider instance by name.

        Providers are lazily instantiated and cached.
        """
        if name in self._providers:
            return self._providers[name]

        if name not in self._configs:
            # Try to create from environment
            config = self._config_from_env(name)
            if config:
                self._configs[name] = config
            else:
                raise ProviderError(f"Provider '{name}' not configured")

        config = self._configs[name]
        provider_class = self.PROVIDER_CLASSES.get(config.provider_type)
        if not provider_class:
            raise ProviderError(f"Unknown provider type: {config.provider_type}")

        provider = provider_class(config)
        self._providers[name] = provider

        logger.info(
            "Provider initialized",
            extra={
                "event": "provider_initialized",
                "name": name,
                "provider_type": config.provider_type.value,
            },
        )

        return provider

    def _config_from_env(self, name: str) -> ProviderConfig | None:
        """Try to create a provider config from environment variables."""
        name_lower = name.lower()

        if name_lower == "azure_openai":
            api_key = os.getenv("AZURE_OPENAI_API_KEY", "")
            endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "")
            deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "")
            if api_key and endpoint and deployment:
                return ProviderConfig(
                    provider_type=ProviderType.AZURE_OPENAI,
                    api_key=api_key,
                    azure_endpoint=endpoint,
                    azure_deployment=deployment,
                    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
                    default_model=os.getenv("AZURE_OPENAI_DEFAULT_MODEL"),
                )

        elif name_lower == "openai":
            api_key = os.getenv("OPENAI_API_KEY", "")
            if api_key:
                return ProviderConfig(
                    provider_type=ProviderType.OPENAI,
                    api_key=api_key,
                    default_model=os.getenv("OPENAI_DEFAULT_MODEL", "gpt-5-mini"),
                )

        elif name_lower in ("anthropic", "claude"):
            api_key = os.getenv("ANTHROPIC_API_KEY", "")
            if api_key:
                return ProviderConfig(
                    provider_type=ProviderType.ANTHROPIC,
                    api_key=api_key,
                    default_model=os.getenv("ANTHROPIC_DEFAULT_MODEL", "claude-sonnet-4-5-20250929"),
                )

        elif name_lower == "openrouter":
            api_key = os.getenv("OPENROUTER_API_KEY", "")
            if api_key:
                return ProviderConfig(
                    provider_type=ProviderType.OPENROUTER,
                    api_key=api_key,
                    referer=os.getenv("OPENROUTER_REFERRER"),
                    title=os.getenv("OPENROUTER_TITLE", "Infrastructure Atlas"),
                    default_model=os.getenv("OPENROUTER_DEFAULT_MODEL", "openai/gpt-5-mini"),
                )

        elif name_lower == "gemini":
            api_key = os.getenv("GOOGLE_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")
            if api_key:
                return ProviderConfig(
                    provider_type=ProviderType.GEMINI,
                    api_key=api_key,
                    default_model=os.getenv("GEMINI_DEFAULT_MODEL", "gemini-1.5-flash"),
                )

        elif name_lower == "claude_code":
            # Claude Code doesn't need an API key - it uses the local CLI
            # Check if the CLI is available
            import shutil

            if shutil.which("claude"):
                return ProviderConfig(
                    provider_type=ProviderType.CLAUDE_CODE,
                    api_key="local",  # Placeholder, not used
                    default_model="claude-code",
                    timeout=300,  # 5 minute timeout for Claude Code
                )

        return None

    def list_available(self) -> list[dict[str, Any]]:
        """List all available providers with their status."""
        available = []

        for provider_type in ProviderType:
            name = provider_type.value
            configured = name in self._configs or self._config_from_env(name) is not None

            available.append(
                {
                    "name": name,
                    "type": provider_type.value,
                    "configured": configured,
                    "active": name in self._providers,
                }
            )

        return available

    def get_configured_providers(self) -> list[str]:
        """Get list of configured provider names."""
        configured = list(self._configs.keys())

        # Also check environment-based providers
        for provider_type in ProviderType:
            name = provider_type.value
            if name not in configured and self._config_from_env(name) is not None:
                configured.append(name)

        return configured

    async def test_provider(self, name: str) -> dict[str, Any]:
        """Test a provider connection."""
        try:
            provider = self.get_provider(name)
            return await provider.test_connection()
        except Exception as e:
            return {
                "status": "error",
                "name": name,
                "error": str(e),
            }

    async def close_all(self) -> None:
        """Close all provider connections."""
        for provider in self._providers.values():
            if hasattr(provider, "close"):
                await provider.close()
        self._providers.clear()


# Global registry instance
_global_registry: ProviderRegistry | None = None


def get_provider_registry() -> ProviderRegistry:
    """Get the global provider registry."""
    global _global_registry
    if _global_registry is None:
        _global_registry = ProviderRegistry()
    return _global_registry


def get_provider(name: str) -> AIProvider:
    """Get a provider from the global registry."""
    return get_provider_registry().get_provider(name)

