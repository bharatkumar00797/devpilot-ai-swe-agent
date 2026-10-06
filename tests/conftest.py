from __future__ import annotations

import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_REPO = ROOT / "examples" / "buggy-calculator"
EXAMPLE_ISSUE = ROOT / "examples" / "issues" / "buggy-calculator.md"


@pytest.fixture()
def sample_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "sample"
    shutil.copytree(EXAMPLE_REPO, repo)
    return repo


@pytest.fixture()
def issue_text() -> str:
    return EXAMPLE_ISSUE.read_text(encoding="utf-8")
