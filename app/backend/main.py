import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv

from config import get_backend_root, is_bundled

log = logging.getLogger("startup")

load_dotenv(get_backend_root() / ".env")

# Fix macOS Python SSL certificate issue — point OpenSSL at certifi's CA bundle
# so urllib, httpx, slack_sdk, etc. can all verify HTTPS certificates.
if not os.environ.get("SSL_CERT_FILE"):
    try:
        import certifi

        os.environ["SSL_CERT_FILE"] = certifi.where()
        log.info("SSL_CERT_FILE set to %s", certifi.where())
    except ImportError:
        log.warning("certifi not available — SSL may fail")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from connectors.registry import init_registry
from database import init_db
from routers import (
    agent_chat,
    auth,
    briefing,
    calendar_api,
    changes,
    claude,
    claude_sessions,
    dashboard,
    drive_api,
    github_api,
    gmail,
    issue_discovery,
    issues,
    longform,
    meetings,
    memory,
    news,
    notes,
    notion_api,
    people,
    personas,
    priorities,
    profile,
    projects_api,
    ramp_api,
    search,
    sheets_api,
    slack_api,
    status_context,
    sync,
    weather,
    whatsapp,
)
from routers.sync import sync_granola, sync_meeting_files
from utils.person_matching import rebuild_from_db

app = FastAPI(title="Personal Dashboard")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://localhost:3000"],
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        # Derive WebSocket origin from the request so it works on any port
        host = request.headers.get("host", "localhost:8000")
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "img-src 'self' data:; "
            f"connect-src 'self' ws://{host}; "
            "font-src 'self' https://cdn.jsdelivr.net; "
            "frame-src 'none'; "
            "object-src 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response


app.add_middleware(SecurityHeadersMiddleware)

# Demo mode: intercept live API calls with fixture data
from demo_middleware import is_demo_mode

if is_demo_mode():
    from demo_middleware import DemoMiddleware

    app.add_middleware(DemoMiddleware)
    log.info("[demo] Demo mode enabled — live API calls will return fixture data")

# API routes (must be registered before the SPA catch-all)
app.include_router(dashboard.router)
app.include_router(people.router)
app.include_router(notes.router)
app.include_router(sync.router)
app.include_router(auth.router)
app.include_router(news.router)
app.include_router(priorities.router)
app.include_router(claude.router)
app.include_router(claude_sessions.router)
app.include_router(gmail.router)
app.include_router(calendar_api.router)
app.include_router(slack_api.router)
app.include_router(notion_api.router)
app.include_router(github_api.router)
app.include_router(ramp_api.router)
app.include_router(projects_api.router)
app.include_router(drive_api.router)
app.include_router(sheets_api.router)
app.include_router(search.router)
app.include_router(meetings.router)
app.include_router(issues.router)
app.include_router(issue_discovery.router)
app.include_router(longform.router)
app.include_router(profile.router)
app.include_router(personas.router)
app.include_router(briefing.router)
app.include_router(weather.router)
app.include_router(status_context.router)
app.include_router(memory.router)
app.include_router(whatsapp.router)
app.include_router(agent_chat.router)
app.include_router(changes.router)

# GraphQL knowledge graph API
from graphql_api import graphql_app

app.include_router(graphql_app, prefix="/graphql")


@app.get("/api/health")
def health():
    return {"status": "ok"}


_frontend_log = logging.getLogger("frontend")


@app.post("/api/frontend-errors")
def frontend_errors(body: dict):
    """Receive error reports from the frontend so they appear in backend logs."""
    errors = body.get("errors", [])
    for err in errors[:20]:  # cap at 20 per request
        source = err.get("source", "unknown")
        message = err.get("message", "")
        detail = err.get("detail", "")
        _frontend_log.error("[%s] %s%s", source, message, f" | {detail}" if detail else "")
    return {"status": "ok", "received": len(errors)}


@app.post("/api/open-url")
def open_url(body: dict):
    """Open a URL in the system default browser (used by pywebview native app)."""
    import webbrowser
    from urllib.parse import urlparse

    url = body.get("url", "")
    if url:
        parsed = urlparse(url)
        if parsed.scheme in ("http", "https") and parsed.netloc:
            webbrowser.open(url)
            return {"status": "ok"}
    return {"status": "invalid_url"}


