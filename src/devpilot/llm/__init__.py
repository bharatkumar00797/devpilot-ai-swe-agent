"""LLM provider implementations and factory."""

from __future__ import annotations

from devpilot.config import Settings
from devpilot.llm.base import Completion, LLMError, LLMProvider, Message, Usage
from devpilot.llm.mock import MockProvider
from devpilot.llm.openai_compat import OpenAICompatibleProvider

__all__ = [
    "Completion",
    "LLMError",
    "LLMProvider",
    "Message",
    "MockProvider",
    "OpenAICompatibleProvider",
    "Usage",
    "build_provider",
]


def build_provider(settings: Settings) -> LLMProvider:
    """Create the configured provider, falling back to the offline mock."""
    if settings.provider in {"openai", "groq", "ollama", "openai-compatible"}:
        return OpenAICompatibleProvider(
            base_url=settings.base_url,
            model=settings.model,
            api_key=settings.api_key,
        )
    if settings.provider != "mock":
        raise ValueError(f"Unknown provider {settings.provider!r} (use 'mock' or 'openai')")
    return MockProvider()
