"""Configuration for the HTTP service, loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from devpilot.config import env_bool, env_int


def _env_list(name: str) -> tuple[str, ...]:
    raw = os.getenv(name, "")
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def default_demo_dir() -> Path:
    """Locate the bundled demo repositories (``examples/`` in a source checkout)."""
    configured = os.getenv("DEVPILOT_DEMO_DIR")
    if configured:
        return Path(configured)
    source_checkout = Path(__file__).resolve().parents[3] / "examples"
    if source_checkout.is_dir():
        return source_checkout
    return Path.cwd() / "examples"


def running_serverless() -> bool:
    """True on serverless platforms where background threads do not outlive a request."""
    return any(os.getenv(name) for name in ("VERCEL", "AWS_LAMBDA_FUNCTION_NAME"))


@dataclass(frozen=True)
class ApiSettings:
    """Service settings.

    Access modes:

    * ``api_keys`` set     -> every ``/api`` call needs ``X-API-Key`` (or a Bearer token).
    * ``dev_mode`` enabled -> no auth; meant for ``localhost`` use only.
    * neither              -> public demo mode: anonymous access, bundled demos only,
                              offline mock provider only.

    ``sync_runs`` executes each run inside the ``POST /api/runs`` request instead of a
    background worker. It is required on serverless hosts (enabled automatically when
    ``VERCEL`` or ``AWS_LAMBDA_FUNCTION_NAME`` is set) because work started in a thread
    is frozen or killed once the response has been sent.
    """

    api_keys: tuple[str, ...] = ()
    dev_mode: bool = False
    repo_allowlist: tuple[Path, ...] = ()
    demo_dir: Path = field(default_factory=default_demo_dir)
    cors_origins: tuple[str, ...] = ()
    rate_limit_per_minute: int = 60
    run_limit_per_minute: int = 6
    max_concurrent_runs: int = 2
    max_queued_runs: int = 8
    max_runs_kept: int = 200
    max_steps_cap: int = 30
    trust_proxy: bool = False
    sync_runs: bool = False

    @property
    def auth_enabled(self) -> bool:
        return bool(self.api_keys)

    @property
    def access_mode(self) -> Literal["api-key", "dev", "public-demo"]:
        if self.api_keys:
            return "api-key"
        return "dev" if self.dev_mode else "public-demo"

    @property
    def public_demo(self) -> bool:
        """True when anonymous callers are limited to demos and the mock provider."""
        return not self.api_keys and not self.dev_mode

    @classmethod
    def from_env(cls) -> ApiSettings:
        return cls(
            api_keys=_env_list("DEVPILOT_API_KEYS"),
            dev_mode=env_bool("DEVPILOT_DEV_MODE", False),
            repo_allowlist=tuple(Path(p) for p in _env_list("DEVPILOT_REPO_ALLOWLIST")),
            demo_dir=default_demo_dir(),
            cors_origins=_env_list("DEVPILOT_CORS_ORIGINS"),
            rate_limit_per_minute=env_int("DEVPILOT_RATE_LIMIT_PER_MINUTE", 60),
            run_limit_per_minute=env_int("DEVPILOT_RUN_LIMIT_PER_MINUTE", 6),
            max_concurrent_runs=max(1, env_int("DEVPILOT_MAX_CONCURRENT_RUNS", 2)),
            max_queued_runs=max(1, env_int("DEVPILOT_MAX_QUEUED_RUNS", 8)),
            max_runs_kept=max(10, env_int("DEVPILOT_MAX_RUNS_KEPT", 200)),
            max_steps_cap=max(1, env_int("DEVPILOT_MAX_STEPS_CAP", 30)),
            trust_proxy=env_bool("DEVPILOT_TRUST_PROXY", False),
            sync_runs=env_bool("DEVPILOT_SYNC_RUNS", running_serverless()),
        )
