"""Request and response models for the HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from devpilot.agent import Step

MAX_ISSUE_CHARS = 8_000
RunState = Literal["queued", "running", "completed", "max_steps", "failed", "error"]


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo: str = Field(
        min_length=1,
        max_length=1024,
        description="`demo:<name>` or an absolute path inside DEVPILOT_REPO_ALLOWLIST",
        examples=["demo:buggy-calculator"],
    )
    issue: str = Field(min_length=1, max_length=MAX_ISSUE_CHARS)
    max_steps: int | None = Field(default=None, ge=1, le=100)
    provider: Literal["mock", "openai"] | None = None

    @field_validator("repo")
    @classmethod
    def _no_control_chars(cls, value: str) -> str:
        if any(ord(ch) < 32 for ch in value):
            raise ValueError("repo must not contain control characters")
        return value.strip()

    @field_validator("issue")
    @classmethod
    def _issue_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("issue must not be blank")
        return value.replace("\x00", "")


class RunSummaryOut(BaseModel):
    id: str
    status: RunState
    repo: str
    provider: str
    title: str
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    step_count: int = 0
    tests_passed: bool | None = None


class RunDetailOut(RunSummaryOut):
    issue: str
    max_steps: int
    summary: str = ""
    diff: str = ""
    changed_files: list[str] = Field(default_factory=list)
    pr_summary: str = ""
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    error: str | None = None


class RunCreatedOut(RunDetailOut):
    """Response of ``POST /api/runs``.

    In background mode the run is still ``queued``; poll the trace endpoint. In sync
    (serverless) mode the run has already finished and ``steps`` holds the full trace,
    so clients never depend on a follow-up request reaching the same instance.
    """

    steps: list[Step] = Field(default_factory=list)


class RunListOut(BaseModel):
    runs: list[RunSummaryOut]


class TraceOut(BaseModel):
    id: str
    status: RunState
    done: bool
    next_cursor: int = Field(description="pass as ?since= to fetch only newer steps")
    steps: list[Step]


class DemoOut(BaseModel):
    name: str
    repo: str
    issue: str


class ConfigOut(BaseModel):
    version: str
    auth_required: bool
    access_mode: Literal["api-key", "dev", "public-demo"]
    allow_paths: bool
    providers: list[str]
    default_provider: str
    default_max_steps: int
    max_steps_cap: int
    max_issue_chars: int
    sync_runs: bool = Field(description="runs finish within the POST /api/runs request")
    demos: list[DemoOut]


class HealthOut(BaseModel):
    status: Literal["ok"] = "ok"
    version: str
    active_runs: int
