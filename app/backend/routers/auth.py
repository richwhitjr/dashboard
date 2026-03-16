"""Authentication status and management for connected services."""

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from app_config import ALLOWED_SECRET_KEYS, delete_secret, get_secret, set_secret
from config import DATA_DIR, get_google_scopes
from database import get_write_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

TOKEN_PATH = DATA_DIR / ".google_token.json"


def _check_google() -> dict:
    """Check Google auth status by validating credentials."""
    from connectors.google_auth import _get_client_credentials

    result = {"configured": False, "connected": False, "error": None, "detail": None}

    has_client_creds = _get_client_credentials() is not None
    if not has_client_creds and not TOKEN_PATH.exists():
        result["detail"] = "No Google credentials found. Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in Settings."
        return result

    result["configured"] = has_client_creds or TOKEN_PATH.exists()
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


def _check_claude_code() -> dict:
    """Check if Claude Code CLI is installed."""
    import shutil

    result = {"configured": False, "connected": False, "error": None, "detail": None}
    path = shutil.which("claude")
    if path:
        result["configured"] = True
        result["connected"] = True
        result["detail"] = f"Found at {path}"
    else:
        result["error"] = "Claude Code CLI not found — install with: npm install -g @anthropic-ai/claude-code"
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


def _check_microsoft() -> dict:
    """Check Microsoft 365 auth status by validating credentials."""
    from connectors.microsoft_auth import TOKEN_PATH as MS_TOKEN_PATH
    from connectors.microsoft_auth import _get_client_credentials

    result = {"configured": False, "connected": False, "error": None, "detail": None}

    has_creds = _get_client_credentials() is not None
    if not has_creds and not MS_TOKEN_PATH.exists():
        result["detail"] = (
            "No Microsoft credentials found. Add MICROSOFT_CLIENT_ID and MICROSOFT_CLIENT_SECRET in Settings."
        )
        return result

    result["configured"] = has_creds or MS_TOKEN_PATH.exists()
    try:
        from connectors.microsoft_auth import get_microsoft_token

        token = get_microsoft_token()
        if token:
            result["connected"] = True
            result["detail"] = "Authenticated via Microsoft OAuth"
    except FileNotFoundError as e:
        result["error"] = str(e)
    except Exception as e:
        logger.exception("Microsoft auth check failed")
        result["error"] = str(e)

    return result


def _check_granola() -> dict:
    """Check Granola MCP auth status by inspecting stored tokens."""
    from connectors.mcp_client import _has_any_tokens, _has_valid_tokens

    result = {"configured": False, "connected": False, "error": None, "detail": None}

    if _has_valid_tokens():
        result["configured"] = True
        result["connected"] = True
        result["detail"] = "Authenticated via Granola MCP (mcp.granola.ai)"
    elif _has_any_tokens():
        # Tokens exist but access token is expired and no usable refresh token.
        # The user needs to re-authenticate interactively.
        result["configured"] = True
        result["error"] = "Granola access token expired. Click 'Authenticate' to re-connect."
    else:
        result["detail"] = "Not authenticated. Enable and click 'Authenticate' to connect."

    return result


def _check_news() -> dict:
    """News requires no auth — always available."""
    return {
        "configured": True,
        "connected": True,
        "error": None,
        "detail": "News aggregation works automatically — no setup needed",
    }


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
    "microsoft": ["outlook_email", "outlook_calendar"],
    "microsoft_drive": ["onedrive"],
    "slack": ["slack"],
    "notion": ["notion", "notion_meetings"],
    "granola": ["granola"],
    "github": ["github"],
    "ramp": ["ramp", "ramp_vendors", "ramp_bills"],
}


