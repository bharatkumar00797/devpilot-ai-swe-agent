"""The core plan -> act -> observe loop."""

from __future__ import annotations

import time
from collections.abc import Callable

from devpilot.agent.actions import ActionParseError, parse_action
from devpilot.agent.models import AgentResult, RunStatus, Step
from devpilot.agent.prompts import INVALID_REPLY, OBSERVATION_TEMPLATE, SYSTEM_PROMPT, TASK_TEMPLATE
from devpilot.llm.base import LLMError, LLMProvider, Message
from devpilot.sandbox.runner import truncate_middle
from devpilot.sandbox.workspace import Workspace
from devpilot.tools.registry import ToolRegistry

StepCallback = Callable[[Step], None]


class Agent:
    def __init__(
        self,
        provider: LLMProvider,
        tools: ToolRegistry,
        workspace: Workspace,
        *,
        max_steps: int = 15,
        max_observation_chars: int = 6_000,
        max_invalid_replies: int = 3,
        on_step: StepCallback | None = None,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be >= 1")
        self.provider = provider
        self.tools = tools
        self.workspace = workspace
        self.max_steps = max_steps
        self.max_observation_chars = max_observation_chars
        self.max_invalid_replies = max_invalid_replies
        self.on_step = on_step

    def run(self, issue: str) -> AgentResult:
        issue = issue.strip()
        if not issue:
            raise ValueError("Issue text must not be empty")
        messages = [
            Message("system", SYSTEM_PROMPT.format(tools=self.tools.describe())),
            Message("user", TASK_TEMPLATE.format(issue=issue)),
        ]
        steps: list[Step] = []
        tests_passed: bool | None = None
        prompt_tokens = completion_tokens = 0
        invalid_streak = 0
        model = ""
        status = RunStatus.MAX_STEPS
        summary = f"Stopped after reaching the step limit ({self.max_steps})."

        for index in range(1, self.max_steps + 1):
            try:
                completion = self.provider.complete(messages)
            except LLMError as exc:
                status, summary = RunStatus.FAILED, f"LLM provider error: {exc}"
                break
            model = completion.model
            prompt_tokens += completion.usage.prompt_tokens
            completion_tokens += completion.usage.completion_tokens
            messages.append(Message("assistant", completion.content))

            try:
                action = parse_action(completion.content)
            except ActionParseError as exc:
                invalid_streak += 1
                if invalid_streak >= self.max_invalid_replies:
                    status, summary = RunStatus.FAILED, "Model repeatedly returned invalid actions."
                    break
                messages.append(Message("user", INVALID_REPLY.format(error=exc)))
                continue
            invalid_streak = 0

            if action.is_finish:
                summary = str(action.args.get("summary") or action.thought or "Done.")
                status = RunStatus.COMPLETED
                self._record(
                    steps,
                    Step(
                        index=index,
                        thought=action.thought,
                        tool="finish",
                        args=action.args,
                        observation=summary,
                    ),
                )
                break

            started = time.monotonic()
            result = self.tools.execute(action.tool, action.args)
            if action.tool == "run_tests" and "passed" in result.metadata:
                tests_passed = bool(result.metadata["passed"])
            observation = truncate_middle(result.output, self.max_observation_chars)
            self._record(
                steps,
                Step(
                    index=index,
                    thought=action.thought,
                    tool=action.tool,
                    args=action.args,
                    ok=result.ok,
                    observation=observation,
                    duration_s=time.monotonic() - started,
                ),
            )
            messages.append(
                Message(
                    "user",
                    OBSERVATION_TEMPLATE.format(
                        tool=action.tool,
                        status="ok" if result.ok else "error",
                        output=observation,
                        step=index,
                        max_steps=self.max_steps,
                    ),
                )
            )

        return AgentResult(
            status=status,
            summary=summary,
            steps=steps,
            diff=self.workspace.diff(),
            changed_files=self.workspace.changed_files(),
            tests_passed=tests_passed,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            model=model,
        )

    def _record(self, steps: list[Step], step: Step) -> None:
        steps.append(step)
        if self.on_step is not None:
            self.on_step(step)
