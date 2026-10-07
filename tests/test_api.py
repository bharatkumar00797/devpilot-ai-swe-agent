from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from devpilot.agent import AgentResult, StepCallback
from devpilot.api import ApiSettings, create_app
from devpilot.api.security import ApiKeyAuth, RateLimiter
from devpilot.config import Settings

ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = ROOT / "examples"
EXAMPLE_ISSUE = DEMO_DIR / "issues" / "buggy-calculator.md"
AGENT = Settings(provider="mock", max_steps=12, command_timeout=60)
KEY = "test-key-123"


def _client(**overrides: Any) -> TestClient:
    options: dict[str, Any] = {"demo_dir": DEMO_DIR, "api_keys": (KEY,), **overrides}
    settings = ApiSettings(**options)
    return TestClient(create_app(settings, agent_settings=AGENT))


def _auth() -> dict[str, str]:
    return {"X-API-Key": KEY}


def _wait(client: TestClient, run_id: str, timeout: float = 60) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        trace = client.get(f"/api/runs/{run_id}/trace", headers=_auth()).json()
        if trace["done"]:
            detail: dict[str, Any] = client.get(f"/api/runs/{run_id}", headers=_auth()).json()
            return detail
        time.sleep(0.1)
    raise AssertionError("run did not finish in time")


def test_health_and_config_are_public() -> None:
    with _client() as client:
        assert client.get("/healthz").json()["status"] == "ok"
        cfg = client.get("/api/config").json()
        assert cfg["auth_required"] is True
        assert "buggy-calculator" in [d["name"] for d in cfg["demos"]]
        assert "add() returns" in cfg["demos"][0]["issue"]


def test_api_requires_valid_key() -> None:
    with _client() as client:
        assert client.get("/api/runs").status_code == 401
        assert client.get("/api/runs", headers={"X-API-Key": "wrong"}).status_code == 401
        assert client.get("/api/runs", headers=_auth()).status_code == 200
        bearer = {"Authorization": f"Bearer {KEY}"}
        assert client.get("/api/runs", headers=bearer).status_code == 200


def test_full_mock_run_on_demo_repo() -> None:
    issue = EXAMPLE_ISSUE.read_text(encoding="utf-8")
    with _client() as client:
        resp = client.post(
            "/api/runs", json={"repo": "demo:buggy-calculator", "issue": issue}, headers=_auth()
        )
        assert resp.status_code == 202, resp.text
        run_id = resp.json()["id"]
        detail = _wait(client, run_id)

        assert detail["status"] == "completed"
        assert detail["tests_passed"] is True
        assert detail["changed_files"] == ["calculator.py"]
        assert "+    return a + b" in detail["diff"]
        assert "Tests: **passing**" in detail["pr_summary"]

        trace = client.get(f"/api/runs/{run_id}/trace", headers=_auth()).json()
        assert trace["steps"][0]["tool"] == "list_files"
        assert trace["steps"][-1]["tool"] == "finish"
        tail = client.get(
            f"/api/runs/{run_id}/trace", params={"since": trace["next_cursor"]}, headers=_auth()
        ).json()
        assert tail["steps"] == []

        listed = client.get("/api/runs", headers=_auth()).json()["runs"]
        assert listed[0]["id"] == run_id
        # demo checkout untouched
        assert "return a - b" in (DEMO_DIR / "buggy-calculator" / "calculator.py").read_text()


def test_runs_are_scoped_to_their_key() -> None:
    with _client(api_keys=(KEY, "other-key")) as client:
        resp = client.post(
            "/api/runs", json={"repo": "demo:buggy-calculator", "issue": "x"}, headers=_auth()
        )
        run_id = resp.json()["id"]
        other = {"X-API-Key": "other-key"}
        assert client.get(f"/api/runs/{run_id}", headers=other).status_code == 404
        assert client.get("/api/runs", headers=other).json()["runs"] == []
        _wait(client, run_id)


def test_rate_limit_returns_429() -> None:
    with _client(rate_limit_per_minute=3) as client:
        codes = [client.get("/api/runs", headers=_auth()).status_code for _ in range(4)]
        assert codes == [200, 200, 200, 429]
        limited = client.get("/api/runs", headers=_auth())
        assert int(limited.headers["Retry-After"]) >= 1


def test_run_creation_has_its_own_limit() -> None:
    with _client(run_limit_per_minute=1) as client:
        body = {"repo": "demo:buggy-calculator", "issue": "The add function is broken."}
        first = client.post("/api/runs", json=body, headers=_auth())
        assert first.status_code == 202
        assert client.post("/api/runs", json=body, headers=_auth()).status_code == 429
        _wait(client, first.json()["id"])


