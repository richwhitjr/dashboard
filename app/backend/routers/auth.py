"""Authentication status and management for connected services."""

import logging
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from app_config import ALLOWED_SECRET_KEYS, delete_secret, get_secret, set_secret
from config import GCLOUD_CREDENTIALS_PATH, GRANOLA_CACHE_PATH
from database import get_write_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

TOKEN_PATH = Path(__file__).parent.parent / ".google_token.json"


def _check_google() -> dict:
    """Check Google auth status by validating credentials."""
    result = {"configured": False, "connected": False, "error": None, "detail": None}

    if not GCLOUD_CREDENTIALS_PATH.exists() and not TOKEN_PATH.exists():
        result["detail"] = "No credentials found. Run: gcloud auth application-default login"
        return result

    result["configured"] = True
    try:
        from connectors.google_auth import get_google_credentials

        creds = get_google_credentials()
        if creds and creds.valid:
            result["connected"] = True
            result["detail"] = "Authenticated via OAuth token"
        else:
            result["error"] = "Token exists but is not valid"
    except FileNotFoundError as e:
        result["error"] = str(e)
    except Exception as e:
        logger.exception("Google auth check failed")
        result["error"] = str(e)

    return result


def _check_slack() -> dict:
    """Check Slack auth status by making a test API call."""
    result = {"configured": False, "connected": False, "error": None, "detail": None}
    token = get_secret("SLACK_TOKEN") or ""

    if not token:
        result["detail"] = "SLACK_TOKEN not configured"
        return result

    result["configured"] = True
    try:
        from slack_sdk import WebClient

        client = WebClient(token=token)
        resp = client.auth_test()
        if resp.get("ok"):
            result["connected"] = True
            result["detail"] = f"Authenticated as {resp.get('user', 'unknown')} in {resp.get('team', 'unknown')}"
        else:
            result["error"] = resp.get("error", "Unknown error")
    except ImportError:
        result["error"] = "slack_sdk not installed"
    except Exception as e:
        result["error"] = str(e)

    return result


def _check_notion() -> dict:
    """Check Notion auth status by making a test API call."""
    result = {"configured": False, "connected": False, "error": None, "detail": None}
    token = get_secret("NOTION_TOKEN") or ""

    if not token:
        result["detail"] = "NOTION_TOKEN not configured"
        return result

    result["configured"] = True
    try:
        import httpx

        resp = httpx.get(
            "https://api.notion.com/v1/users/me",
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": "2022-06-28",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("object") == "user":
            name = data.get("name", "Unknown")
            result["connected"] = True
            result["detail"] = f"Authenticated as {name}"
        else:
            result["error"] = "Unexpected response from Notion API"
    except Exception as e:
        result["error"] = str(e)

    return result


def _check_github() -> dict:
    """Check GitHub auth via gh CLI token."""
    import subprocess

    result = {"configured": False, "connected": False, "error": None, "detail": None}
    try:
        proc = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=5)
        if proc.returncode == 0 and proc.stdout.strip():
            result["configured"] = True
            import httpx

            resp = httpx.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {proc.stdout.strip()}",
                    "Accept": "application/vnd.github+json",
                },
                timeout=10,
            )
            if resp.status_code == 200:
                user = resp.json()
                result["connected"] = True
                result["detail"] = f"Authenticated as {user.get('login', 'unknown')}"
            else:
                result["error"] = f"Token invalid (HTTP {resp.status_code})"
        else:
            result["detail"] = "gh CLI not authenticated. Run: gh auth login"
    except FileNotFoundError:
        result["detail"] = "gh CLI not installed. Install: brew install gh"
    except Exception as e:
        result["error"] = str(e)
    return result


def _check_ramp() -> dict:
    """Check Ramp auth status by validating credentials."""
    result = {"configured": False, "connected": False, "error": None, "detail": None}
    client_id = get_secret("RAMP_CLIENT_ID") or ""
    client_secret = get_secret("RAMP_CLIENT_SECRET") or ""

    if not client_id or not client_secret:
        result["detail"] = "RAMP_CLIENT_ID and RAMP_CLIENT_SECRET not configured"
        return result

    result["configured"] = True
    try:
        from connectors.ramp import check_ramp_connection

        check = check_ramp_connection()
        result["connected"] = check["connected"]
        result["error"] = check.get("error")
        result["detail"] = check.get("detail")
    except Exception as e:
        result["error"] = str(e)

    return result


