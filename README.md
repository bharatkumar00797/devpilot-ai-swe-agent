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
- CLI, REST API (FastAPI) and a small web dashboard

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

## Architecture

```
src/devpilot/
  agent/     plan -> act -> observe loop, JSON action parser, prompts, result models
  llm/       provider interface, offline mock provider, OpenAI-compatible client
  tools/     tool registry (validated args) + built-in workspace tools
  sandbox/   isolated workspace copy, path guard, allowlisted command runner
  report.py  PR-style Markdown summary
  service.py wires everything together for the CLI / API
  cli.py     `devpilot run ...`
```

_Full diagram and walkthrough coming soon._

## Security model

_Coming soon._

## License

MIT