def test_repo_outside_allowlist_is_rejected(tmp_path: Path, sample_repo: Path) -> None:
    allowed = sample_repo.parent
    outside = tmp_path.parent / "elsewhere"
    with _client(repo_allowlist=(allowed,)) as client:
        for repo in [
            str(outside),
            "/etc",
            f"{allowed}/../..",
            "relative/path",
            "demo:does-not-exist",
            "demo:../../etc",
        ]:
            resp = client.post("/api/runs", json={"repo": repo, "issue": "x"}, headers=_auth())
            assert resp.status_code == 403, (repo, resp.text)

        # a symlink inside the allowlist that points outside it is also rejected
        (allowed / "escape").symlink_to("/etc")
        resp = client.post(
            "/api/runs", json={"repo": str(allowed / "escape"), "issue": "x"}, headers=_auth()
        )
        assert resp.status_code == 403

        ok = client.post(
            "/api/runs", json={"repo": str(sample_repo), "issue": "x"}, headers=_auth()
        )
        assert ok.status_code == 202
        _wait(client, ok.json()["id"])


def test_public_demo_mode_restricts_paths_and_providers(sample_repo: Path) -> None:
    settings = ApiSettings(demo_dir=DEMO_DIR, repo_allowlist=(sample_repo.parent,))
    with TestClient(create_app(settings, agent_settings=AGENT)) as client:
        cfg = client.get("/api/config").json()
        assert cfg["access_mode"] == "public-demo" and cfg["allow_paths"] is False
        body = {"repo": str(sample_repo), "issue": "x"}
        assert client.post("/api/runs", json=body).status_code == 403
        body = {"repo": "demo:buggy-calculator", "issue": "x", "provider": "openai"}
        assert client.post("/api/runs", json=body).status_code == 403


@pytest.mark.parametrize(
    "body",
    [
        {"repo": "demo:buggy-calculator", "issue": ""},
        {"repo": "demo:buggy-calculator", "issue": "   "},
        {"repo": "demo:buggy-calculator", "issue": "x" * 8001},
        {"repo": "demo:buggy-calculator", "issue": "x", "max_steps": 0},
        {"repo": "demo:buggy-calculator", "issue": "x", "max_steps": 31},
        {"repo": "demo:buggy-calculator", "issue": "x", "provider": "evil"},
        {"repo": "demo:buggy-calculator", "issue": "x", "unexpected": 1},
        {"repo": "demo:buggy\ncalculator", "issue": "x"},
    ],
)
def test_invalid_payloads_are_rejected(body: dict[str, Any]) -> None:
    with _client() as client:
        assert client.post("/api/runs", json=body, headers=_auth()).status_code == 422


def test_responses_never_leak_provider_key() -> None:
    secret = "sk-super-secret-value"
    agent = Settings(provider="mock", api_key=secret, max_steps=3)
    settings = ApiSettings(demo_dir=DEMO_DIR, api_keys=(KEY,))
    with TestClient(create_app(settings, agent_settings=agent)) as client:
        run_id = client.post(
            "/api/runs", json={"repo": "demo:buggy-calculator", "issue": "x"}, headers=_auth()
        ).json()["id"]
        detail = _wait(client, run_id)
        texts = [client.get("/api/config").text, str(detail), client.get("/healthz").text]
        assert all(secret not in t for t in texts)


def test_dashboard_is_served_with_security_headers() -> None:
    with _client() as client:
        page = client.get("/")
        assert page.status_code == 200 and "DevPilot" in page.text
        assert "default-src 'self'" in page.headers["Content-Security-Policy"]
        assert page.headers["X-Content-Type-Options"] == "nosniff"
        assert client.get("/static/app.js").status_code == 200


def test_oversized_body_is_rejected() -> None:
    with _client() as client:
        resp = client.post(
            "/api/runs",
            content=b"{" + b" " * 70_000 + b"}",
            headers={**_auth(), "Content-Type": "application/json"},
        )
        assert resp.status_code == 413


def test_api_key_auth_and_rate_limiter_units() -> None:
    auth = ApiKeyAuth(("a", "b"))
    assert auth.verify("a") and auth.verify("b")
    assert auth.verify("c") is None and auth.verify(None) is None
    assert auth.verify("a") != auth.verify("b")

    now = [0.0]
    limiter = RateLimiter(2, 10, clock=lambda: now[0])
    assert limiter.check("x") is None and limiter.check("x") is None
    assert limiter.check("x") == pytest.approx(10)
    assert limiter.check("y") is None
    now[0] = 10.5
    assert limiter.check("x") is None


