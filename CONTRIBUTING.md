# Contributing to DevPilot

Thanks for your interest in improving DevPilot. Bug reports, documentation fixes and pull
requests are all welcome.

## Development setup

Requirements: Python 3.11 or 3.12, `git`. Docker is optional (only for the container checks).

```bash
git clone https://github.com/bharatkumar00797/devpilot-ai-swe-agent.git
cd devpilot-ai-swe-agent
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Everything runs offline with the default `mock` provider, so no API key is needed for
development or tests. To try a real model, copy `.env.example` to `.env` and set the
`DEVPILOT_PROVIDER` / `DEVPILOT_BASE_URL` / `DEVPILOT_API_KEY` / `DEVPILOT_MODEL` variables.
Never commit `.env` or any key.

## Checks

Run these before opening a pull request; CI runs the same commands on Python 3.11 and 3.12.

```bash
ruff check .            # lint
ruff format .           # format (CI uses: ruff format --check .)
mypy                    # strict type checking of src/devpilot
pytest                  # full test suite, offline
```

Optional end-to-end checks:

```bash
devpilot run --repo examples/shopping-cart --issue-file examples/issues/shopping-cart.md
devpilot serve --dev                                 # dashboard on http://127.0.0.1:8000
python scripts/smoke_test.py http://127.0.0.1:8000   # health + every demo through the API
docker compose up --build                            # hardened container
```

## Guidelines

- Keep the mock provider the default: every feature must work without network access or keys.
- New code is fully typed (`mypy --strict` must pass) and comes with tests.
- Tools must never raise into the agent loop; return an error `ToolResult` instead.
- Anything that touches the sandbox, the command allowlist, auth or rate limiting needs a test
  that proves the guard holds (see `tests/test_runner.py`, `tests/test_workspace.py`,
  `tests/test_api.py`).
- Adding a demo: put the repository under `examples/<name>/` with a failing test suite and the
  issue text in `examples/issues/<name>.md`; `tests/test_demos.py` and the smoke test pick it up.

## Commit style

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(api): add per-key run ownership
fix(sandbox): reject symlinks that escape the workspace
docs: explain serverless sync mode
test: cover trace polling cursor
ci: build and smoke-test the Docker image
chore: bump version to 1.0.0
```

Keep commits small and focused, write the subject in the imperative mood, and explain the
"why" in the body when it is not obvious. Update `CHANGELOG.md` under **Unreleased** for
user-visible changes.

## Reporting security issues

Please do not open public issues for vulnerabilities; see [SECURITY.md](SECURITY.md).