def _check_granola() -> dict:
    """Check if Granola cache file exists (no auth needed)."""
    result = {"configured": False, "connected": False, "error": None, "detail": None}

    if GRANOLA_CACHE_PATH.exists():
        result["configured"] = True
        result["connected"] = True
        result["detail"] = f"Cache file found at {GRANOLA_CACHE_PATH}"
    else:
        result["detail"] = f"Cache file not found at {GRANOLA_CACHE_PATH}"

    return result


def _get_sync_states() -> dict:
    """Fetch last sync state per source from the database."""
    from database import get_db_connection

    with get_db_connection(readonly=True) as db:
        rows = db.execute("SELECT * FROM sync_state").fetchall()
    result = {}
    for row in rows:
        result[row["source"]] = {
            "last_sync_at": row["last_sync_at"],
            "last_sync_status": row["last_sync_status"],
            "last_error": row["last_error"],
            "items_synced": row["items_synced"],
        }
    return result


# Map auth service names to their sync_state source names
_AUTH_TO_SYNC = {
    "google": ["gmail", "calendar"],
    "google_drive": ["drive", "sheets", "docs"],
    "slack": ["slack"],
    "notion": ["notion"],
    "granola": ["granola"],
    "github": ["github"],
    "ramp": ["ramp", "ramp_vendors", "ramp_bills"],
}


# Map secret keys to the sync_state sources they affect
_SECRET_TO_SYNC = {
    "SLACK_TOKEN": ["slack"],
    "NOTION_TOKEN": ["notion"],
    "RAMP_CLIENT_ID": ["ramp", "ramp_vendors", "ramp_bills"],
    "RAMP_CLIENT_SECRET": ["ramp", "ramp_vendors", "ramp_bills"],
}

# Map connector IDs to sync_state sources
_CONNECTOR_TO_SYNC = {
    "google": ["gmail", "calendar"],
    "google_drive": ["drive", "sheets", "docs"],
    "slack": ["slack"],
    "notion": ["notion"],
    "granola": ["granola"],
    "github": ["github"],
    "ramp": ["ramp", "ramp_vendors", "ramp_bills"],
    "news": ["news"],
}


def _clear_sync_errors(sources: list[str]):
    """Reset sync_state error fields for the given sources so stale errors don't persist."""
    if not sources:
        return
    with get_write_db() as db:
        for src in sources:
            db.execute(
                "UPDATE sync_state SET last_sync_status = NULL, last_error = NULL WHERE source = ?",
                (src,),
            )
        db.commit()


@router.get("/status")
def auth_status():
    """Return authentication status for all connected services, including sync errors."""
    sync_states = _get_sync_states()

    services = {
        "google": _check_google(),
        "google_drive": _check_google(),
        "slack": _check_slack(),
        "notion": _check_notion(),
        "granola": _check_granola(),
        "github": _check_github(),
        "ramp": _check_ramp(),
    }

    # Attach sync state to each service
    for service_name, info in services.items():
        sync_sources = _AUTH_TO_SYNC.get(service_name, [])
        sync_info = {}
        for src in sync_sources:
            if src in sync_states:
                sync_info[src] = sync_states[src]
        info["sync"] = sync_info

    return services


@router.post("/google")
def google_auth():
    """Trigger browser-based Google OAuth flow."""
    try:
        from connectors.google_auth import run_oauth_flow

        run_oauth_flow()
        # Clear stale sync errors for all Google-related sources
        _clear_sync_errors(_AUTH_TO_SYNC.get("google", []))
        _clear_sync_errors(_AUTH_TO_SYNC.get("google_drive", []))
        return {"status": "authenticated"}
    except Exception as e:
        logger.exception("Google OAuth flow failed")
        return {"status": "error", "error": "OAuth flow failed"}


