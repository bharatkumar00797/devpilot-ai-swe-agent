"""Deterministic offline provider.

The mock provider follows the same JSON action protocol as a real model, so the
whole pipeline (agent loop, tools, sandbox, diff, report) runs end to end with no
API key and no network. It is used as the default for demos, CI and tests.

Policy (derived purely from the transcript, so it is stateless and reproducible):

1. list the repository files
2. search for the most relevant identifier from the issue
3. read the best matching file
4. run the test suite to reproduce the problem
5. if the issue contains concrete suggestions such as
   "`return a - b` should be `return a + b`", apply the first one as a targeted edit
6. re-run the tests; while they still fail and more suggestions remain, locate the
   next snippet, apply it and test again (iterate on failure)
7. finish with a summary of every change and the final test outcome
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

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


def find_suggestions(issue: str) -> list[tuple[str, str]]:
    """Every concrete ``old -> new`` suggestion in the issue, in reading order."""
    found: list[tuple[int, str, str]] = []
    for pattern in _SUGGESTION_RES:
        found.extend((m.start(), m.group(1), m.group(2)) for m in pattern.finditer(issue))
    ordered: list[tuple[str, str]] = []
    for _, old, new in sorted(found):
        if (old, new) not in ordered:
            ordered.append((old, new))
    return ordered


def find_suggestion(issue: str) -> tuple[str, str] | None:
    suggestions = find_suggestions(issue)
    return suggestions[0] if suggestions else None


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
        called = [h.tool for h in history]
        suggestions = find_suggestions(issue)

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

        edits = [h for h in history if h.tool == "replace_in_file"]
        if edits and called[-1] == "replace_in_file":
            return _act("Re-run the tests to verify the change.", "run_tests", {})

        last_test = next((h.observation for h in reversed(history) if h.tool == "run_tests"), "")
        passed = "exit_code=0" in last_test

        # Iterate on failure: keep applying the next suggested change while tests fail.
        if len(edits) < len(suggestions) and not (edits and passed):
            old, new = suggestions[len(edits)]
            searched = next(
                (h for h in history if h.tool == "search_code" and h.args.get("query") == old),
                None,
            )
            if searched is None:
                reason = "Tests are still failing; " if edits else ""
                return _act(
                    f"{reason}locate the next suspicious snippet {old!r}.",
                    "search_code",
                    {"query": old},
                )
            path = self._target_file([searched]) or target
            if path:
                prefix = "Tests still fail; try the next fix" if edits else "Apply the fix"
                return _act(
                    f"{prefix} in {path}: replace {old!r} with {new!r}.",
                    "replace_in_file",
                    {"path": path, "old": old, "new": new},
                )

        summary = _summary(edits, passed)
        return _act("Wrap up and report the outcome.", "finish", {"summary": summary})

    @staticmethod
    def _history(messages: list[Message]) -> list[_Turn]:
        """Pair each assistant action with the observation that followed it."""
        history: list[_Turn] = []
        for i, message in enumerate(messages):
            if message.role != "assistant":
                continue
            try:
                payload = json.loads(message.content)
                tool = str(payload.get("tool", ""))
                args = payload.get("args") or {}
            except (json.JSONDecodeError, AttributeError):
                continue
            observation = ""
            if i + 1 < len(messages) and messages[i + 1].role == "user":
                observation = messages[i + 1].content
            history.append(_Turn(tool, args if isinstance(args, dict) else {}, observation))
        return history

    @staticmethod
    def _target_file(history: list[_Turn]) -> str | None:
        for turn in history:
            if turn.tool == "search_code":
                hits = [m.group(1) for m in _SEARCH_HIT_RE.finditer(turn.observation)]
                code = [h for h in hits if h.endswith(_CODE_EXTENSIONS)]
                source = [h for h in code if "test" not in h.lower()]
                for group in (source, code, hits):
                    if group:
                        return group[0]
        for turn in history:
            if turn.tool == "list_files":
                for line in turn.observation.splitlines():
                    name = line.strip()
                    if name.endswith(_CODE_EXTENSIONS) and "test" not in name.lower():
                        return name
        return None


@dataclass(frozen=True)
class _Turn:
    tool: str
    args: dict[str, object]
    observation: str


def _summary(edits: list[_Turn], passed: bool) -> str:
    changes = [
        f"`{e.args.get('old', '')}` -> `{e.args.get('new', '')}` in `{e.args.get('path', '')}`"
        for e in edits
        if not e.observation.startswith(f"Observation from `{e.tool}` (error)")
    ]
    if edits and passed:
        rounds = f" after {len(edits)} edit/test iterations" if len(edits) > 1 else ""
        return f"Fixed the issue{rounds}: changed {'; '.join(changes)}. The test suite now passes."
    if edits:
        return (
            f"Applied {len(edits)} candidate fix(es) ({'; '.join(changes) or 'none applied'}), "
            "but tests are still failing."
        )
    return (
        "Investigated the issue and reproduced it with the test suite, but no confident "
        "patch could be derived offline. Configure a real LLM provider for open-ended fixes."
    )


def _act(thought: str, tool: str, args: dict[str, object]) -> dict[str, object]:
    return {"thought": thought, "tool": tool, "args": args}
