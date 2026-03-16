"""Shared Microsoft Graph API authentication via MSAL.

Parallels google_auth.py — stores OAuth token at ~/.personal-dashboard/.microsoft_token.json,
handles browser-based auth code flow and automatic token refresh.
"""

import json
import logging
import os
import stat
import subprocess
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import msal

from config import DATA_DIR

logger = logging.getLogger(__name__)

TOKEN_PATH = DATA_DIR / ".microsoft_token.json"
_cached_token: dict | None = None
_lock = threading.Lock()

MICROSOFT_SCOPES = [
    "User.Read",
    "Mail.ReadWrite",
    "Calendars.ReadWrite",
    "Files.Read.All",
    "offline_access",
]


def _get_client_credentials() -> tuple[str, str, str] | None:
    """Return (client_id, client_secret, tenant_id) or None."""
    from app_config import get_secret

    client_id = get_secret("MICROSOFT_CLIENT_ID")
    client_secret = get_secret("MICROSOFT_CLIENT_SECRET")
    if client_id and client_secret:
        tenant_id = get_secret("MICROSOFT_TENANT_ID") or "common"
        return (client_id, client_secret, tenant_id)
    return None


def _get_msal_app() -> msal.ConfidentialClientApplication:
    """Build an MSAL ConfidentialClientApplication."""
    creds = _get_client_credentials()
    if not creds:
        raise FileNotFoundError(
            "No Microsoft credentials found. Add MICROSOFT_CLIENT_ID and MICROSOFT_CLIENT_SECRET in Settings."
        )
    client_id, client_secret, tenant_id = creds
    authority = f"https://login.microsoftonline.com/{tenant_id}"
    return msal.ConfidentialClientApplication(
        client_id,
        authority=authority,
        client_credential=client_secret,
    )


def get_microsoft_token() -> str:
    """Return a valid access token string. Refreshes automatically via MSAL."""
    global _cached_token
    with _lock:
        # Try cached in-memory token first
        if _cached_token and _cached_token.get("access_token"):
            return _cached_token["access_token"]

        # Try loading from disk and refreshing
        if TOKEN_PATH.exists():
            try:
                token_data = json.loads(TOKEN_PATH.read_text())
                refresh_token = token_data.get("refresh_token")
                if refresh_token:
                    app = _get_msal_app()
                    result = app.acquire_token_by_refresh_token(refresh_token, scopes=MICROSOFT_SCOPES)
                    if "access_token" in result:
                        _save_token(result)
                        return result["access_token"]
                    else:
                        logger.warning(
                            "Microsoft token refresh failed: %s",
                            result.get("error_description", result.get("error")),
                        )
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to read Microsoft token file: %s", e)

    raise FileNotFoundError("No Microsoft token found. Click Authenticate in Settings to connect Microsoft 365.")


def run_oauth_flow() -> dict:
    """Run browser-based MSAL authorization code flow.

    Opens system browser for Microsoft login, captures the redirect on localhost:8080.
    """
    logger.info("Starting Microsoft OAuth flow...")

    app = _get_msal_app()
    redirect_uri = "http://localhost:8080"

    # Initiate the auth code flow
    flow = app.initiate_auth_code_flow(
        scopes=MICROSOFT_SCOPES,
        redirect_uri=redirect_uri,
    )

    auth_url = flow.get("auth_uri")
    if not auth_url:
        raise RuntimeError(f"Failed to initiate Microsoft auth flow: {flow.get('error_description', 'unknown error')}")

    # Capture the auth response via a temporary local HTTP server
    auth_response = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            # Flatten single-value params
            for k, v in params.items():
                auth_response[k] = v[0] if len(v) == 1 else v

            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            if "error" in auth_response:
                self.wfile.write(
                    b"<html><body><h2>Authentication failed.</h2><p>You can close this window.</p></body></html>"
                )
            else:
                self.wfile.write(
                    b"<html><body><h2>Microsoft 365 connected!</h2>"
                    b"<p>You can close this window and return to the dashboard.</p></body></html>"
                )

        def log_message(self, format, *args):
            logger.debug("OAuth callback: %s", format % args)

    server = HTTPServer(("localhost", 8080), CallbackHandler)
    server.timeout = 120  # 2 minute timeout

    # Open browser — use macOS `open` for reliability (same as google_auth.py)
    logger.info("Opening Microsoft OAuth URL in system browser")
    try:
        subprocess.Popen(["open", auth_url])
    except Exception:
        logger.warning("macOS `open` failed, falling back to webbrowser.open")
        webbrowser.open(auth_url)

    # Wait for the callback
    logger.info("Waiting for OAuth callback on port 8080...")
    server.handle_request()
    server.server_close()

    if not auth_response or "error" in auth_response:
        error_desc = auth_response.get("error_description", auth_response.get("error", "No response"))
        raise RuntimeError(f"Microsoft OAuth failed: {error_desc}")

    # Exchange auth code for tokens
    result = app.acquire_token_by_auth_code_flow(flow, auth_response)
    if "access_token" not in result:
        error = result.get("error_description", result.get("error", "unknown"))
        raise RuntimeError(f"Microsoft token exchange failed: {error}")

    _save_token(result)
    logger.info("Microsoft OAuth flow completed, token saved to %s", TOKEN_PATH)
    return result


def revoke_token():
    """Delete stored Microsoft token."""
    global _cached_token
    with _lock:
        _cached_token = None
        TOKEN_PATH.unlink(missing_ok=True)
    logger.info("Microsoft token revoked")


def _save_token(result: dict):
    """Persist token data to disk with 0600 permissions."""
    global _cached_token
    # Store only what we need for refresh
    token_data = {
        "access_token": result.get("access_token"),
        "refresh_token": result.get("refresh_token"),
        "token_type": result.get("token_type"),
        "expires_in": result.get("expires_in"),
        "scope": result.get("scope"),
    }
    _cached_token = token_data
    TOKEN_PATH.write_text(json.dumps(token_data, indent=2) + "\n")
    os.chmod(TOKEN_PATH, stat.S_IRUSR | stat.S_IWUSR)
