"""Serverless entrypoint (Vercel): exposes the DevPilot FastAPI app as ``app``.

Serverless functions freeze or discard background threads once a response is sent,
so runs execute synchronously inside ``POST /api/runs`` (``DEVPILOT_SYNC_RUNS`` is
switched on automatically when ``VERCEL`` is set). Unless API keys are configured
the deployment is a public demo: bundled demo repositories and the offline mock
provider only. Temporary workspaces are created under ``/tmp``, the only writable
location on the platform.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if SRC.is_dir() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

os.environ.setdefault("DEVPILOT_DEMO_DIR", str(ROOT / "examples"))
os.environ.setdefault("DEVPILOT_SYNC_RUNS", "true")
os.environ.setdefault("DEVPILOT_MAX_STEPS_CAP", "20")
os.environ.setdefault("DEVPILOT_COMMAND_TIMEOUT", "30")

from devpilot.api import create_app  # noqa: E402  (path setup must run first)

app = create_app()
