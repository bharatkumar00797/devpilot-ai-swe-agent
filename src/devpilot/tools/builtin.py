"""Built-in tools that operate on a sandboxed workspace."""

from __future__ import annotations

from typing import Any

from devpilot.sandbox import CommandRunner, Workspace
from devpilot.tools.registry import Tool, ToolRegistry, ToolResult


def detect_test_command(workspace: Workspace) -> str:
    """Best-effort guess of how to run the target project's tests."""
    files = set(workspace.list_files(limit=5_000))
    top = {f.split("/", 1)[0] for f in files}
    if "package.json" in files:
        return "npm test"
    if "go.mod" in files:
        return "go test ./..."
    if "Cargo.toml" in files:
        return "cargo test"
    if top & {"tests", "test", "pyproject.toml", "pytest.ini", "setup.cfg", "tox.ini"}:
        return "pytest -q"
    return "python -m unittest"


def build_default_registry(
    workspace: Workspace, runner: CommandRunner, *, test_command: str | None = None
) -> ToolRegistry:
    test_cmd = test_command or detect_test_command(workspace)
    registry = ToolRegistry()

    def list_files(args: dict[str, Any]) -> ToolResult:
        files = workspace.list_files(args.get("path", "."))
        return ToolResult(True, "\n".join(files) or "(no files)", {"count": len(files)})

    def read_file(args: dict[str, Any]) -> ToolResult:
        text = workspace.read_text(
            args["path"], args.get("start_line", 1), args.get("end_line")
        )
        return ToolResult(True, text or "(empty file)")

    def search_code(args: dict[str, Any]) -> ToolResult:
        hits = workspace.search(args["query"], regex=args.get("regex", False))
        if not hits:
            return ToolResult(True, "No matches.", {"count": 0})
        return ToolResult(True, "\n".join(h.format() for h in hits), {"count": len(hits)})

    def replace_in_file(args: dict[str, Any]) -> ToolResult:
        line = workspace.replace(args["path"], args["old"], args["new"])
        return ToolResult(True, f"Edited {args['path']} at line {line}.", {"path": args["path"]})

    def write_file(args: dict[str, Any]) -> ToolResult:
        workspace.write_text(args["path"], args["content"])
        return ToolResult(True, f"Wrote {args['path']}.", {"path": args["path"]})

    def run_tests(args: dict[str, Any]) -> ToolResult:
        command = test_cmd
        if args.get("target"):
            command = f"{test_cmd} {args['target']}"
        result = runner.run(command)
        return ToolResult(
            True, result.format(), {"exit_code": result.exit_code, "passed": result.ok}
        )

    def run_command(args: dict[str, Any]) -> ToolResult:
        result = runner.run(args["command"])
        return ToolResult(True, result.format(), {"exit_code": result.exit_code})

    registry.register(Tool(
        "list_files", "List files in the repository (or a sub-directory).",
        {"path": (str, False, "directory relative to the repo root, default '.'")},
        list_files,
    ))
    registry.register(Tool(
        "read_file", "Read a file with line numbers.",
        {
            "path": (str, True, "file path relative to the repo root"),
            "start_line": (int, False, "first line to show (1-based)"),
            "end_line": (int, False, "last line to show (inclusive)"),
        },
        read_file,
    ))
    registry.register(Tool(
        "search_code", "Search all text files for a string or regex.",
        {
            "query": (str, True, "text to search for"),
            "regex": (bool, False, "treat query as a regular expression"),
        },
        search_code,
    ))
    registry.register(Tool(
        "replace_in_file", "Replace one exact, unique snippet of text in a file.",
        {
            "path": (str, True, "file to edit"),
            "old": (str, True, "exact existing text; must occur exactly once"),
            "new": (str, True, "replacement text"),
        },
        replace_in_file,
    ))
    registry.register(Tool(
        "write_file", "Create or overwrite a file with the given content.",
        {
            "path": (str, True, "file to write"),
            "content": (str, True, "full new file content"),
        },
        write_file,
    ))
    registry.register(Tool(
        "run_tests", f"Run the project's test suite (`{test_cmd}`).",
        {"target": (str, False, "optional test file or node id to narrow the run")},
        run_tests,
    ))
    registry.register(Tool(
        "run_command", "Run an allowlisted developer command (tests, linters) in the sandbox.",
        {"command": (str, True, "command line, e.g. 'ruff check .'")},
        run_command,
    ))
    return registry
