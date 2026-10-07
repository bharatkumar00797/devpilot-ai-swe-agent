# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.12

# ---------------------------------------------------------------- build stage
# Build wheels for the package and all of its dependencies, so the runtime image
# installs offline and carries no compilers, caches or source tree.
FROM python:${PYTHON_VERSION}-slim AS build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip wheel --wheel-dir /wheels .

# -------------------------------------------------------------- runtime stage
FROM python:${PYTHON_VERSION}-slim AS runtime

LABEL org.opencontainers.image.title="DevPilot" \
      org.opencontainers.image.description="Autonomous AI software engineering agent: issue in, tested patch out" \
      org.opencontainers.image.source="https://github.com/bharatkumar00797/devpilot-ai-swe-agent" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TMPDIR=/tmp \
    PORT=8000 \
    DEVPILOT_DEMO_DIR=/app/examples \
    DEVPILOT_PROVIDER=mock

RUN groupadd --system --gid 10001 devpilot \
 && useradd --system --uid 10001 --gid devpilot --home-dir /app --shell /usr/sbin/nologin devpilot

COPY --from=build /wheels /wheels
RUN pip install --no-index --find-links=/wheels devpilot-ai \
 && rm -rf /wheels

WORKDIR /app
# Demo repositories stay root-owned and read-only; every run works on a copy in /tmp.
COPY examples ./examples

USER devpilot
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import os, urllib.request as u; u.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT', '8000'), timeout=4)"]

# Shell form only to expand $PORT (Render, Railway, Fly and Cloud Run inject it).
CMD ["sh", "-c", "exec devpilot serve --host 0.0.0.0 --port \"${PORT:-8000}\""]
