"""Resolve the repository a run should operate on, enforcing the directory allowlist."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

DEMO_PREFIX = "demo:"
_DEMO_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class RepoNotAllowed(PermissionError):
    """The requested repository is outside every allowed location."""


@dataclass(frozen=True)
class DemoRepo:
    name: str
    path: Path
    issue: str


class RepoResolver:
    """Maps a ``repo`` request field to a real directory.

    Accepted forms:

    * ``demo:<name>`` -> a bundled demo under ``demo_dir`` (always allowed)
    * an absolute path that, after resolving symlinks and ``..``, lives inside one
      of the allowlisted roots (only when path access is enabled)
    """

    def __init__(self, demo_dir: Path, allowlist: tuple[Path, ...], *, allow_paths: bool) -> None:
        self.demo_dir = demo_dir.resolve()
        self.allowlist = tuple(p.resolve() for p in allowlist)
        self.allow_paths = allow_paths and bool(self.allowlist)

    def demos(self) -> list[DemoRepo]:
        if not self.demo_dir.is_dir():
            return []
        issues_dir = self.demo_dir / "issues"
        found: list[DemoRepo] = []
        for child in sorted(self.demo_dir.iterdir()):
            if child.name == "issues" or not child.is_dir() or not _DEMO_NAME.match(child.name):
                continue
            issue_file = issues_dir / f"{child.name}.md"
            issue = issue_file.read_text(encoding="utf-8") if issue_file.is_file() else ""
            found.append(DemoRepo(child.name, child, issue))
        return found

    def resolve(self, repo: str) -> Path:
        if repo.startswith(DEMO_PREFIX):
            name = repo[len(DEMO_PREFIX) :]
            for demo in self.demos():
                if demo.name == name:
                    return demo.path
            raise RepoNotAllowed(f"Unknown demo repository {name!r}")

        if not self.allow_paths:
            raise RepoNotAllowed("Only bundled demo repositories are enabled on this server")
        raw = Path(repo)
        if not raw.is_absolute():
            raise RepoNotAllowed("Repository path must be absolute")
        try:
            resolved = raw.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise RepoNotAllowed("Repository path does not exist") from exc
        if not resolved.is_dir():
            raise RepoNotAllowed("Repository path is not a directory")
        if not any(resolved.is_relative_to(root) for root in self.allowlist):
            raise RepoNotAllowed("Repository path is outside the allowed directories")
        return resolved
