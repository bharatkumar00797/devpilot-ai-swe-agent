"""Deterministic offline provider.

The mock provider follows the same JSON action protocol as a real model, so the
whole pipeline (agent loop, tools, sandbox, diff, report) runs end to end with no
API key and no network. It is used as the default for demos, CI and tests.

Policy (derived purely from the transcript, so it is stateless and reproducible):

1. list the repository files
2. search for the most relevant identifier from the issue
3. read the best matching file
4. run the test suite to reproduce the problem
5. if the issue contains a concrete suggestion such as
   "`return a - b` should be `return a + b`", apply it as a targeted edit
6. re-run the tests and finish with a summary
"""

from __future__ import annotations

import json
import re

from devpilot.llm.base import Completion, LLMProvider, Message, Usage

_ISSUE_RE = re.compile(r"<issue>\s*(.*?)\s*</issue>", re.DOTALL)
_SUGGESTION_RES = [
    re.compile(r"`([^`]+)`\s+should\s+(?:be|read|become)\s+`([^`]+)`", re.IGNORECASE),
    re.compile(r"replace\s+`([^`]+)`\s+with\s+`([^`]+)`", re.IGNORECASE),
    re.compile(r"change\s+`([^`]+)`\s+to\s+`([^`]+)`", re.IGNORECASE),
]
_BACKTICK_RE = re.compile(r"`([^`\n]+)`")
_IDENT_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]{2,})\b")
_SEARCH_HIT_RE = re.compile(r"^([^\s:][^:]*):(\d+):", re.MULTILINE)
_CODE_EXTENSIONS = (
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".rb",
    ".php",
    ".c",
    ".h",
    ".cc",
    ".cpp",
    ".cs",
    ".swift",
    ".scala",
)
_STOPWORDS = {
    "the",
    "and",
    "for",
    "that",
    "this",
    "with",
    "should",
    "returns",
    "return",
    "when",
    "from",
    "into",
    "wrong",
    "result",
    "results",
    "bug",
    "issue",
    "fix",
    "test",
    "tests",
    "looks",
    "like",
    "function",
    "file",
    "instead",
    "not",
    "are",
    "was",
    "have",
    "has",
}


def _extract_issue(messages: list[Message]) -> str:
    for message in messages:
        if message.role == "user":
            match = _ISSUE_RE.search(message.content)
            if match:
                return match.group(1)
    return ""


def find_suggestion(issue: str) -> tuple[str, str] | None:
    for pattern in _SUGGESTION_RES:
        match = pattern.search(issue)
        if match:
            return match.group(1), match.group(2)
    return None


def pick_search_query(issue: str) -> str:
    suggestion = find_suggestion(issue)
    if suggestion:
        return suggestion[0]
    for token in _BACKTICK_RE.findall(issue):
        cleaned = str(token).strip()
        if len(cleaned) >= 3:
            return cleaned.rstrip("()")
    for token in _IDENT_RE.findall(issue):
        if str(token).lower() not in _STOPWORDS:
            return str(token)
    return issue.strip().split("\n", 1)[0][:40]


class MockProvider(LLMProvider):
    name = "mock"

    def complete(self, messages: list[Message], *, temperature: float = 0.0) -> Completion:
        action = self._next_action(messages)
        content = json.dumps(action)
        prompt_chars = sum(len(m.content) for m in messages)
        return Completion(
            content=content,
            model="mock-swe-1",
            usage=Usage(prompt_tokens=prompt_chars // 4, completion_tokens=len(content) // 4),
        )

    # ------------------------------------------------------------------ policy
    def _next_action(self, messages: list[Message]) -> dict[str, object]:
        issue = _extract_issue(messages)
        history = self._history(messages)
        called = [tool for tool, _ in history]
        suggestion = find_suggestion(issue)

        if "list_files" not in called:
            return _act("Get an overview of the repository layout.", "list_files", {})

        if "search_code" not in called:
            query = pick_search_query(issue)
            return _act(
                f"Locate code related to the issue by searching for {query!r}.",
                "search_code",
                {"query": query},
            )

        target = self._target_file(history)
        if "read_file" not in called and target:
            return _act(
                f"Read {target} to understand the implementation.", "read_file", {"path": target}
            )

        if "run_tests" not in called:
            return _act("Run the test suite to reproduce the failure.", "run_tests", {})

        edited = "replace_in_file" in called
        if suggestion and target and not edited:
            old, new = suggestion
            return _act(
                f"Apply the minimal fix in {target}: replace {old!r} with {new!r}.",
                "replace_in_file",
                {"path": target, "old": old, "new": new},
            )

        if edited and called[-1] != "run_tests":
            return _act("Re-run the tests to verify the fix.", "run_tests", {})

        last_test = next((obs for tool, obs in reversed(history) if tool == "run_tests"), "")
        passed = "exit_code=0" in last_test
        if edited and passed:
            summary = (
                f"Fixed the issue by changing `{suggestion[0] if suggestion else ''}` to "
                f"`{suggestion[1] if suggestion else ''}` in `{target}`. The test suite now passes."
            )
        elif edited:
            summary = f"Applied a candidate fix in `{target}`, but tests are still failing."
        else:
            summary = (
                "Investigated the issue and reproduced it with the test suite, but no confident "
                "patch could be derived offline. Configure a real LLM provider for open-ended "
                "fixes."
            )
        return _act("Wrap up and report the outcome.", "finish", {"summary": summary})

    @staticmethod
    def _history(messages: list[Message]) -> list[tuple[str, str]]:
        """Pair each assistant action with the observation that followed it."""
        history: list[tuple[str, str]] = []
        for i, message in enumerate(messages):
            if message.role != "assistant":
                continue
            try:
                tool = str(json.loads(message.content).get("tool", ""))
            except (json.JSONDecodeError, AttributeError):
                continue
            observation = ""
            if i + 1 < len(messages) and messages[i + 1].role == "user":
                observation = messages[i + 1].content
            history.append((tool, observation))
        return history

    @staticmethod
    def _target_file(history: list[tuple[str, str]]) -> str | None:
        for tool, observation in history:
            if tool == "search_code":
                hits = [m.group(1) for m in _SEARCH_HIT_RE.finditer(observation)]
                code = [h for h in hits if h.endswith(_CODE_EXTENSIONS)]
                source = [h for h in code if "test" not in h.lower()]
                for group in (source, code, hits):
                    if group:
                        return group[0]
        for tool, observation in history:
            if tool == "list_files":
                for line in observation.splitlines():
                    name = line.strip()
                    if name.endswith(_CODE_EXTENSIONS) and "test" not in name.lower():
                        return name
        return None


def _act(thought: str, tool: str, args: dict[str, object]) -> dict[str, object]:
    return {"thought": thought, "tool": tool, "args": args}
