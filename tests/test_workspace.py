from __future__ import annotations

from pathlib import Path

import pytest

from devpilot.sandbox import SandboxViolation, Workspace


def test_workspace_is_a_copy(sample_repo: Path) -> None:
    with Workspace.from_source(sample_repo) as ws:
        ws.replace("calculator.py", "return a - b", "return a + b")
        assert "a + b" in (ws.root / "calculator.py").read_text()
    assert "a - b" in (sample_repo / "calculator.py").read_text()


@pytest.mark.parametrize("bad", ["../outside.txt", "/etc/passwd", "tests/../../x", ""])
def test_path_escape_is_blocked(sample_repo: Path, bad: str) -> None:
    with Workspace.from_source(sample_repo) as ws, pytest.raises(SandboxViolation):
        ws.resolve(bad)


def test_symlink_escape_is_blocked(sample_repo: Path, tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("token")
    (sample_repo / "link.txt").symlink_to(secret)
    with Workspace.from_source(sample_repo) as ws:
        with pytest.raises(SandboxViolation):
            ws.read_text("link.txt")
        assert "link.txt" not in ws.list_files()


def test_secrets_and_git_are_not_copied_or_writable(sample_repo: Path) -> None:
    (sample_repo / ".env").write_text("API_KEY=abc")
    (sample_repo / ".git").mkdir()
    (sample_repo / ".git" / "config").write_text("[core]")
    with Workspace.from_source(sample_repo) as ws:
        assert not (ws.root / ".env").exists()
        assert not (ws.root / ".git").exists()
        with pytest.raises(SandboxViolation):
            ws.write_text(".env", "X=1")
        with pytest.raises(SandboxViolation):
            ws.write_text(".git/hooks/pre-commit", "evil")


def test_replace_requires_unique_match(sample_repo: Path) -> None:
    with Workspace.from_source(sample_repo) as ws:
        with pytest.raises(ValueError, match="occurs"):
            ws.replace("calculator.py", "def ", "def  ")
        with pytest.raises(ValueError, match="not found"):
            ws.replace("calculator.py", "does-not-exist", "x")


def test_search_and_diff(sample_repo: Path) -> None:
    with Workspace.from_source(sample_repo) as ws:
        hits = ws.search("def add")
        assert [h.path for h in hits] == ["calculator.py"]
        assert ws.diff() == ""
        ws.replace("calculator.py", "return a - b", "return a + b")
        ws.write_text("NOTES.md", "new file\n")
        diff = ws.diff()
        assert "-    return a - b" in diff
        assert "+    return a + b" in diff
        assert "+++ b/NOTES.md" in diff
        assert ws.changed_files() == ["NOTES.md", "calculator.py"]
