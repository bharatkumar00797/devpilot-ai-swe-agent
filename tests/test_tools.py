from __future__ import annotations

from pathlib import Path

from devpilot.sandbox import CommandRunner, Workspace
from devpilot.tools import build_default_registry, detect_test_command


def test_registry_validates_and_reports_errors(sample_repo: Path) -> None:
    with Workspace.from_source(sample_repo) as ws:
        registry = build_default_registry(ws, CommandRunner(ws.root))
        assert detect_test_command(ws) == "pytest -q"

        missing = registry.execute("read_file", {})
        assert not missing.ok and "Missing required argument" in missing.output

        unknown_arg = registry.execute("read_file", {"path": "calculator.py", "evil": 1})
        assert not unknown_arg.ok

        escape = registry.execute("read_file", {"path": "../../etc/passwd"})
        assert not escape.ok and "SandboxViolation" in escape.output

        blocked = registry.execute("run_command", {"command": "curl http://x"})
        assert not blocked.ok and "not allowed" in blocked.output

        unknown_tool = registry.execute("format_disk", {})
        assert not unknown_tool.ok

        ok = registry.execute("read_file", {"path": "calculator.py", "start_line": "4"})
        assert ok.ok and "def add" in ok.output


def test_describe_lists_all_tools(sample_repo: Path) -> None:
    with Workspace.from_source(sample_repo) as ws:
        text = build_default_registry(ws, CommandRunner(ws.root)).describe()
    for name in ["list_files", "read_file", "search_code", "replace_in_file", "run_tests"]:
        assert f"- {name}(" in text
