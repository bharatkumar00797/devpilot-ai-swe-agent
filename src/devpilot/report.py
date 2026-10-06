"""Render an agent run as a pull-request style Markdown summary."""

from __future__ import annotations

from devpilot.agent.models import AgentResult


def _title(issue: str) -> str:
    first = issue.strip().splitlines()[0] if issue.strip() else "Automated change"
    return first.lstrip("# ").strip()[:72]


def render_pr_summary(issue: str, result: AgentResult) -> str:
    tests = {True: "passing", False: "failing", None: "not run"}[result.tests_passed]
    lines = [
        f"## {_title(issue)}",
        "",
        "### Summary",
        result.summary,
        "",
        "### Changes",
    ]
    lines += [f"- `{path}`" for path in result.changed_files] or ["- _No files changed_"]
    lines += [
        "",
        "### Verification",
        f"- Tests: **{tests}**",
        f"- Agent status: `{result.status.value}` after {len(result.steps)} step(s)",
        f"- Model: `{result.model or 'n/a'}` "
        f"({result.prompt_tokens + result.completion_tokens} tokens)",
        "",
        "<details><summary>Agent trace</summary>",
        "",
    ]
    for step in result.steps:
        marker = "ok" if step.ok else "error"
        lines.append(f"{step.index}. `{step.tool}` ({marker}) — {step.thought}")
    lines += ["", "</details>"]
    if result.diff:
        lines += ["", "### Diff", "", "```diff", result.diff.rstrip(), "```"]
    return "\n".join(lines) + "\n"
