"""Runtime configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


@dataclass(frozen=True)
class Settings:
    provider: str = "mock"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o-mini"
    max_steps: int = 15
    command_timeout: int = 60
    isolate_network: bool = True

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            provider=os.getenv("DEVPILOT_PROVIDER", "mock").strip().lower(),
            base_url=os.getenv("DEVPILOT_BASE_URL", cls.base_url),
            api_key=os.getenv("DEVPILOT_API_KEY", ""),
            model=os.getenv("DEVPILOT_MODEL", cls.model),
            max_steps=_env_int("DEVPILOT_MAX_STEPS", cls.max_steps),
            command_timeout=_env_int("DEVPILOT_COMMAND_TIMEOUT", cls.command_timeout),
            isolate_network=_env_bool("DEVPILOT_ISOLATE_NETWORK", cls.isolate_network),
        )
