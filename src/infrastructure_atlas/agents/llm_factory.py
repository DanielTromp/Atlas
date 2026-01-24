"""LLM Factory for creating provider-agnostic language models.

This module provides a factory function to create LangChain-compatible LLM instances
for different providers (Anthropic, OpenAI, Gemini, etc.) with consistent configuration.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from infrastructure_atlas.infrastructure.logging import get_logger

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = get_logger(__name__)

# Provider to LangChain class mapping
# Maps provider name to (module_path, class_name) for lazy imports
PROVIDER_LLM_MAPPING: dict[str, tuple[str, str]] = {
    "anthropic": ("langchain_anthropic", "ChatAnthropic"),
    "openai": ("langchain_openai", "ChatOpenAI"),
    "gemini": ("langchain_google_genai", "ChatGoogleGenerativeAI"),
    "azure_openai": ("langchain_openai", "AzureChatOpenAI"),
}

# Default models for each provider
DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-haiku-4-5-20251001",
    "openai": "gpt-5-mini",
    "gemini": "gemini-3-flash",
    "azure_openai": "gpt-5-mini",
}

# Environment variable names for API keys
API_KEY_ENV_VARS: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GOOGLE_API_KEY",
    "azure_openai": "AZURE_OPENAI_API_KEY",
}


def get_supported_providers() -> list[str]:
    """Get list of supported LLM providers.

    Returns:
        List of provider names that can be used with create_llm
    """
    return list(PROVIDER_LLM_MAPPING.keys())


def get_default_model(provider: str) -> str:
    """Get the default model for a provider.

    Args:
        provider: Provider name (anthropic, openai, gemini, azure_openai)

    Returns:
        Default model identifier for the provider
    """
    return DEFAULT_MODELS.get(provider, DEFAULT_MODELS["anthropic"])


def create_llm(
    provider: str = "anthropic",
    model: str | None = None,
    temperature: float = 0.4,
    max_tokens: int = 4096,
    **kwargs: Any,
) -> "BaseChatModel":
    """Create a LangChain-compatible LLM instance for the specified provider.

    This factory function creates the appropriate LLM class based on the provider,
    handling API key configuration and provider-specific settings.

    Args:
        provider: LLM provider name (anthropic, openai, gemini, azure_openai)
        model: Model identifier (if None, uses provider default)
        temperature: Sampling temperature (0-2)
        max_tokens: Maximum tokens to generate
        **kwargs: Additional provider-specific arguments

    Returns:
        LangChain BaseChatModel instance

    Raises:
        ValueError: If provider is not supported
        ImportError: If required LangChain package is not installed

    Example:
        # Create Anthropic LLM
        llm = create_llm("anthropic", model="claude-haiku-4-5-20251001")

        # Create OpenAI LLM
        llm = create_llm("openai", model="gpt-5-mini", temperature=0.7)

        # Create Gemini LLM
        llm = create_llm("gemini", model="gemini-3-flash")
    """
    provider = provider.lower()

    if provider not in PROVIDER_LLM_MAPPING:
        supported = ", ".join(PROVIDER_LLM_MAPPING.keys())
        raise ValueError(f"Unsupported provider: {provider}. Supported: {supported}")

    # Resolve model
    model = model or get_default_model(provider)

    # Get module and class info
    module_name, class_name = PROVIDER_LLM_MAPPING[provider]

    logger.debug(f"Creating LLM: provider={provider}, model={model}, temp={temperature}")

    try:
        # Import the appropriate module and class
        module = __import__(module_name, fromlist=[class_name])
        llm_class = getattr(module, class_name)
    except ImportError as e:
        raise ImportError(
            f"LangChain package for {provider} not installed. "
            f"Install with: pip install {module_name}"
        ) from e

    # Provider-specific configuration
    if provider == "anthropic":
        return llm_class(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )

    elif provider == "openai":
        return llm_class(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )

    elif provider == "gemini":
        return llm_class(
            model=model,
            temperature=temperature,
            max_output_tokens=max_tokens,
            **kwargs,
        )

    elif provider == "azure_openai":
        # Azure requires additional configuration
        azure_endpoint = kwargs.pop("azure_endpoint", None) or os.getenv("AZURE_OPENAI_ENDPOINT")
        api_version = kwargs.pop("api_version", None) or os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")
        deployment = kwargs.pop("azure_deployment", None) or os.getenv("AZURE_OPENAI_DEPLOYMENT", model)

        return llm_class(
            azure_deployment=deployment,
            azure_endpoint=azure_endpoint,
            api_version=api_version,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )

    else:
        # Generic fallback (shouldn't reach here due to validation above)
        return llm_class(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )


def check_provider_available(provider: str) -> dict[str, Any]:
    """Check if a provider is available (has API key configured).

    Args:
        provider: Provider name to check

    Returns:
        Dict with 'available' boolean and optional 'error' message
    """
    provider = provider.lower()

    if provider not in PROVIDER_LLM_MAPPING:
        return {"available": False, "error": f"Unknown provider: {provider}"}

    env_var = API_KEY_ENV_VARS.get(provider)
    if env_var and not os.getenv(env_var):
        return {
            "available": False,
            "error": f"API key not configured. Set {env_var} environment variable.",
        }

    # Check if the LangChain package is installed
    module_name, _ = PROVIDER_LLM_MAPPING[provider]
    try:
        __import__(module_name)
    except ImportError:
        return {
            "available": False,
            "error": f"LangChain package not installed: pip install {module_name}",
        }

    return {"available": True}
