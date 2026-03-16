"""Shared Google API authentication."""

import json
import logging
import os
import stat

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from config import DATA_DIR, GCLOUD_CREDENTIALS_PATH, get_google_scopes

logger = logging.getLogger(__name__)

TOKEN_PATH = DATA_DIR / ".google_token.json"
_cached_creds: Credentials | None = None


def _scopes_sufficient(creds: Credentials) -> bool:
    """Check if the credential's granted scopes cover all required scopes."""
    if not creds.scopes:
        return True  # Can't verify from token — assume OK
    required = set(get_google_scopes())
    granted = set(creds.scopes)
    return required.issubset(granted)


def _get_quota_project_id() -> str | None:
    """Read quota_project_id from ADC credentials."""
    if GCLOUD_CREDENTIALS_PATH.exists():
        with open(GCLOUD_CREDENTIALS_PATH) as f:
            return json.load(f).get("quota_project_id")
    return None


def _get_client_credentials() -> tuple[str, str] | None:
    """Resolve Google OAuth client credentials from config or file.

    Returns (client_id, client_secret) or None if no credentials found.
    Priority:
      1. GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET in config.json secrets
      2. google_client_secret.json file in DATA_DIR

    Note: gcloud ADC credentials are intentionally excluded here. The gcloud
    CLI's own client_id/client_secret cannot be used for new OAuth flows
    (Google rejects them with 'invalid_client'). ADC token refresh is handled
    separately in get_google_credentials().
    """
    from app_config import get_secret

    # 1. Config secrets (primary path for DMG users)
    client_id = get_secret("GOOGLE_CLIENT_ID")
    client_secret = get_secret("GOOGLE_CLIENT_SECRET")
    if client_id and client_secret:
        return (client_id, client_secret)

    # 2. Bundled client_secret.json file in data directory
    client_secret_file = DATA_DIR / "google_client_secret.json"
    if client_secret_file.exists():
        try:
            with open(client_secret_file) as f:
                data = json.load(f)
            app_data = data.get("installed") or data.get("web") or {}
            cid = app_data.get("client_id")
            csec = app_data.get("client_secret")
            if cid and csec:
                return (cid, csec)
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to read google_client_secret.json")

    return None


def get_google_credentials() -> Credentials:
    global _cached_creds
    if _cached_creds and _cached_creds.valid:
        return _cached_creds

    scopes = get_google_scopes()
    quota_project_id = _get_quota_project_id()

    # Try app-specific token first
    if TOKEN_PATH.exists():
        _cached_creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), scopes)
        if quota_project_id:
            _cached_creds = _cached_creds.with_quota_project(quota_project_id)
        if not _scopes_sufficient(_cached_creds):
            _cached_creds = None
            TOKEN_PATH.unlink(missing_ok=True)
            raise RuntimeError("Google OAuth scopes have changed. Please re-authenticate at /api/auth/google")
        if _cached_creds.expired and _cached_creds.refresh_token:
            try:
                _cached_creds.refresh(Request())
            except RefreshError as e:
                logger.warning("Token refresh failed (likely scope change): %s", e)
                _cached_creds = None
                TOKEN_PATH.unlink(missing_ok=True)
                # Fall through to ADC
            else:
                TOKEN_PATH.write_text(_cached_creds.to_json())
                os.chmod(TOKEN_PATH, stat.S_IRUSR | stat.S_IWUSR)
        if _cached_creds and _cached_creds.valid:
            return _cached_creds

    # Fall back to ADC refresh_token (only works if gcloud ADC has one)
    if GCLOUD_CREDENTIALS_PATH.exists():
        with open(GCLOUD_CREDENTIALS_PATH) as f:
            cred_data = json.load(f)

        if cred_data.get("refresh_token"):
            try:
                _cached_creds = Credentials(
                    token=None,
                    refresh_token=cred_data.get("refresh_token"),
                    client_id=cred_data.get("client_id"),
                    client_secret=cred_data.get("client_secret"),
                    token_uri="https://oauth2.googleapis.com/token",
                    scopes=scopes,
                    quota_project_id=cred_data.get("quota_project_id"),
                )
                _cached_creds.refresh(Request())
                TOKEN_PATH.write_text(_cached_creds.to_json())
                os.chmod(TOKEN_PATH, stat.S_IRUSR | stat.S_IWUSR)
                return _cached_creds
            except (RefreshError, Exception) as e:
                logger.warning("ADC token refresh failed: %s", e)
                _cached_creds = None

    raise FileNotFoundError(
        "No Google credentials found. Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET "
        "in Settings, then click Authenticate."
    )


def run_oauth_flow() -> Credentials:
    """Run browser-based OAuth flow using resolved client credentials."""
    import subprocess
    import webbrowser

    from google_auth_oauthlib.flow import InstalledAppFlow

    logger.info("Starting Google OAuth flow...")

    creds_pair = _get_client_credentials()
    if not creds_pair:
        raise FileNotFoundError(
            "No Google OAuth client credentials found. Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in Settings."
        )

    client_id, client_secret = creds_pair
    scopes = get_google_scopes()
    logger.info("OAuth scopes: %s", scopes)
    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost:8080"],
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, scopes)

    # In pywebview (DMG app), webbrowser.open() can silently fail because
    # PyInstaller bundles may not find the system browser correctly.
    # Monkey-patch webbrowser.open to use macOS `open` command which always works.
    _orig_open = webbrowser.open

    def _open_via_macos(url, *args, **kwargs):
        logger.info("Opening OAuth URL in system browser")
        try:
            subprocess.Popen(["open", url])
            return True
        except Exception:
            logger.warning("macOS `open` failed, falling back to webbrowser.open")
            return _orig_open(url, *args, **kwargs)

    webbrowser.open = _open_via_macos
    try:
        logger.info("Waiting for OAuth callback on port 8080...")
        creds = flow.run_local_server(port=8080, open_browser=True)
    finally:
        webbrowser.open = _orig_open

    global _cached_creds
    _cached_creds = creds
    TOKEN_PATH.write_text(creds.to_json())
    os.chmod(TOKEN_PATH, stat.S_IRUSR | stat.S_IWUSR)
    logger.info("OAuth flow completed, token saved to %s", TOKEN_PATH)
    return creds
