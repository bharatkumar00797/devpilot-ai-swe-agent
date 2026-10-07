# Security Policy

DevPilot is an autonomous agent that edits code and runs test suites, so we take isolation
and API security seriously. The design is described in the
[security model](README.md#security-model) section of the README.

## Supported versions

| Version | Supported |
| --- | --- |
| 1.0.x | yes |
| < 1.0 | no |

## Reporting a vulnerability

Please **do not open a public issue** for security problems.

- Use GitHub's private vulnerability reporting:
  **Security → Report a vulnerability** on
  <https://github.com/bharatkumar00797/devpilot-ai-swe-agent/security>.
- Include the affected version or commit, a description of the impact, and steps or a proof of
  concept to reproduce it.

You can expect an acknowledgement within 3 working days and a status update within 10 working
days. Once a fix is released we are happy to credit you in the changelog unless you prefer to
stay anonymous.

## Scope

In scope:

- Escaping the run workspace: reading or writing files outside it, following symlinks out,
  writing protected files (`.git`, `.env`, keys).
- Bypassing the command allowlist, injecting shell syntax, or leaking server environment
  variables (for example provider API keys) into sandboxed commands.
- Authentication or authorization bypass in the REST API: accessing runs owned by another key,
  using non-demo repositories or real providers in public-demo mode.
- Bypassing rate limits, the request body cap or the run queue bounds.
- Cross-site scripting or CSP bypass in the dashboard.
- Secrets exposed in API responses, logs or the published Docker image.

Out of scope:

- Code executed by a repository's own test suite when you deliberately point DevPilot at an
  untrusted repository outside a container. This is a documented residual risk; run such
  workloads in the hardened container.
- Missing network isolation on hosts that block unprivileged user namespaces (documented
  best-effort behaviour).
- Denial of service that requires more traffic than the configured rate limits allow.
- Incorrect patches produced by a real LLM provider; output is a diff for human review.
- Vulnerabilities in third-party platforms (Render, Fly.io, Railway, Vercel) or dependencies
  without a demonstrated impact on DevPilot.