def test_queue_is_bounded_and_crashed_runs_are_reported() -> None:
    release = threading.Event()

    def slow_task(repo: Path, issue: str, settings: Settings, on_step: StepCallback) -> AgentResult:
        release.wait(10)
        raise RuntimeError("boom")

    settings = ApiSettings(demo_dir=DEMO_DIR, api_keys=(KEY,), max_queued_runs=1)
    app = create_app(settings, agent_settings=AGENT, task_fn=slow_task)
    with TestClient(app) as client:
        body = {"repo": "demo:buggy-calculator", "issue": "x"}
        first = client.post("/api/runs", json=body, headers=_auth())
        assert first.status_code == 202
        busy = client.post("/api/runs", json=body, headers=_auth())
        assert busy.status_code == 503 and "Retry-After" in busy.headers
        release.set()
        detail = _wait(client, first.json()["id"])
        assert detail["status"] == "error"
        assert detail["error"] == "RuntimeError: boom"


def test_sync_mode_finishes_the_run_inside_the_post_request() -> None:
    issue = (DEMO_DIR / "issues" / "shopping-cart.md").read_text(encoding="utf-8")
    # public-demo + sync: the serverless (Vercel) configuration
    with _client(api_keys=(), sync_runs=True) as client:
        cfg = client.get("/api/config").json()
        assert cfg["sync_runs"] is True
        assert cfg["access_mode"] == "public-demo"
        assert {"buggy-calculator", "shopping-cart"} <= {d["name"] for d in cfg["demos"]}

        resp = client.post("/api/runs", json={"repo": "demo:shopping-cart", "issue": issue})
        assert resp.status_code == 200, resp.text
        run = resp.json()
        assert run["status"] == "completed"
        assert run["tests_passed"] is True
        assert run["changed_files"] == ["shopcart/models.py", "shopcart/pricing.py"]
        assert run["steps"][0]["tool"] == "list_files"
        assert run["steps"][-1]["tool"] == "finish"
        assert len(run["steps"]) == run["step_count"]
        assert "Tests: **passing**" in run["pr_summary"]
        # still retrievable afterwards on the same instance
        assert client.get(f"/api/runs/{run['id']}").json()["status"] == "completed"


def test_async_mode_returns_queued_run_without_steps() -> None:
    gate = threading.Event()

    def slow_task(repo: Path, issue: str, settings: Settings, on_step: StepCallback) -> AgentResult:
        gate.wait(5)
        raise RuntimeError("stop")

    settings = ApiSettings(demo_dir=DEMO_DIR, api_keys=(KEY,))
    with TestClient(create_app(settings, agent_settings=AGENT, task_fn=slow_task)) as client:
        resp = client.post(
            "/api/runs", json={"repo": "demo:buggy-calculator", "issue": "x"}, headers=_auth()
        )
        gate.set()
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] in {"queued", "running"}
        assert body["steps"] == []
        assert client.get("/api/config").json()["sync_runs"] is False


def test_sync_mode_is_auto_enabled_on_serverless(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("VERCEL", "AWS_LAMBDA_FUNCTION_NAME", "DEVPILOT_SYNC_RUNS"):
        monkeypatch.delenv(name, raising=False)
    assert ApiSettings.from_env().sync_runs is False
    monkeypatch.setenv("VERCEL", "1")
    assert ApiSettings.from_env().sync_runs is True
    monkeypatch.setenv("DEVPILOT_SYNC_RUNS", "false")
    assert ApiSettings.from_env().sync_runs is False


def test_serverless_entrypoint_exposes_public_demo_app(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.util

    # setenv-then-delenv makes monkeypatch remove whatever the entrypoint sets on teardown
    for name in (
        "DEVPILOT_API_KEYS",
        "DEVPILOT_DEV_MODE",
        "DEVPILOT_DEMO_DIR",
        "DEVPILOT_SYNC_RUNS",
        "DEVPILOT_MAX_STEPS_CAP",
        "DEVPILOT_COMMAND_TIMEOUT",
    ):
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)
    monkeypatch.setenv("VERCEL", "1")
    spec = importlib.util.spec_from_file_location("vercel_entry", ROOT / "api" / "index.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with TestClient(module.app) as client:
        cfg = client.get("/api/config").json()
        assert cfg["access_mode"] == "public-demo"
        assert cfg["sync_runs"] is True
        assert cfg["providers"] == ["mock"]
        assert len(cfg["demos"]) >= 2


def test_forwarded_ip_uses_the_hop_added_by_the_trusted_proxy() -> None:
    with _client(api_keys=(), trust_proxy=True, rate_limit_per_minute=2) as client:
        spoofed = [{"X-Forwarded-For": f"10.0.0.{i}, 203.0.113.7"} for i in range(3)]
        codes = [client.get("/api/runs", headers=h).status_code for h in spoofed]
        # rotating the forged left-most entry does not dodge the per-IP limit
        assert codes == [200, 200, 429]
        other = client.get("/api/runs", headers={"X-Forwarded-For": "198.51.100.9"})
        assert other.status_code == 200
