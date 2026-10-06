"""Guarded command execution inside a workspace.

Guardrails:
* commands are parsed with ``shlex`` and executed without a shell
* only allowlisted command prefixes may run (test runners and linters)
* hard wall-clock timeout; the whole process group is killed on expiry
* scrubbed environment: API keys and other secrets are never inherited
* optional network isolation via ``unshare -rn`` (Linux user namespaces)
* POSIX resource limits on CPU time and written file size
* output is truncated so a noisy test suite cannot flood the model context
"""

from __future__ import annotations

import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from devpilot.sandbox.workspace import SandboxViolation

DEFAULT_ALLOWLIST: tuple[tuple[str, ...], ...] = (
    ("pytest",),
    ("python", "-m", "pytest"),
    ("python", "-m", "unittest"),
    ("npm", "test"),
    ("npm", "run", "test"),
    ("npm", "run", "lint"),
    ("go", "test"),
    ("go", "vet"),
    ("cargo", "test"),
    ("ruff", "check"),
)
_SHELL_META = set(";|&`$<>\n")
_ENV_PASSTHROUGH = ("PATH", "LANG", "LC_ALL", "TZ", "SYSTEMROOT")


@dataclass(frozen=True)
class CommandResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_s: float
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def format(self) -> str:
        status = "TIMEOUT" if self.timed_out else f"exit_code={self.exit_code}"
        parts = [f"$ {self.command}", f"[{status}, {self.duration_s:.1f}s]"]
        if self.stdout.strip():
            parts.append(self.stdout.rstrip())
        if self.stderr.strip():
            parts.append("--- stderr ---\n" + self.stderr.rstrip())
        return "\n".join(parts)


def truncate_middle(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    omitted = len(text) - limit
    return f"{text[:half]}\n... [{omitted} characters truncated] ...\n{text[-half:]}"


@lru_cache(maxsize=1)
def network_isolation_available() -> bool:
    """Probe once whether unprivileged network namespaces work on this host."""
    if not sys.platform.startswith("linux") or shutil.which("unshare") is None:
        return False
    try:
        probe = subprocess.run(
            ["unshare", "-rn", "true"], capture_output=True, timeout=5, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return probe.returncode == 0


class CommandRunner:
    def __init__(
        self,
        cwd: Path,
        *,
        allowlist: Sequence[tuple[str, ...]] = DEFAULT_ALLOWLIST,
        timeout_s: int = 60,
        max_output_chars: int = 8_000,
        isolate_network: bool = True,
    ) -> None:
        self.cwd = cwd
        self.allowlist = tuple(allowlist)
        self.timeout_s = timeout_s
        self.max_output_chars = max_output_chars
        self.isolate_network = isolate_network and network_isolation_available()

    def parse(self, command: str) -> list[str]:
        if not command or len(command) > 500:
            raise SandboxViolation("Command is empty or too long")
        if any(ch in _SHELL_META for ch in command):
            raise SandboxViolation("Shell operators are not allowed")
        argv = shlex.split(command)
        if not any(tuple(argv[: len(prefix)]) == prefix for prefix in self.allowlist):
            allowed = ", ".join(" ".join(p) for p in self.allowlist)
            raise SandboxViolation(f"Command not allowed: {argv[0]!r}. Allowed: {allowed}")
        for arg in argv[1:]:
            if arg.startswith("/") or ".." in Path(arg).parts:
                raise SandboxViolation(f"Arguments must stay inside the workspace: {arg}")
        return argv

    def _resolve_argv(self, argv: list[str]) -> list[str]:
        # Run Python tooling with the current interpreter so it works inside venvs.
        if argv[0] == "pytest":
            argv = [sys.executable, "-m", "pytest", *argv[1:]]
        elif argv[0] == "python":
            argv = [sys.executable, *argv[1:]]
        if self.isolate_network:
            argv = ["unshare", "-rn", *argv]
        return argv

    def _env(self) -> dict[str, str]:
        env = {k: os.environ[k] for k in _ENV_PASSTHROUGH if k in os.environ}
        env.update(
            HOME=str(self.cwd),
            PYTHONDONTWRITEBYTECODE="1",
            PYTHONHASHSEED="0",
            PIP_NO_INPUT="1",
            NO_COLOR="1",
            CI="1",
        )
        return env

    def _limits(self) -> None:  # pragma: no cover - runs in the child process
        import resource

        cpu = self.timeout_s + 5
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
        fsize = 64 * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))

    def run(self, command: str) -> CommandResult:
        argv = self._resolve_argv(self.parse(command))
        posix = os.name == "posix"
        start = time.monotonic()
        proc = subprocess.Popen(
            argv,
            cwd=self.cwd,
            env=self._env(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=posix,
            preexec_fn=self._limits if posix else None,
        )
        timed_out = False
        try:
            stdout, stderr = proc.communicate(timeout=self.timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            if posix:
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
            stdout, stderr = proc.communicate()
        return CommandResult(
            command=command,
            exit_code=proc.returncode if not timed_out else -9,
            stdout=truncate_middle(stdout or "", self.max_output_chars),
            stderr=truncate_middle(stderr or "", self.max_output_chars // 2),
            duration_s=time.monotonic() - start,
            timed_out=timed_out,
        )
