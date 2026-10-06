"""Isolated copy of a target repository that the agent is allowed to modify.

The agent never touches the user's checkout. Every run works on a throwaway copy,
every path is validated against the workspace root, and the final result is a
unified diff against the original snapshot.
"""

from __future__ import annotations

import difflib
import fnmatch
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

DEFAULT_IGNORES: tuple[str, ...] = (
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".tox",
    ".env",
)
PROTECTED_PATTERNS: tuple[str, ...] = (".git/*", ".env", ".env.*", "*.pem", "*.key", "id_rsa*")


class SandboxViolation(PermissionError):
    """Raised when an operation would escape or abuse the sandbox."""


@dataclass(frozen=True)
class SearchHit:
    path: str
    line_no: int
    line: str

    def format(self) -> str:
        return f"{self.path}:{self.line_no}: {self.line.strip()}"


class Workspace:
    def __init__(
        self,
        root: Path,
        *,
        max_file_bytes: int = 256_000,
        owns_root: bool = False,
    ) -> None:
        self.root = root.resolve()
        self.max_file_bytes = max_file_bytes
        self._owns_root = owns_root
        self._snapshot: dict[str, str] = self._read_all_text()

    # ------------------------------------------------------------ lifecycle
    @classmethod
    def from_source(
        cls,
        source: Path,
        *,
        base_dir: Path | None = None,
        ignore: tuple[str, ...] = DEFAULT_IGNORES,
        max_file_bytes: int = 256_000,
    ) -> Workspace:
        source = source.resolve()
        if not source.is_dir():
            raise FileNotFoundError(f"Repository not found: {source}")
        tmp = Path(tempfile.mkdtemp(prefix="devpilot-", dir=base_dir))
        target = tmp / "repo"
        shutil.copytree(source, target, ignore=shutil.ignore_patterns(*ignore), symlinks=True)
        return cls(target, max_file_bytes=max_file_bytes, owns_root=True)

    def cleanup(self) -> None:
        if self._owns_root:
            shutil.rmtree(self.root.parent, ignore_errors=True)

    def __enter__(self) -> Workspace:
        return self

    def __exit__(self, *exc: object) -> None:
        self.cleanup()

    # --------------------------------------------------------------- paths
    def resolve(self, rel_path: str, *, for_write: bool = False) -> Path:
        if not rel_path or "\x00" in rel_path:
            raise SandboxViolation("Empty or invalid path")
        candidate = Path(rel_path)
        if candidate.is_absolute():
            raise SandboxViolation(f"Absolute paths are not allowed: {rel_path}")
        resolved = (self.root / candidate).resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise SandboxViolation(f"Path escapes the workspace: {rel_path}")
        rel = resolved.relative_to(self.root).as_posix()
        if for_write and any(fnmatch.fnmatch(rel, p) for p in PROTECTED_PATTERNS):
            raise SandboxViolation(f"Path is protected: {rel_path}")
        if any(fnmatch.fnmatch(rel, p) for p in (".env", ".env.*")):
            raise SandboxViolation(f"Secret files are not accessible: {rel_path}")
        return resolved

    def _rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def _iter_files(self, start: Path | None = None) -> list[Path]:
        base = start or self.root
        files = [
            p
            for p in base.rglob("*")
            if p.is_file()
            and not p.is_symlink()
            and not any(part in DEFAULT_IGNORES for part in p.relative_to(self.root).parts)
        ]
        return sorted(files)

    def _read_all_text(self) -> dict[str, str]:
        snapshot: dict[str, str] = {}
        for path in self._iter_files():
            text = self._try_read(path)
            if text is not None:
                snapshot[self._rel(path)] = text
        return snapshot

    def _try_read(self, path: Path) -> str | None:
        if path.stat().st_size > self.max_file_bytes:
            return None
        try:
            return path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            return None

    # ----------------------------------------------------------- file ops
    def list_files(self, subdir: str = ".", limit: int = 400) -> list[str]:
        start = self.resolve(subdir)
        if not start.is_dir():
            raise NotADirectoryError(f"Not a directory: {subdir}")
        return [self._rel(p) for p in self._iter_files(start)][:limit]

    def read_text(self, rel_path: str, start_line: int = 1, end_line: int | None = None) -> str:
        path = self.resolve(rel_path)
        if not path.is_file():
            raise FileNotFoundError(f"No such file: {rel_path}")
        text = self._try_read(path)
        if text is None:
            raise ValueError(f"File is binary or larger than {self.max_file_bytes} bytes")
        lines = text.splitlines()
        start = max(1, start_line)
        end = len(lines) if end_line is None else min(len(lines), end_line)
        return "\n".join(f"{n:>4} | {lines[n - 1]}" for n in range(start, end + 1))

    def write_text(self, rel_path: str, content: str) -> None:
        if len(content.encode("utf-8")) > self.max_file_bytes:
            raise SandboxViolation("Refusing to write a file larger than the size limit")
        path = self.resolve(rel_path, for_write=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def replace(self, rel_path: str, old: str, new: str) -> int:
        """Replace exactly one occurrence of ``old``; ambiguity is an error."""
        if not old:
            raise ValueError("'old' must not be empty")
        path = self.resolve(rel_path, for_write=True)
        if not path.is_file():
            raise FileNotFoundError(f"No such file: {rel_path}")
        text = path.read_text(encoding="utf-8")
        count = text.count(old)
        if count == 0:
            raise ValueError(f"Text to replace was not found in {rel_path}")
        if count > 1:
            raise ValueError(
                f"Text to replace occurs {count} times in {rel_path}; include more context"
            )
        updated = text.replace(old, new, 1)
        self.write_text(rel_path, updated)
        return text[: text.index(old)].count("\n") + 1

    def search(self, query: str, *, regex: bool = False, limit: int = 50) -> list[SearchHit]:
        if not query:
            raise ValueError("Search query must not be empty")
        if len(query) > 200:
            raise ValueError("Search query is too long")
        pattern = re.compile(query if regex else re.escape(query))
        hits: list[SearchHit] = []
        for path in self._iter_files():
            text = self._try_read(path)
            if text is None:
                continue
            for line_no, line in enumerate(text.splitlines(), start=1):
                if pattern.search(line):
                    hits.append(SearchHit(self._rel(path), line_no, line[:200]))
                    if len(hits) >= limit:
                        return hits
        return hits

    # --------------------------------------------------------------- diff
    def changed_files(self) -> list[str]:
        current = self._read_all_text()
        keys = set(current) | set(self._snapshot)
        return sorted(k for k in keys if current.get(k) != self._snapshot.get(k))

    def diff(self) -> str:
        current = self._read_all_text()
        chunks: list[str] = []
        for rel in self.changed_files():
            before = self._snapshot.get(rel)
            after = current.get(rel)
            chunks.extend(
                difflib.unified_diff(
                    (before or "").splitlines(keepends=True),
                    (after or "").splitlines(keepends=True),
                    fromfile="/dev/null" if before is None else f"a/{rel}",
                    tofile="/dev/null" if after is None else f"b/{rel}",
                )
            )
        return "".join(chunks)
