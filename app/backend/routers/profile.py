"""User profile and setup status API."""

import os
import shutil

from fastapi import APIRouter
from pydantic import BaseModel

from app_config import (
    get_profile,
    get_secret,
    invalidate_cache,
    is_setup_complete,
    save_config,
    update_profile,
)
from config import DATA_DIR, DATABASE_PATH

router = APIRouter(prefix="/api/profile", tags=["profile"])


class ProfileUpdate(BaseModel):
    user_name: str | None = None
    user_title: str | None = None
    user_company: str | None = None
    user_company_description: str | None = None
    user_email: str | None = None
    user_email_domain: str | None = None
    github_repo: str | None = None
    skip_domains: list[str] | None = None
    news_topics: list[str] | None = None


@router.get("")
def get_user_profile():
    """Return the full user profile."""
    return get_profile()


@router.patch("")
def update_user_profile(body: ProfileUpdate):
    """Update profile fields (partial update)."""
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    return update_profile(updates)


@router.get("/setup-status")
def setup_status():
    """Return setup status for first-run detection."""
    profile = get_profile()
    has_profile = bool(profile.get("user_name"))

    # Count connected services by checking which secrets are configured
    from app_config import ALLOWED_SECRET_KEYS

    connected = sum(1 for key in ALLOWED_SECRET_KEYS if get_secret(key))
    # Also check Google OAuth
    from config import GCLOUD_CREDENTIALS_PATH
    from routers.auth import TOKEN_PATH

    if TOKEN_PATH.exists() or GCLOUD_CREDENTIALS_PATH.exists():
        connected += 1

    return {
        "setup_complete": is_setup_complete(),
        "has_profile": has_profile,
        "connected_services": connected,
        "data_dir": str(DATA_DIR),
        "database_path": str(DATABASE_PATH),
    }


@router.post("/complete-setup")
def complete_setup():
    """Mark initial setup as complete."""
    save_config({"setup_complete": True})
    return {"status": "ok"}


@router.post("/reset")
def reset_all_data():
    """Delete all user data and return to fresh state."""
    # 1. Delete database files
    for suffix in ("", "-wal", "-shm"):
        db_file = DATA_DIR / f"dashboard.db{suffix}"
        if db_file.exists():
            db_file.unlink()

    # 2. Delete config
    config_file = DATA_DIR / "config.json"
    if config_file.exists():
        config_file.unlink()

    # 3. Delete subdirectories (sessions, avatars)
    for subdir in ("claude_sessions", "personas"):
        path = DATA_DIR / subdir
        if path.exists():
            shutil.rmtree(path)

    # 4. Delete Google OAuth token
    from routers.auth import TOKEN_PATH

    if TOKEN_PATH.exists():
        TOKEN_PATH.unlink()

    # 5. Clear in-memory caches
    invalidate_cache()
    try:
        import connectors.google_auth

        connectors.google_auth._cached_creds = None
    except Exception:
        pass

    # 6. Clear secret env vars
    for key in ("SLACK_TOKEN", "NOTION_TOKEN", "GEMINI_API_KEY", "RAMP_CLIENT_ID", "RAMP_CLIENT_SECRET"):
        os.environ.pop(key, None)

    # 7. Re-initialize fresh database
    from connectors.registry import init_registry
    from database import init_db
    from utils.employee_matching import rebuild_from_db

    init_db()
    init_registry()
    rebuild_from_db()

    return {"status": "ok"}
