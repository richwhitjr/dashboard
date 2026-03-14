"""Demo mode middleware — intercepts live API calls and returns mock fixtures."""

import json
import logging
import os
from pathlib import Path

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

log = logging.getLogger("demo")

DEMO_MODE = os.environ.get("DEMO_MODE", "").strip() in ("1", "true", "yes")

# Fixtures directory: repo_root/demo/fixtures/
FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "demo" / "fixtures"


def is_demo_mode() -> bool:
    return DEMO_MODE


# Routes that make real external API calls and need mocking.
# Maps (method, path_prefix) → fixture filename (str) or inline response (dict).
_MOCK_ROUTES: list[tuple[str, str, str | dict]] = [
    # Auth — prevent real OAuth flows and return demo status
    ("GET", "/api/auth/status", "auth_status.json"),
    ("GET", "/api/auth/secrets", "auth_secrets.json"),
    ("GET", "/api/auth/google/scopes", {"required": [], "current": [], "needs_reauth": False}),
    ("POST", "/api/auth/google", {"status": "demo_mode"}),
    ("POST", "/api/auth/google/revoke", {"status": "demo_mode"}),
    ("POST", "/api/auth/microsoft", {"status": "demo_mode"}),
    ("POST", "/api/auth/microsoft/revoke", {"status": "demo_mode"}),
    ("POST", "/api/auth/granola/connect", {"status": "demo_mode"}),
    ("POST", "/api/auth/test/", {"configured": True, "connected": True, "error": None, "detail": "Demo mode"}),
    # Gmail — live API endpoints
    ("GET", "/api/gmail/search", "gmail_search.json"),
    ("GET", "/api/gmail/thread/", "gmail_thread.json"),
    ("GET", "/api/gmail/drafts", {"drafts": []}),
    ("POST", "/api/gmail/send", {"status": "demo_mode", "message": "Email sending disabled in demo"}),
    ("POST", "/api/gmail/drafts", {"status": "demo_mode"}),
    ("POST", "/api/gmail/archive", {"results": []}),
    ("POST", "/api/gmail/trash", {"results": []}),
    # Calendar — live API endpoints
    ("GET", "/api/calendar/search", "calendar_search.json"),
    ("POST", "/api/calendar/events", {"status": "demo_mode"}),
    ("PATCH", "/api/calendar/events/", {"status": "demo_mode"}),
    ("DELETE", "/api/calendar/events/", {"status": "demo_mode"}),
    ("POST", "/api/calendar/events/", {"status": "demo_mode"}),
    # Slack — live API endpoints
    ("GET", "/api/slack/search", "slack_search.json"),
    ("GET", "/api/slack/channels", "slack_channels.json"),
    ("POST", "/api/slack/send", {"status": "demo_mode"}),
    ("PATCH", "/api/slack/message", {"status": "demo_mode"}),
    ("DELETE", "/api/slack/message", {"status": "demo_mode"}),
    ("POST", "/api/slack/react", {"status": "demo_mode"}),
    # Notion — live API endpoints
    ("GET", "/api/notion/search", "notion_search.json"),
    ("GET", "/api/notion/pages/", "notion_page_content.json"),
    ("POST", "/api/notion/pages", {"status": "demo_mode"}),
    ("PATCH", "/api/notion/pages/", {"status": "demo_mode"}),
    ("DELETE", "/api/notion/pages/", {"status": "demo_mode"}),
    ("POST", "/api/notion/pages/", {"status": "demo_mode"}),
    # GitHub — live API endpoints
    ("GET", "/api/github/pulls", "github_prs.json"),
    ("GET", "/api/github/issues", {"issues": []}),
    ("GET", "/api/github/search", {"results": []}),
    # Drive — live API endpoints
    ("GET", "/api/drive/search", "drive_search.json"),
    ("POST", "/api/drive/docs", {"status": "demo_mode"}),
    ("POST", "/api/drive/docs/", {"status": "demo_mode"}),
    # Sheets — live API endpoints
    ("POST", "/api/sheets/", {"status": "demo_mode"}),
    ("PATCH", "/api/sheets/", {"status": "demo_mode"}),
    # Weather — intercepted here for the HTTP endpoint
    ("GET", "/api/weather", "weather.json"),
    # AI Priorities — prevent Gemini calls on refresh
    ("GET", "/api/priorities", "priorities.json"),
    # Issue discovery — AI-powered
    ("POST", "/api/issues/discover", {"status": "demo_mode", "message": "Issue discovery disabled in demo"}),
    ("GET", "/api/issues/discover/status", {"status": "idle"}),
    ("GET", "/api/issues/discover/proposals", {"proposals": []}),
    # Sync — prevent real sync
    ("POST", "/api/sync", {"status": "demo_mode", "message": "Sync disabled in demo mode"}),
    # Restart — prevent restart
    ("POST", "/api/restart", {"status": "demo_mode"}),
]


class DemoMiddleware(BaseHTTPMiddleware):
    """Intercept live API endpoints in demo mode and return fixture data."""

    async def dispatch(self, request: Request, call_next):
        method = request.method
        path = request.url.path

        for route_method, route_path, response in _MOCK_ROUTES:
            if method == route_method and path.startswith(route_path):
                if isinstance(response, dict):
                    return JSONResponse(response)
                # It's a fixture filename
                fixture_path = FIXTURES_DIR / response
                if fixture_path.exists():
                    data = json.loads(fixture_path.read_text())
                    return JSONResponse(data)
                log.warning("Demo fixture not found: %s", fixture_path)
                return JSONResponse({"error": "fixture not found", "fixture": response}, status_code=500)

        return await call_next(request)
