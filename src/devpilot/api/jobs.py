"""Background execution of agent runs with bounded concurrency and an in-memory store."""

from __future__ import annotations

import threading
import uuid
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from devpilot.agent import AgentResult, RunStatus, Step, StepCallback
from devpilot.api.schemas import RunState
from devpilot.config import Settings
from devpilot.report import render_pr_summary
from devpilot.service import run_task

TaskFn = Callable[[Path, str, Settings, StepCallback], AgentResult]
ACTIVE_STATES: frozenset[RunState] = frozenset({"queued", "running"})
_FINAL_STATE: dict[RunStatus, RunState] = {
    RunStatus.COMPLETED: "completed",
    RunStatus.MAX_STEPS: "max_steps",
    RunStatus.FAILED: "failed",
}


def default_task(repo: Path, issue: str, settings: Settings, on_step: StepCallback) -> AgentResult:
    return run_task(repo, issue, settings=settings, on_step=on_step)


def _now() -> datetime:
    return datetime.now(UTC)


class QueueFull(RuntimeError):
    """Too many runs are queued or executing."""


@dataclass
class RunRecord:
    id: str
    owner: str
    repo_label: str
    repo_path: Path
    issue: str
    provider: str
    max_steps: int
    created_at: datetime = field(default_factory=_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    status: RunState = "queued"
    steps: list[Step] = field(default_factory=list)
    result: AgentResult | None = None
    pr_summary: str = ""
    error: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def done(self) -> bool:
        return self.status not in ACTIVE_STATES

    @property
    def title(self) -> str:
        first = self.issue.strip().splitlines()[0] if self.issue.strip() else ""
        return first.lstrip("# ").strip()[:80]

    def add_step(self, step: Step) -> None:
        with self.lock:
            self.steps.append(step)

    def steps_since(self, cursor: int) -> list[Step]:
        with self.lock:
            return list(self.steps[max(0, cursor) :])


class RunManager:
    """Owns the worker pool and the run records.

    Runs execute in a thread pool (the agent loop is synchronous and spends most of
    its time in subprocesses or HTTP calls). ``max_active`` bounds queued + running
    work so a burst of requests cannot pile up unbounded jobs; old finished runs are
    evicted once ``max_kept`` is exceeded.
    """

    def __init__(
        self,
        *,
        max_workers: int = 2,
        max_active: int = 8,
        max_kept: int = 200,
        task_fn: TaskFn = default_task,
    ) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="devpilot")
        self._max_active = max_active
        self._max_kept = max_kept
        self._task_fn = task_fn
        self._runs: OrderedDict[str, RunRecord] = OrderedDict()
        self._lock = threading.Lock()

    # ----------------------------------------------------------------- public
    def submit(
        self,
        *,
        owner: str,
        repo_label: str,
        repo_path: Path,
        issue: str,
        settings: Settings,
    ) -> RunRecord:
        record = RunRecord(
            id=uuid.uuid4().hex,
            owner=owner,
            repo_label=repo_label,
            repo_path=repo_path,
            issue=issue,
            provider=settings.provider,
            max_steps=settings.max_steps,
        )
        with self._lock:
            if self.active_count_unlocked() >= self._max_active:
                raise QueueFull("Too many runs in progress; try again shortly")
            self._runs[record.id] = record
            self._evict_unlocked()
        self._executor.submit(self._execute, record, settings)
        return record

    def get(self, run_id: str, owner: str) -> RunRecord | None:
        with self._lock:
            record = self._runs.get(run_id)
        if record is None or record.owner != owner:
            return None
        return record

    def list(self, owner: str, limit: int = 50) -> list[RunRecord]:
        with self._lock:
            records = [r for r in reversed(self._runs.values()) if r.owner == owner]
        return records[:limit]

    def active_count(self) -> int:
        with self._lock:
            return self.active_count_unlocked()

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    # --------------------------------------------------------------- internal
    def active_count_unlocked(self) -> int:
        return sum(1 for r in self._runs.values() if not r.done)

    def _evict_unlocked(self) -> None:
        overflow = len(self._runs) - self._max_kept
        if overflow <= 0:
            return
        for run_id in [rid for rid, r in self._runs.items() if r.done][:overflow]:
            del self._runs[run_id]

    def _execute(self, record: RunRecord, settings: Settings) -> None:
        with record.lock:
            record.status = "running"
            record.started_at = _now()
        try:
            result = self._task_fn(record.repo_path, record.issue, settings, record.add_step)
        except Exception as exc:  # a crashed run must never take down the worker
            with record.lock:
                record.status = "error"
                record.error = f"{type(exc).__name__}: {exc}"[:500]
                record.finished_at = _now()
            return
        pr_summary = render_pr_summary(record.issue, result)
        with record.lock:
            record.result = result
            record.pr_summary = pr_summary
            # The final step list from the result is authoritative.
            record.steps = list(result.steps)
            record.status = _FINAL_STATE[result.status]
            record.finished_at = _now()