@app.post("/api/restart")
def restart():
    """Rebuild frontend dist, then restart the server process."""
    if is_bundled():
        return {"status": "not_supported", "message": "Restart not available in bundled app"}

    import os
    import signal
    import subprocess
    import threading

    def _rebuild_and_restart():
        # Rebuild frontend so dist/ picks up any changes
        frontend_dir = Path(__file__).parent.parent / "frontend"
        subprocess.run(["npm", "run", "build"], cwd=frontend_dir, capture_output=True)
        os.kill(os.getpid(), signal.SIGTERM)

    # Run in background so the HTTP response goes out first
    threading.Timer(0.5, _rebuild_and_restart).start()
    return {"status": "restarting"}


@app.on_event("startup")
def startup():
    """Run database migrations, register connectors, and sync data on startup."""
    t_total = time.time()

    def _step(name, fn):
        log.info("[startup] %s ...", name)
        sys.stdout.flush()
        sys.stderr.flush()
        t0 = time.time()
        try:
            fn()
            log.info("[startup] %s OK (%.2fs)", name, time.time() - t0)
        except BaseException as e:
            log.error("[startup] %s FAILED after %.2fs: %s: %s", name, time.time() - t0, type(e).__name__, e)
            import traceback

            log.error("".join(traceback.format_exc()))
            sys.stdout.flush()
            sys.stderr.flush()
            raise

    def _migrate_google_token():
        """Move .google_token.json from backend dir to DATA_DIR if needed."""
        from config import DATA_DIR

        old_path = Path(__file__).parent / ".google_token.json"
        new_path = DATA_DIR / ".google_token.json"
        if old_path.exists() and not new_path.exists():
            import shutil

            shutil.move(str(old_path), str(new_path))
            log.info("Migrated Google token from %s to %s", old_path, new_path)

    _step("init_db (migrations)", init_db)
    _step("migrate_google_token", _migrate_google_token)
    _step("init_registry (connectors)", init_registry)
    _step("rebuild_from_db (person matching cache)", rebuild_from_db)
    _step("sync_meeting_files", sync_meeting_files)

    if not is_demo_mode():
        from connectors.registry import is_enabled

        if is_enabled("granola"):
            _step("sync_granola", sync_granola)

        from routers.sync import start_auto_sync

        _step("start_auto_sync", start_auto_sync)
    else:
        log.info("[startup] Demo mode — skipping sync and auto-sync")
    log.info("[startup] All startup steps completed in %.2fs", time.time() - t_total)


@app.on_event("shutdown")
def shutdown():
    from routers.sync import stop_auto_sync

    stop_auto_sync()


# Serve built frontend — must be last so it doesn't shadow API routes
import sys

if is_bundled():
    DIST_DIR = Path(sys._MEIPASS) / "frontend" / "dist"
else:
    DIST_DIR = Path(__file__).parent.parent / "frontend" / "dist"

log.info("[frontend] DIST_DIR=%s exists=%s", DIST_DIR, DIST_DIR.exists())
if DIST_DIR.exists():
    assets_dir = DIST_DIR / "assets"
    index_file = DIST_DIR / "index.html"
    log.info("[frontend] assets/ exists=%s, index.html exists=%s", assets_dir.exists(), index_file.exists())
    if assets_dir.exists():
        try:
            asset_files = list(assets_dir.iterdir())
            log.info("[frontend] %d asset files: %s", len(asset_files), [f.name for f in asset_files[:10]])
        except Exception as e:
            log.warning("[frontend] Could not list assets: %s", e)

    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

    @app.get("/{path:path}")
    def serve_spa(path: str):
        if path.startswith("api/"):
            from fastapi.responses import JSONResponse

            return JSONResponse({"error": "not found"}, status_code=404)
        file = (DIST_DIR / path).resolve()
        dist_resolved = DIST_DIR.resolve()
        if file.is_file() and str(file).startswith(str(dist_resolved)):
            return FileResponse(file)
        return FileResponse(DIST_DIR / "index.html")
else:
    log.error("[frontend] DIST_DIR does not exist — app will show blank page!")
