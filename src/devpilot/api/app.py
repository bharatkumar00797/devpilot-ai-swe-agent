"""FastAPI application: REST endpoints for agent runs plus the static dashboard."""

from __future__ import annotations

import math
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from devpilot import __version__
from devpilot.api.jobs import QueueFull, RunManager, RunRecord, TaskFn, default_task
from devpilot.api.repos import DEMO_PREFIX, RepoNotAllowed, RepoResolver
from devpilot.api.schemas import (
    MAX_ISSUE_CHARS,
    ConfigOut,
    DemoOut,
    HealthOut,
    RunCreate,
    RunCreatedOut,
    RunDetailOut,
    RunListOut,
    RunSummaryOut,
    TraceOut,
)
from devpilot.api.security import ApiKeyAuth, RateLimiter
from devpilot.api.settings import ApiSettings
from devpilot.config import Settings

STATIC_DIR = Path(__file__).parent / "static"
MAX_BODY_BYTES = 64 * 1024
PUBLIC_OWNER = "public"

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    ),
}


@dataclass(frozen=True)
class Caller:
    """Who is calling: ``owner`` scopes run visibility, ``client`` keys rate limits."""

    owner: str
    client: str
    trusted: bool  # authenticated with a key, or the server runs in dev mode


def _client_ip(request: Request, trust_proxy: bool) -> str:
    if trust_proxy:
        # A proxy appends the address it saw, so the right-most entry is the one added
        # by the trusted edge; earlier entries are client-supplied and can be forged.
        forwarded = request.headers.get("x-forwarded-for", "")
        hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
        if hops:
            return hops[-1][:64]
    return request.client.host if request.client else "unknown"


def _presented_key(request: Request) -> str | None:
    key = request.headers.get("x-api-key")
    if key:
        return key.strip()
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return token.strip()
    return None


def _retry_after(seconds: float) -> dict[str, str]:
    return {"Retry-After": str(max(1, math.ceil(seconds)))}


@dataclass(frozen=True)
class AccessGuard:
    """Authenticates a request and applies the general per-caller rate limit."""

    settings: ApiSettings
    auth: ApiKeyAuth
    limiter: RateLimiter

    def __call__(self, request: Request) -> Caller:
        if self.auth.enabled:
            owner = self.auth.verify(_presented_key(request))
            if owner is None:
                raise HTTPException(
                    status.HTTP_401_UNAUTHORIZED,
                    "Missing or invalid API key",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            who = Caller(owner=owner, client=f"key:{owner}", trusted=True)
        else:
            ip = _client_ip(request, self.settings.trust_proxy)
            who = Caller(owner=PUBLIC_OWNER, client=f"ip:{ip}", trusted=self.settings.dev_mode)
        retry = self.limiter.check(who.client)
        if retry is not None:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Rate limit exceeded",
                headers=_retry_after(retry),
            )
        return who


def get_caller(request: Request) -> Caller:
    guard: AccessGuard = request.app.state.guard
    return guard(request)


CallerDep = Annotated[Caller, Depends(get_caller)]


def _summary(record: RunRecord) -> RunSummaryOut:
    result = record.result
    return RunSummaryOut(
        id=record.id,
        status=record.status,
        repo=record.repo_label,
        provider=record.provider,
        title=record.title,
        created_at=record.created_at,
        started_at=record.started_at,
        finished_at=record.finished_at,
        step_count=len(record.steps),
        tests_passed=result.tests_passed if result else None,
    )


def _detail(record: RunRecord) -> RunDetailOut:
    with record.lock:
        base = _summary(record).model_dump()
        result = record.result
        return RunDetailOut(
            **base,
            issue=record.issue,
            max_steps=record.max_steps,
            summary=result.summary if result else "",
            diff=result.diff if result else "",
            changed_files=list(result.changed_files) if result else [],
            pr_summary=record.pr_summary,
            model=result.model if result else "",
            prompt_tokens=result.prompt_tokens if result else 0,
            completion_tokens=result.completion_tokens if result else 0,
            error=record.error,
        )


