"""Result types produced by an agent run."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class RunStatus(StrEnum):
    COMPLETED = "completed"
    MAX_STEPS = "max_steps"
    FAILED = "failed"


class Step(BaseModel):
    index: int
    thought: str = ""
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    ok: bool = True
    observation: str = ""
    duration_s: float = 0.0


class AgentResult(BaseModel):
    status: RunStatus
    summary: str
    steps: list[Step] = Field(default_factory=list)
    diff: str = ""
    changed_files: list[str] = Field(default_factory=list)
    tests_passed: bool | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""
