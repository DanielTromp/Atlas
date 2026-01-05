"""Pricing information for AI providers and models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Pricing per 1M tokens (input, output)
# Format: (input_price_per_1M, output_price_per_1M)
PRICING: dict[str, tuple[float, float]] = {
    # OpenAI models
    "gpt-5-mini": (0.25, 2.0),
    "gpt-4o-mini": (0.15, 0.6),
    "gpt-4o": (2.5, 10.0),
    "gpt-4-turbo": (10.0, 30.0),
    "gpt-3.5-turbo": (0.5, 1.5),
    # Anthropic models
    "claude-3-5-sonnet-20241022": (3.0, 15.0),
    "claude-3-5-haiku-20241022": (0.8, 4.0),
    "claude-3-opus-20240229": (15.0, 75.0),
    # Google Gemini models
    "gemini-1.5-flash": (0.075, 0.3),
    "gemini-1.5-pro": (1.25, 5.0),
    "gemini-pro": (0.5, 1.5),
    # OpenRouter models (approximate, varies)
    "openai/gpt-5-mini": (0.25, 2.0),
    "openai/gpt-5-nano": (0.10, 0.40),
    "openai/gpt-5.2": (5.0, 20.0),
    "openai/gpt-4o-mini": (0.15, 0.6),
    "openai/gpt-4o": (2.5, 10.0),
    "openai/gpt-oss-120b": (0.50, 1.50),
    "anthropic/claude-opus-4.5": (15.0, 75.0),
    "anthropic/claude-sonnet-4.5": (3.0, 15.0),
    "anthropic/claude-haiku-4.5": (0.80, 4.0),
    "anthropic/claude-sonnet-4": (3.0, 15.0),
    "anthropic/claude-3.5-sonnet": (3.0, 15.0),
    "anthropic/claude-3.5-haiku": (0.8, 4.0),
    "google/gemini-2.5-flash": (0.075, 0.3),
    "google/gemini-flash-1.5": (0.075, 0.3),
    "x-ai/grok-4.1-fast": (0.50, 1.50),
    "meta-llama/llama-3.1-70b-instruct": (0.59, 0.79),
    "deepseek/deepseek-v3.2": (0.27, 1.10),
    "deepseek/deepseek-chat": (0.14, 0.28),
}


@dataclass
class TokenCost:
    """Token usage and cost information."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "model": self.model,
        }


def calculate_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> TokenCost:
    """Calculate cost for token usage.

    Args:
        model: Model identifier
        prompt_tokens: Number of prompt tokens
        completion_tokens: Number of completion tokens

    Returns:
        TokenCost with calculated cost
    """
    # Normalize model name
    model_lower = model.lower()

    # Find matching pricing
    pricing = None
    for key, price in PRICING.items():
        if key.lower() in model_lower or model_lower in key.lower():
            pricing = price
            break

    # Default pricing if not found
    if pricing is None:
        # Use average pricing
        pricing = (1.0, 3.0)

    input_price_per_1M, output_price_per_1M = pricing

    # Calculate cost
    input_cost = (prompt_tokens / 1_000_000) * input_price_per_1M
    output_cost = (completion_tokens / 1_000_000) * output_price_per_1M
    total_cost = input_cost + output_cost

    return TokenCost(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        cost_usd=total_cost,
        model=model,
    )


def get_model_pricing(model: str) -> dict[str, Any]:
    """Get pricing information for a model."""
    model_lower = model.lower()
    for key, price in PRICING.items():
        if key.lower() in model_lower or model_lower in key.lower():
            return {
                "model": key,
                "input_price_per_1M": price[0],
                "output_price_per_1M": price[1],
            }
    return {
        "model": model,
        "input_price_per_1M": 1.0,
        "output_price_per_1M": 3.0,
        "estimated": True,
    }
