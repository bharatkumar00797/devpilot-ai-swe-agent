from __future__ import annotations

from pathlib import Path

import httpx

from devpilot.agent import Agent, RunStatus
from devpilot.config import Settings
from devpilot.llm import Completion, LLMProvider, Message, OpenAICompatibleProvider
from devpilot.llm.mock import find_suggestion, pick_search_query
from devpilot.report import render_pr_summary
from devpilot.sandbox import CommandRunner, Workspace
from devpilot.service import run_task
from devpilot.tools import build_default_registry

MOCK = Settings(provider="mock", max_steps=12, command_timeout=60)


def test_end_to_end_fix_with_mock_provider(sample_repo: Path, issue_text: str) -> None:
    result = run_task(sample_repo, issue_text, settings=MOCK)
    assert result.status is RunStatus.COMPLETED
    assert result.tests_passed is True
    assert result.changed_files == ["calculator.py"]
    assert "+    return a + b" in result.diff
    # the user's checkout is untouched
    assert "return a - b" in (sample_repo / "calculator.py").read_text()
    tools = [s.tool for s in result.steps]
    assert tools[0] == "list_files" and tools[-1] == "finish"
    assert tools.count("run_tests") == 2

    summary = render_pr_summary(issue_text, result)
    assert summary.startswith("## add() returns the wrong result")
    assert "Tests: **passing**" in summary


def test_mock_without_suggestion_reports_analysis(sample_repo: Path) -> None:
    result = run_task(sample_repo, "The `add` function is broken.", settings=MOCK)
    assert result.status is RunStatus.COMPLETED
    assert result.diff == ""
    assert result.tests_passed is False


def test_suggestion_and_query_extraction() -> None:
    assert find_suggestion("please replace `x = 1` with `x = 2`") == ("x = 1", "x = 2")
    assert find_suggestion("nothing concrete") is None
    assert pick_search_query("The `parse_config()` helper crashes") == "parse_config"


class _ScriptedProvider(LLMProvider):
    name = "scripted"

    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.calls = 0

    def complete(self, messages: list[Message], *, temperature: float = 0.0) -> Completion:
        reply = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        return Completion(content=reply, model="scripted")


def _agent(repo: Path, provider: LLMProvider, max_steps: int = 5) -> tuple[Agent, Workspace]:
    ws = Workspace.from_source(repo)
    tools = build_default_registry(ws, CommandRunner(ws.root))
    return Agent(provider, tools, ws, max_steps=max_steps), ws


def test_agent_recovers_from_invalid_reply_and_respects_step_limit(sample_repo: Path) -> None:
    provider = _ScriptedProvider(["not json", '{"tool": "list_files", "args": {}}'])
    agent, ws = _agent(sample_repo, provider, max_steps=3)
    with ws:
        result = agent.run("anything")
    assert result.status is RunStatus.MAX_STEPS
    assert [s.tool for s in result.steps] == ["list_files", "list_files"]


def test_agent_fails_after_repeated_invalid_replies(sample_repo: Path) -> None:
    agent, ws = _agent(sample_repo, _ScriptedProvider(["garbage"]), max_steps=10)
    with ws:
        result = agent.run("anything")
    assert result.status is RunStatus.FAILED


def test_openai_compatible_provider_parses_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        return httpx.Response(
            200,
            json={
                "model": "test-model",
                "choices": [{"message": {"role": "assistant", "content": '{"tool": "finish"}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 3},
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(base_url="http://llm.local/v1", model="m", client=client)
    completion = provider.complete([Message("user", "hi")])
    assert completion.content == '{"tool": "finish"}'
    assert completion.usage.total_tokens == 13
