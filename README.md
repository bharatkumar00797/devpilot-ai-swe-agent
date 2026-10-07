# DevPilot — Autonomous AI Software Engineering Agent

> Give it an issue and a repository. DevPilot plans, explores the code, writes a patch,
> runs the tests in a sandbox, iterates on failures and hands back a reviewable diff
> with a PR summary.

**Status:** early development (v0.1).

## Why

Most "AI coding" tools stop at suggesting snippets. DevPilot treats a change the way an
engineer does: understand the issue, find the relevant code, make a minimal edit, and prove it
with tests — all inside an isolated workspace so the agent can never touch your real checkout,
your secrets, or the network.

## Planned features

- Agent loop (plan → act → observe) driven by any LLM
- Pluggable LLM providers: offline deterministic `mock` (default) and any OpenAI-compatible API
  (OpenAI, Groq, OpenRouter, Ollama, vLLM)
- Tool layer: list / read / search / edit files, run tests
- Sandbox guardrails: copy-on-run workspace, path-escape protection, command allowlist,
  timeouts, scrubbed environment, optional network isolation
- Unified diff + Markdown PR summary as output
- CLI, REST API (FastAPI) with background runs, and a live web dashboard

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Runs fully offline with the deterministic mock provider
devpilot run --repo examples/buggy-calculator \
  --issue-file examples/issues/buggy-calculator.md --out runs/demo

cat runs/demo/PR_SUMMARY.md   # PR description + diff
```

To use a real model, copy `.env.example` to `.env` and set `DEVPILOT_PROVIDER=openai`
plus `DEVPILOT_BASE_URL` / `DEVPILOT_API_KEY` / `DEVPILOT_MODEL` (works with OpenAI, Groq,
OpenRouter or a local Ollama server).

## REST API and dashboard

```bash
devpilot serve --dev            # http://127.0.0.1:8000 — dashboard, no auth (localhost only)
DEVPILOT_API_KEYS=change-me devpilot serve --host 0.0.0.0   # API-key protected
```

Open `http://127.0.0.1:8000/` for the dashboard (pick a demo repo, describe the issue, watch the
live step trace, then review the colored diff and PR summary). Interactive API docs live at `/docs`.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/runs` | start a run in the background → `202` with the run id |
| `GET` | `/api/runs` | your recent runs |
| `GET` | `/api/runs/{id}` | status, summary, diff, changed files, `tests_passed`, PR summary |
| `GET` | `/api/runs/{id}/trace?since=N` | step trace; poll with the returned `next_cursor` |
| `GET` | `/api/config` | public UI config (demos, limits, access mode) |
| `GET` | `/healthz` | liveness probe |

```bash
curl -s -X POST localhost:8000/api/runs -H "X-API-Key: change-me" \
  -H "Content-Type: application/json" \
  -d '{"repo": "demo:buggy-calculator", "issue": "`return a - b` should be `return a + b`"}'
```

`repo` is either `demo:<name>` (bundled examples) or an absolute path inside
`DEVPILOT_REPO_ALLOWLIST`. Without API keys (and without dev mode) the server is a safe public
demo: bundled repos and the offline mock provider only. Keys are compared in constant time,
requests are rate limited per key/IP, runs are visible only to the key that created them, and
provider credentials never appear in any response. See `.env.example` for every setting.

## Architecture

```
src/devpilot/
  agent/     plan -> act -> observe loop, JSON action parser, prompts, result models
  llm/       provider interface, offline mock provider, OpenAI-compatible client
  tools/     tool registry (validated args) + built-in workspace tools
  sandbox/   isolated workspace copy, path guard, allowlisted command runner
  api/       FastAPI app, background run manager, auth + rate limiting, repo allowlist,
             static dashboard (plain HTML/CSS/JS)
  report.py  PR-style Markdown summary
  service.py wires everything together for the CLI / API
  cli.py     `devpilot run ...` and `devpilot serve`
```

_Full diagram and walkthrough coming soon._

## Security model

_Coming soon._

## License

MIT
