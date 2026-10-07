# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-10-07

First stable release.

### Added

- Plan → act → observe agent loop with a tolerant JSON action parser, invalid-reply recovery
  and step limits.
- LLM providers: deterministic offline `mock` policy (default) and an OpenAI-compatible client
  (OpenAI, Groq, OpenRouter, Ollama, vLLM) with retries and exponential backoff.
- Tool registry with validated arguments: list, read, search, replace, write, run tests and
  run allowlisted commands.
- Sandbox: copy-on-run workspace, path and symlink guards, protected files, allowlisted
  commands without a shell, timeouts, scrubbed environment, CPU and file-size limits,
  best-effort network isolation with `unshare -rn`.
- Iterate on failure: after each edit tests are re-run and the agent continues while red.
- Outputs: unified diff, changed files, test outcome, token usage, step trace and a Markdown
  PR summary (`patch.diff`, `PR_SUMMARY.md`, `run.json`).
- `devpilot run` CLI and `devpilot serve` REST API (FastAPI) with background runs, trace
  polling, OpenAPI docs and `/healthz`.
- Access modes `api-key`, `dev` and `public-demo`; constant-time API-key checks, per-key run
  ownership, sliding-window rate limits, bounded queue, repository allowlist, 64 KB body cap,
  strict security headers and CSP, opt-in CORS, right-most `X-Forwarded-For` hop behind a
  trusted proxy.
- Static web dashboard: demo picker, live trace, colored diff, PR summary, run history and
  `#run=<id>&tab=<name>` deep links.
- Serverless sync mode (auto-enabled on Vercel / AWS Lambda): runs finish inside
  `POST /api/runs` and the response carries the full trace.
- Demo repositories `buggy-calculator` and `shopping-cart` with issue texts.
- Deployment: multi-stage non-root Dockerfile with health check, hardened docker compose,
  `render.yaml`, `fly.toml`, `railway.json`, `vercel.json` + `api/index.py`.
- `scripts/smoke_test.py` and a CI job that builds the image and smoke-tests every demo.
- Documentation: README with architecture and sequence diagrams, security model, deploy guides
  and configuration reference; dashboard screenshots; CONTRIBUTING and SECURITY policies.

[Unreleased]: https://github.com/bharatkumar00797/devpilot-ai-swe-agent/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/bharatkumar00797/devpilot-ai-swe-agent/releases/tag/v1.0.0