@router.post("/google/revoke")
def google_revoke():
    """Remove stored Google token to force re-authentication."""
    if TOKEN_PATH.exists():
        TOKEN_PATH.unlink()
        # Clear cached credentials
        try:
            from connectors import google_auth

            google_auth._cached_creds = None
        except Exception:
            pass
        return {"status": "revoked"}
    return {"status": "no_token"}


@router.post("/test/{service}")
def test_connection(service: str):
    """Test a specific service connection and return detailed status."""
    checkers = {
        "google": _check_google,
        "google_drive": _check_google,
        "slack": _check_slack,
        "notion": _check_notion,
        "granola": _check_granola,
        "github": _check_github,
        "ramp": _check_ramp,
    }
    checker = checkers.get(service)
    if not checker:
        return {"error": f"Unknown service: {service}"}
    result = checker()
    # If connection test passed, clear stale sync errors
    if result.get("connected"):
        _clear_sync_errors(_AUTH_TO_SYNC.get(service, []))
    return result


# --- Secrets management ---


def _mask_secret(value: str) -> str:
    """Return a masked version of a secret for display. Shows only first 3 chars."""
    if not value:
        return ""
    if len(value) <= 6:
        return "***"
    return value[:3] + "***"


@router.get("/secrets")
def get_secrets():
    """Return which secrets are configured (masked values, never raw)."""
    result = {}
    for key in ALLOWED_SECRET_KEYS:
        val = get_secret(key)
        result[key] = {
            "configured": bool(val),
            "masked": _mask_secret(val) if val else "",
        }
    return result


class SecretUpdate(BaseModel):
    key: str
    value: str


@router.post("/secrets")
def update_secret(body: SecretUpdate):
    """Save a secret to config.json and reload into environment."""
    if body.key not in ALLOWED_SECRET_KEYS:
        return {"error": f"Unknown secret key: {body.key}"}
    set_secret(body.key, body.value)
    # Clear stale sync errors for sources affected by this secret
    _clear_sync_errors(_SECRET_TO_SYNC.get(body.key, []))
    return {"status": "ok", "key": body.key, "configured": True}


@router.delete("/secrets/{key}")
def remove_secret(key: str):
    """Remove a secret from config.json."""
    if key not in ALLOWED_SECRET_KEYS:
        return {"error": f"Unknown secret key: {key}"}
    delete_secret(key)
    return {"status": "ok", "key": key, "configured": False}


# --- Connector management ---


@router.get("/connectors")
def list_connectors():
    """Return all registered connectors with their metadata and enabled status."""
    from app_config import get_connector_config
    from connectors.registry import get_all

    config = get_connector_config()
    result = []
    for c in get_all():
        entry = config.get(c.id, {})
        enabled = entry.get("enabled", c.default_enabled)
        result.append(
            {
                "id": c.id,
                "name": c.name,
                "description": c.description,
                "category": c.category,
                "secret_keys": c.secret_keys,
                "help_steps": c.help_steps,
                "help_url": c.help_url,
                "default_enabled": c.default_enabled,
                "enabled": enabled,
            }
        )
    return result


@router.post("/connectors/{connector_id}/enable")
def enable_connector(connector_id: str):
    """Enable a connector."""
    from app_config import set_connector_enabled
    from connectors.registry import get_by_id

    if not get_by_id(connector_id):
        return {"error": f"Unknown connector: {connector_id}"}
    set_connector_enabled(connector_id, True)
    # Clear stale sync errors so UI doesn't show old failures
    _clear_sync_errors(_CONNECTOR_TO_SYNC.get(connector_id, []))
    return {"status": "ok", "connector": connector_id, "enabled": True}


@router.post("/connectors/{connector_id}/disable")
def disable_connector(connector_id: str):
    """Disable a connector."""
    from app_config import set_connector_enabled
    from connectors.registry import get_by_id

    if not get_by_id(connector_id):
        return {"error": f"Unknown connector: {connector_id}"}
    set_connector_enabled(connector_id, False)
    return {"status": "ok", "connector": connector_id, "enabled": False}