def create_app(
    settings: ApiSettings | None = None,
    *,
    agent_settings: Settings | None = None,
    task_fn: TaskFn | None = None,
) -> FastAPI:
    """Build the application. Arguments exist mainly so tests can inject config."""
    cfg = settings or ApiSettings.from_env()
    base_agent = agent_settings or Settings.from_env()
    auth = ApiKeyAuth(cfg.api_keys)
    api_limiter = RateLimiter(cfg.rate_limit_per_minute)
    run_limiter = RateLimiter(cfg.run_limit_per_minute)
    resolver = RepoResolver(cfg.demo_dir, cfg.repo_allowlist, allow_paths=not cfg.public_demo)
    manager = RunManager(
        max_workers=cfg.max_concurrent_runs,
        max_active=cfg.max_queued_runs,
        max_kept=cfg.max_runs_kept,
        task_fn=task_fn or default_task,
        inline=cfg.sync_runs,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        manager.shutdown()

    app = FastAPI(
        title="DevPilot API",
        version=__version__,
        description="Autonomous AI software engineering agent: issue in, tested patch out.",
        lifespan=lifespan,
    )
    app.state.guard = AccessGuard(cfg, auth, api_limiter)

    if cfg.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(cfg.cors_origins),
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", "X-API-Key", "Authorization"],
            allow_credentials=False,
            max_age=600,
        )

    @app.middleware("http")
    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        length = request.headers.get("content-length")
        if length and (not length.isdigit() or int(length) > MAX_BODY_BYTES):
            return JSONResponse({"detail": "Request body too large"}, status_code=413)
        response = await call_next(request)
        # Swagger UI (/docs) loads its own assets, so it is left out of the strict CSP.
        is_docs = request.url.path.startswith(("/docs", "/redoc"))
        for name, value in SECURITY_HEADERS.items():
            if not (is_docs and name == "Content-Security-Policy"):
                response.headers.setdefault(name, value)
        return response

    def load(run_id: str, who: Caller) -> RunRecord:
        record = manager.get(run_id, who.owner) if len(run_id) <= 64 else None
        if record is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
        return record

    # ------------------------------------------------------------- public
    @app.get("/healthz", response_model=HealthOut, tags=["meta"])
    def healthz() -> HealthOut:
        return HealthOut(version=__version__, active_runs=manager.active_count())

    @app.get("/api/config", response_model=ConfigOut, tags=["meta"])
    def config() -> ConfigOut:
        default_provider = "mock" if cfg.public_demo else base_agent.provider
        return ConfigOut(
            version=__version__,
            auth_required=cfg.auth_enabled,
            access_mode=cfg.access_mode,
            allow_paths=resolver.allow_paths,
            providers=["mock"] if cfg.public_demo else ["mock", "openai"],
            default_provider=default_provider,
            default_max_steps=min(base_agent.max_steps, cfg.max_steps_cap),
            max_steps_cap=cfg.max_steps_cap,
            max_issue_chars=MAX_ISSUE_CHARS,
            sync_runs=cfg.sync_runs,
            demos=[
                DemoOut(name=d.name, repo=f"{DEMO_PREFIX}{d.name}", issue=d.issue)
                for d in resolver.demos()
            ],
        )

    # --------------------------------------------------------------- runs
    @app.post(
        "/api/runs",
        response_model=RunCreatedOut,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["runs"],
        responses={200: {"model": RunCreatedOut, "description": "Finished run (sync mode)"}},
    )
    def create_run(body: RunCreate, who: CallerDep, response: Response) -> RunCreatedOut:
        if body.max_steps is not None and body.max_steps > cfg.max_steps_cap:
            raise HTTPException(
                422,
                f"max_steps must be <= {cfg.max_steps_cap}",
            )
        provider = body.provider or ("mock" if cfg.public_demo else base_agent.provider)
        if provider != "mock" and not who.trusted:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Only the offline mock provider is enabled here"
            )
        try:
            repo_path = resolver.resolve(body.repo)
        except RepoNotAllowed as exc:
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc

        # Validated requests only count towards the (stricter) run-creation limit.
        retry = run_limiter.check(who.client)
        if retry is not None:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Run limit exceeded",
                headers=_retry_after(retry),
            )
        run_settings = replace(
            base_agent,
            provider=provider,
            max_steps=min(body.max_steps or base_agent.max_steps, cfg.max_steps_cap),
        )
        try:
            record = manager.submit(
                owner=who.owner,
                repo_label=body.repo,
                repo_path=repo_path,
                issue=body.issue,
                settings=run_settings,
            )
        except QueueFull as exc:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, str(exc), headers={"Retry-After": "10"}
            ) from exc
        detail = _detail(record).model_dump()
        if not record.done:
            return RunCreatedOut(**detail)
        response.status_code = status.HTTP_200_OK
        return RunCreatedOut(**detail, steps=record.steps_since(0))

    @app.get("/api/runs", response_model=RunListOut, tags=["runs"])
    def list_runs(who: CallerDep, limit: Annotated[int, Query(ge=1, le=100)] = 20) -> RunListOut:
        return RunListOut(runs=[_summary(r) for r in manager.list(who.owner, limit)])

    @app.get("/api/runs/{run_id}", response_model=RunDetailOut, tags=["runs"])
    def get_run(run_id: str, who: CallerDep) -> RunDetailOut:
        return _detail(load(run_id, who))

    @app.get("/api/runs/{run_id}/trace", response_model=TraceOut, tags=["runs"])
    def get_trace(run_id: str, who: CallerDep, since: Annotated[int, Query(ge=0)] = 0) -> TraceOut:
        record = load(run_id, who)
        with record.lock:
            done, state = record.done, record.status
        steps = record.steps_since(since)
        return TraceOut(
            id=record.id,
            status=state,
            done=done,
            next_cursor=since + len(steps),
            steps=steps,
        )

    # ---------------------------------------------------------- dashboard
    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
