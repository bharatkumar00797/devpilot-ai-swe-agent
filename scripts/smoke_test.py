"""Smoke-test a running DevPilot server: health, config, and every bundled demo.

Usage: python scripts/smoke_test.py [BASE_URL]   (default http://127.0.0.1:8000)

Standard library only, so it runs anywhere (CI, a laptop, against a deployment).
Works with both background mode (polls the trace) and sync/serverless mode.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any

TIMEOUT_S = 120


def call(base: str, path: str, body: dict[str, Any] | None = None) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        base + path,
        data=data,
        method="POST" if data else "GET",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        return json.load(response)


def wait_healthy(base: str) -> dict[str, Any]:
    deadline = time.monotonic() + 60
    while True:
        try:
            health: dict[str, Any] = call(base, "/healthz")
            return health
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            if time.monotonic() > deadline:
                raise
            time.sleep(1)


def run_demo(base: str, demo: dict[str, Any]) -> dict[str, Any]:
    run: dict[str, Any] = call(base, "/api/runs", {"repo": demo["repo"], "issue": demo["issue"]})
    deadline = time.monotonic() + TIMEOUT_S
    while run["status"] in {"queued", "running"}:
        if time.monotonic() > deadline:
            raise TimeoutError(f"{demo['name']} did not finish")
        time.sleep(0.5)
        run = call(base, f"/api/runs/{run['id']}")
    return run


def main() -> int:
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
    health = wait_healthy(base)
    config = call(base, "/api/config")
    print(
        f"healthy: v{health['version']} | mode={config['access_mode']} | sync={config['sync_runs']}"
    )
    if not config["demos"]:
        print("FAIL: no demo repositories found")
        return 1
    failures = 0
    for demo in config["demos"]:
        run = run_demo(base, demo)
        ok = run["status"] == "completed" and run["tests_passed"] is True
        failures += not ok
        files = ", ".join(run["changed_files"]) or "none"
        print(
            f"{'PASS' if ok else 'FAIL'}: {demo['name']} -> {run['status']}, "
            f"tests_passed={run['tests_passed']}, steps={run['step_count']}, changed={files}"
        )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
