import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# Fix macOS Python SSL certificate issue — point OpenSSL at certifi's CA bundle
# so urllib, httpx, slack_sdk, etc. can all verify HTTPS certificates.
if not os.environ.get("SSL_CERT_FILE"):
    try:
        import certifi

        os.environ["SSL_CERT_FILE"] = certifi.where()
    except ImportError:
        pass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from database import init_db
from routers import (
    auth,
    calendar_api,
    claude,
    claude_sessions,
    dashboard,
    employees,
    github_api,
    gmail,
    issues,
    meetings,
    news,
    notes,
    notion_api,
    priorities,
    projects_api,
    ramp_api,
    search,
    slack_api,
    sync,
)
from routers.sync import sync_granola, sync_meeting_files
from utils.employee_matching import rebuild_from_db

app = FastAPI(title="Rich's Dashboard")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes (must be registered before the SPA catch-all)
app.include_router(employees.router)
app.include_router(notes.router)
app.include_router(dashboard.router)
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
app.include_router(search.router)
app.include_router(meetings.router)
app.include_router(issues.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/open-url")
def open_url(body: dict):
    """Open a URL in the system default browser (used by pywebview native app)."""
    import webbrowser

    url = body.get("url", "")
    if url and (url.startswith("http://") or url.startswith("https://")):
        webbrowser.open(url)
        return {"status": "ok"}
    return {"status": "invalid_url"}


@app.post("/api/restart")
def restart():
    """Rebuild frontend dist, then restart the server process."""
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
    """Run database migrations and sync data on startup."""
    # Run migrations first to ensure schema is up to date
    init_db()
    # Rebuild employee matching cache from database
    rebuild_from_db()
    # Sync markdown meeting files and Granola notes
    sync_meeting_files()
    sync_granola()


# Serve built frontend — must be last so it doesn't shadow API routes
DIST_DIR = Path(__file__).parent.parent / "frontend" / "dist"
if DIST_DIR.exists():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

    @app.get("/{path:path}")
    def serve_spa(path: str):
        if path.startswith("api/"):
            from fastapi.responses import JSONResponse

            return JSONResponse({"error": "not found"}, status_code=404)
        file = DIST_DIR / path
        if file.is_file():
            return FileResponse(file)
        return FileResponse(DIST_DIR / "index.html")