# Map secret keys to the sync_state sources they affect
_SECRET_TO_SYNC = {
    "SLACK_TOKEN": ["slack"],
    "NOTION_TOKEN": ["notion", "notion_meetings"],
    "RAMP_CLIENT_ID": ["ramp", "ramp_vendors", "ramp_bills"],
    "RAMP_CLIENT_SECRET": ["ramp", "ramp_vendors", "ramp_bills"],
    "GOOGLE_CLIENT_ID": ["gmail", "calendar", "drive", "sheets", "docs"],
    "GOOGLE_CLIENT_SECRET": ["gmail", "calendar", "drive", "sheets", "docs"],
    "MICROSOFT_CLIENT_ID": ["outlook_email", "outlook_calendar", "onedrive"],
    "MICROSOFT_CLIENT_SECRET": ["outlook_email", "outlook_calendar", "onedrive"],
}

# Map connector IDs to sync_state sources
_CONNECTOR_TO_SYNC = {
    "google": ["gmail", "calendar"],
    "google_drive": ["drive", "sheets", "docs"],
    "microsoft": ["outlook_email", "outlook_calendar"],
    "microsoft_drive": ["onedrive"],
    "slack": ["slack"],
    "notion": ["notion", "notion_meetings"],
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
        "microsoft": _check_microsoft(),
        "microsoft_drive": _check_microsoft(),
        "slack": _check_slack(),
        "notion": _check_notion(),
        "granola": _check_granola(),
        "github": _check_github(),
        "ramp": _check_ramp(),
        "claude_code": _check_claude_code(),
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


@router.get("/google/scopes")
def google_scopes():
    """Check if the current Google token has the required scopes."""
    required = get_google_scopes()
    current: list[str] = []
    needs_reauth = True

    if TOKEN_PATH.exists():
        try:
            from google.oauth2.credentials import Credentials

            creds = Credentials.from_authorized_user_file(str(TOKEN_PATH))
            current = list(creds.scopes or [])
            needs_reauth = not set(required).issubset(set(current))
        except Exception:
            pass

    return {"required": required, "current": current, "needs_reauth": needs_reauth}


@router.post("/google")
def google_auth():
    """Trigger browser-based Google OAuth flow."""
    logger.info("POST /api/auth/google — starting OAuth flow")
    try:
        from connectors.google_auth import run_oauth_flow

        run_oauth_flow()
        # Clear stale sync errors for all Google-related sources
        _clear_sync_errors(_AUTH_TO_SYNC.get("google", []))
        _clear_sync_errors(_AUTH_TO_SYNC.get("google_drive", []))
        logger.info("POST /api/auth/google — OAuth flow completed successfully")
        return {"status": "authenticated"}
    except Exception as e:
        logger.exception("Google OAuth flow failed: %s", e)
        return {"status": "error", "error": f"OAuth flow failed: {e}"}


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


@router.post("/microsoft")
def microsoft_auth():
    """Trigger browser-based Microsoft OAuth flow."""
    logger.info("POST /api/auth/microsoft — starting OAuth flow")
    try:
        from connectors.microsoft_auth import run_oauth_flow

        run_oauth_flow()
        _clear_sync_errors(_AUTH_TO_SYNC.get("microsoft", []))
        _clear_sync_errors(_AUTH_TO_SYNC.get("microsoft_drive", []))
        logger.info("POST /api/auth/microsoft — OAuth flow completed successfully")
        return {"status": "authenticated"}
    except Exception as e:
        logger.exception("Microsoft OAuth flow failed: %s", e)
        return {"status": "error", "error": f"OAuth flow failed: {e}"}


@router.post("/microsoft/revoke")
def microsoft_revoke():
    """Remove stored Microsoft token to force re-authentication."""
    from connectors.microsoft_auth import revoke_token

    revoke_token()
    return {"status": "revoked"}


@router.post("/granola/connect")
def granola_connect():
    """Initiate Granola OAuth flow (opens browser for user consent)."""
    try:
        from connectors.mcp_client import initiate_granola_oauth

        initiate_granola_oauth()
        _clear_sync_errors(_AUTH_TO_SYNC.get("granola", []))
        return {"status": "authenticated"}
    except Exception:
        logger.exception("Granola OAuth flow failed")
        return {"status": "error", "error": "Granola OAuth flow failed"}


@router.post("/test/{service}")
def test_connection(service: str):
    """Test a specific service connection and return detailed status."""
    checkers = {
        "google": _check_google,
        "google_drive": _check_google,
        "microsoft": _check_microsoft,
        "microsoft_drive": _check_microsoft,
        "slack": _check_slack,
        "notion": _check_notion,
        "granola": _check_granola,
        "github": _check_github,
        "ramp": _check_ramp,
        "claude_code": _check_claude_code,
        "news": _check_news,
    }
    # Lazy import to avoid circular deps
    from routers.whatsapp import _check_whatsapp

    checkers["whatsapp"] = _check_whatsapp
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
def list_connectors(capability: str | None = None):
    """Return all registered connectors with their metadata and enabled status.

    Optionally filter by capability (e.g. ?capability=meeting_notes).
    """
    from app_config import get_connector_config, get_google_access_mode
    from connectors.registry import get_all, get_by_capability

    config = get_connector_config()
    google_mode = get_google_access_mode()
    connectors = get_by_capability(capability) if capability else get_all()
    result = []
    for c in connectors:
        entry = config.get(c.id, {})
        enabled = entry.get("enabled", c.default_enabled)
        item: dict = {
            "id": c.id,
            "name": c.name,
            "description": c.description,
            "category": c.category,
            "secret_keys": c.secret_keys,
            "help_steps": c.help_steps,
            "help_url": c.help_url,
            "default_enabled": c.default_enabled,
            "enabled": enabled,
            "capabilities": c.capabilities,
        }
        # Include access mode for Google connectors
        if c.id in ("google", "google_drive"):
            item["google_access_mode"] = google_mode
        result.append(item)
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


# --- Email/Calendar provider switch ---


@router.post("/email-calendar-provider/switch")
def switch_email_calendar_provider(body: dict):
    """Switch between Google and Microsoft for email/calendar.

    Clears synced email/calendar data so the new provider starts fresh.
    """
    provider = body.get("provider", "")
    if provider not in ("google", "microsoft"):
        return {"error": "provider must be 'google' or 'microsoft'"}

    from app_config import get_email_calendar_provider, update_profile

    old_provider = get_email_calendar_provider()
    if old_provider == provider:
        return {"status": "ok", "provider": provider, "changed": False}

    # Update profile setting
    update_profile({"email_calendar_provider": provider})

    # Clear synced email/calendar data so new provider starts fresh
    with get_write_db() as db:
        db.execute("DELETE FROM emails")
        db.execute("DELETE FROM calendar_events")
        db.execute("DELETE FROM cached_email_priorities")
        # Clear sync state for both providers
        db.execute("DELETE FROM sync_state WHERE source IN ('gmail', 'calendar', 'outlook_email', 'outlook_calendar')")
        db.commit()

    logger.info("Switched email/calendar provider from %s to %s, cleared data", old_provider, provider)
    return {"status": "ok", "provider": provider, "changed": True}


# --- Google access mode ---


class AccessModeUpdate(BaseModel):
    mode: str  # "readonly" or "readwrite"


@router.get("/google/access-mode")
def get_access_mode():
    """Return the current Google access mode."""
    from app_config import get_google_access_mode

    return {"mode": get_google_access_mode()}


@router.post("/google/access-mode")
def set_access_mode(body: AccessModeUpdate):
    """Set Google access mode and invalidate cached credentials."""
    from app_config import get_google_access_mode, set_google_access_mode

    old_mode = get_google_access_mode()
    if body.mode not in ("readonly", "readwrite"):
        return {"error": "mode must be 'readonly' or 'readwrite'"}

    set_google_access_mode(body.mode)

    # If mode changed, clear cached credentials so next call uses new scopes
    if old_mode != body.mode:
        try:
            from connectors import google_auth

            google_auth._cached_creds = None
        except Exception:
            pass
        # Delete token — it was issued for the old scopes
        if TOKEN_PATH.exists():
            TOKEN_PATH.unlink(missing_ok=True)

    needs_reauth = old_mode != body.mode
    return {"status": "ok", "mode": body.mode, "needs_reauth": needs_reauth}
