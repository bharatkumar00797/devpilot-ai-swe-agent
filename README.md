# DevPilot — Autonomous AI Software Engineering Agent

> Give it an issue and a repository. DevPilot plans, explores the code, writes a patch,
> runs the tests in a sandbox, iterates on failures and hands back a reviewable diff
> with a PR summary.

**Status:** early development (v0.1). See the roadmap below.

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
- CLI, REST API (FastAPI) and a small web dashboard

## Quick start

_Coming soon._

## Architecture

_Coming soon._

## Security model

_Coming soon._

## License

MIT
