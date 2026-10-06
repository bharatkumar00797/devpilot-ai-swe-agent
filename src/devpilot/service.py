"""High-level entry point that wires workspace, sandbox, tools, provider and agent."""

from __future__ import annotations

from pathlib import Path

from devpilot.agent import Agent, AgentResult, StepCallback
from devpilot.config import Settings
from devpilot.llm import LLMProvider, build_provider
from devpilot.sandbox import CommandRunner, Workspace
from devpilot.tools import build_default_registry


def run_task(
    repo: Path,
    issue: str,
    *,
    settings: Settings | None = None,
    provider: LLMProvider | None = None,
    test_command: str | None = None,
    on_step: StepCallback | None = None,
) -> AgentResult:
    """Resolve ``issue`` against a throwaway copy of ``repo`` and return the result.

    The original repository is never modified; apply ``result.diff`` yourself
    (e.g. ``git apply``) after review.
    """
    settings = settings or Settings.from_env()
    provider = provider or build_provider(settings)
    with Workspace.from_source(repo) as workspace:
        runner = CommandRunner(
            workspace.root,
            timeout_s=settings.command_timeout,
            isolate_network=settings.isolate_network,
        )
        tools = build_default_registry(workspace, runner, test_command=test_command)
        agent = Agent(provider, tools, workspace, max_steps=settings.max_steps, on_step=on_step)
        return agent.run(issue)
