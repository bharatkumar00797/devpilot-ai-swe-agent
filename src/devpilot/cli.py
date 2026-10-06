"""Command line interface: ``devpilot run --repo PATH --issue TEXT``."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from devpilot import __version__
from devpilot.agent import Step
from devpilot.config import Settings
from devpilot.report import render_pr_summary
from devpilot.service import run_task


def _print_step(step: Step) -> None:
    args = ", ".join(f"{k}={str(v)[:40]!r}" for k, v in step.args.items())
    status = "ok" if step.ok else "ERR"
    print(f"[{step.index:>2}] {step.tool}({args}) -> {status}")
    if step.thought:
        print(f"     thought: {step.thought}")


def _cmd_run(ns: argparse.Namespace) -> int:
    if ns.issue_file:
        issue = Path(ns.issue_file).read_text(encoding="utf-8")
    else:
        issue = ns.issue or ""
    if not issue.strip():
        print("error: provide --issue or --issue-file", file=sys.stderr)
        return 2

    settings = Settings.from_env()
    if ns.provider:
        settings = replace(settings, provider=ns.provider)
    if ns.max_steps:
        settings = replace(settings, max_steps=ns.max_steps)

    print(f"DevPilot {__version__} | provider={settings.provider} | repo={ns.repo}")
    result = run_task(
        Path(ns.repo), issue, settings=settings, test_command=ns.test_command,
        on_step=None if ns.quiet else _print_step,
    )

    out_dir = Path(ns.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "patch.diff").write_text(result.diff, encoding="utf-8")
    (out_dir / "PR_SUMMARY.md").write_text(render_pr_summary(issue, result), encoding="utf-8")
    (out_dir / "run.json").write_text(result.model_dump_json(indent=2), encoding="utf-8")

    print(f"\nstatus: {result.status.value} | tests_passed: {result.tests_passed}")
    print(f"summary: {result.summary}")
    print(f"changed: {', '.join(result.changed_files) or 'none'}")
    print(f"artifacts written to {out_dir}/ (patch.diff, PR_SUMMARY.md, run.json)")
    return 0 if result.status.value == "completed" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="devpilot", description="Autonomous AI SWE agent")
    parser.add_argument("--version", action="version", version=f"devpilot {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="resolve an issue against a repository")
    run.add_argument("--repo", required=True, help="path to the target repository")
    group = run.add_mutually_exclusive_group()
    group.add_argument("--issue", help="issue text")
    group.add_argument("--issue-file", help="file containing the issue text")
    run.add_argument("--test-command", help="override the detected test command")
    run.add_argument("--provider", choices=["mock", "openai"], help="LLM provider override")
    run.add_argument("--max-steps", type=int, help="maximum agent steps")
    run.add_argument("--out", default="runs/latest", help="output directory for artifacts")
    run.add_argument("--quiet", action="store_true", help="do not print each step")
    run.set_defaults(func=_cmd_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    ns = build_parser().parse_args(argv)
    code: int = ns.func(ns)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
