"""HTTP service (FastAPI) and web dashboard for DevPilot."""

from devpilot.api.app import create_app
from devpilot.api.settings import ApiSettings

__all__ = ["ApiSettings", "create_app"]
