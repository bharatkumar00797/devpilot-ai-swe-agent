from __future__ import annotations

from pathlib import Path

import pytest

from devpilot.sandbox import CommandRunner, SandboxViolation


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /",
        "curl https://example.com",
        "python -c 'print(1)'",
        "pytest; rm -rf .",
        "pytest && echo hi",
        "pytest $(whoami)",
        "pytest /etc",
        "pytest ../other",
        "",
    ],
)
def test_disallowed_commands(tmp_path: Path, command: str) -> None:
    runner = CommandRunner(tmp_path)
    with pytest.raises(SandboxViolation):
        runner.parse(command)


def test_runs_allowlisted_tests(sample_repo: Path) -> None:
    result = CommandRunner(sample_repo, timeout_s=60).run("pytest -q")
    assert result.exit_code == 1  # the demo repo ships with a failing test
    assert "test_add" in result.stdout


def test_timeout_kills_process(tmp_path: Path) -> None:
    (tmp_path / "test_slow.py").write_text("import time\n\ndef test_slow():\n    time.sleep(30)\n")
    result = CommandRunner(tmp_path, timeout_s=2).run("pytest -q")
    assert result.timed_out
    assert not result.ok
    assert result.duration_s < 15


def test_environment_is_scrubbed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEVPILOT_API_KEY", "super-secret")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-secret")
    (tmp_path / "test_env.py").write_text(
        "import os\n\n"
        "def test_env():\n"
        "    assert 'DEVPILOT_API_KEY' not in os.environ\n"
        "    assert 'AWS_SECRET_ACCESS_KEY' not in os.environ\n"
    )
    result = CommandRunner(tmp_path, timeout_s=30).run("pytest -q")
    assert result.ok, result.format()


def test_output_is_truncated(tmp_path: Path) -> None:
    (tmp_path / "test_noisy.py").write_text("def test_noisy():\n    print('x' * 50000)\n")
    result = CommandRunner(tmp_path, timeout_s=30, max_output_chars=1000).run("pytest -q -s")
    assert len(result.stdout) < 1200
    assert "truncated" in result.stdout
