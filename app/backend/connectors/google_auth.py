"""Shared Google API authentication."""

import json
import os
import stat
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from config import GCLOUD_CREDENTIALS_PATH, GOOGLE_SCOPES

TOKEN_PATH = Path(__file__).parent.parent / ".google_token.json"
_cached_creds: Credentials | None = None


def _get_quota_project_id() -> str | None:
    """Read quota_project_id from ADC credentials."""
    if GCLOUD_CREDENTIALS_PATH.exists():
        with open(GCLOUD_CREDENTIALS_PATH) as f:
            return json.load(f).get("quota_project_id")
    return None


def get_google_credentials() -> Credentials:
    global _cached_creds
    if _cached_creds and _cached_creds.valid:
        return _cached_creds

    quota_project_id = _get_quota_project_id()

    # Try app-specific token first
    if TOKEN_PATH.exists():
        _cached_creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), GOOGLE_SCOPES)
        if quota_project_id:
            _cached_creds = _cached_creds.with_quota_project(quota_project_id)
        if _cached_creds.expired and _cached_creds.refresh_token:
            _cached_creds.refresh(Request())
            TOKEN_PATH.write_text(_cached_creds.to_json())
            os.chmod(TOKEN_PATH, stat.S_IRUSR | stat.S_IWUSR)
        if _cached_creds.valid:
            return _cached_creds

    # Fall back to ADC
    if not GCLOUD_CREDENTIALS_PATH.exists():
        raise FileNotFoundError("No Google credentials found. Run the OAuth flow at /api/auth/google")

    with open(GCLOUD_CREDENTIALS_PATH) as f:
        cred_data = json.load(f)

    try:
        _cached_creds = Credentials(
            token=None,
            refresh_token=cred_data.get("refresh_token"),
            client_id=cred_data.get("client_id"),
            client_secret=cred_data.get("client_secret"),
            token_uri="https://oauth2.googleapis.com/token",
            scopes=GOOGLE_SCOPES,
            quota_project_id=cred_data.get("quota_project_id"),
        )
        _cached_creds.refresh(Request())
        # Save for future use
        TOKEN_PATH.write_text(_cached_creds.to_json())
        os.chmod(TOKEN_PATH, stat.S_IRUSR | stat.S_IWUSR)
        return _cached_creds
    except Exception:
        raise RuntimeError(
            "ADC token refresh failed. Run: gcloud auth application-default login "
            "--scopes='https://www.googleapis.com/auth/gmail.readonly,"
            "https://www.googleapis.com/auth/calendar.readonly,"
            "https://www.googleapis.com/auth/drive.readonly,"
            "https://www.googleapis.com/auth/spreadsheets.readonly'"
        )


def run_oauth_flow() -> Credentials:
    """Run browser-based OAuth flow using ADC client credentials."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not GCLOUD_CREDENTIALS_PATH.exists():
        raise FileNotFoundError("No gcloud credentials found")

    with open(GCLOUD_CREDENTIALS_PATH) as f:
        cred_data = json.load(f)

    client_config = {
        "installed": {
            "client_id": cred_data["client_id"],
            "client_secret": cred_data["client_secret"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost:8080"],
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, GOOGLE_SCOPES)
    creds = flow.run_local_server(port=8080, open_browser=True)

    global _cached_creds
    _cached_creds = creds
    TOKEN_PATH.write_text(creds.to_json())
    os.chmod(TOKEN_PATH, stat.S_IRUSR | stat.S_IWUSR)
    return creds
