"""Manages ~/.personal-dashboard/config.json — profile, secrets, connector settings.

Config file is stored with 0600 permissions alongside the SQLite database.
Falls back to os.environ / .env for backward compatibility.
"""

import json
import os
import stat
from pathlib import Path
from threading import Lock

_lock = Lock()
_cache: dict | None = None

ALLOWED_SECRET_KEYS = frozenset(
    {
        "SLACK_TOKEN",
        "NOTION_TOKEN",
        "GEMINI_API_KEY",
        "RAMP_CLIENT_ID",
        "RAMP_CLIENT_SECRET",
        "LUNCHMONEY_TOKEN",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "MICROSOFT_CLIENT_ID",
        "MICROSOFT_CLIENT_SECRET",
        "MICROSOFT_TENANT_ID",
    }
)

DEFAULT_CONFIG = {
    "profile": {},
    "secrets": {},
    "connectors": {},
    "setup_complete": False,
}


def _config_path() -> Path:
    from config import CONFIG_PATH

    return CONFIG_PATH


def load_config() -> dict:
    """Read config.json, return default config if missing."""
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
        path = _config_path()
        if path.exists():
            try:
                data = json.loads(path.read_text())
                _cache = {**DEFAULT_CONFIG, **data}
                return _cache
            except (json.JSONDecodeError, OSError):
                pass
        _cache = dict(DEFAULT_CONFIG)
        return _cache


def save_config(updates: dict) -> dict:
    """Merge updates into config.json, write with 0600 permissions."""
    global _cache
    with _lock:
        path = _config_path()
        if path.exists():
            try:
                current = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                current = dict(DEFAULT_CONFIG)
        else:
            current = dict(DEFAULT_CONFIG)

        # Deep merge for known dict keys
        for key in ("profile", "secrets", "connectors"):
            if key in updates and isinstance(updates[key], dict):
                if key not in current or not isinstance(current[key], dict):
                    current[key] = {}
                current[key].update(updates[key])
                updates = {k: v for k, v in updates.items() if k != key}

        current.update(updates)

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(current, indent=2) + "\n")
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600

        _cache = current
        return current


def invalidate_cache():
    """Clear the in-memory cache so next load_config() re-reads from disk."""
    global _cache
    with _lock:
        _cache = None


def get_profile() -> dict:
    """Return the profile section of config."""
    return load_config().get("profile", {})


def update_profile(updates: dict) -> dict:
    """Update profile fields and return the updated profile."""
    save_config({"profile": updates})
    return get_profile()


def is_setup_complete() -> bool:
    return load_config().get("setup_complete", False)


def get_secret(key: str) -> str | None:
    """Read a secret — checks config.json first, then os.environ."""
    val = load_config().get("secrets", {}).get(key)
    if val:
        return val
    return os.environ.get(key) or None


def set_secret(key: str, value: str):
    """Write a secret to config.json and also set in os.environ for current process."""
    if key not in ALLOWED_SECRET_KEYS:
        raise ValueError(f"Secret key {key!r} not in allowed list")
    save_config({"secrets": {key: value}})
    os.environ[key] = value


def delete_secret(key: str):
    """Remove a secret from config.json and os.environ."""
    if key not in ALLOWED_SECRET_KEYS:
        raise ValueError(f"Secret key {key!r} not in allowed list")
    config = load_config()
    secrets = config.get("secrets", {})
    if key in secrets:
        del secrets[key]
        save_config({"secrets": secrets})
    os.environ.pop(key, None)


def get_connector_config() -> dict:
    """Return connector enabled/disabled states from config."""
    return load_config().get("connectors", {})


def set_connector_enabled(connector_id: str, enabled: bool):
    """Enable or disable a connector in config."""
    save_config({"connectors": {connector_id: {"enabled": enabled}}})


def get_google_access_mode() -> str:
    """Return 'readonly' or 'readwrite' from connectors.google.access_mode."""
    google = get_connector_config().get("google", {})
    return google.get("access_mode", "readonly")


def set_google_access_mode(mode: str):
    """Set Google access mode ('readonly' or 'readwrite') in config."""
    if mode not in ("readonly", "readwrite"):
        raise ValueError(f"Invalid mode: {mode!r}")
    save_config({"connectors": {"google": {"access_mode": mode}}})


def get_email_calendar_provider() -> str:
    """Return 'google' or 'microsoft'. Defaults to 'google' for backward compat."""
    return get_profile().get("email_calendar_provider") or "google"


def get_prompt_context() -> str:
    """Build a context string for AI prompts from the user profile.

    Returns e.g. 'for Alex, the VP of Engineering at Acme Corp (a SaaS platform)'
    or 'for the user' if no profile is configured.
    """
    profile = get_profile()
    name = profile.get("user_name", "").strip()
    title = profile.get("user_title", "").strip()
    company = profile.get("user_company", "").strip()
    company_desc = profile.get("user_company_description", "").strip()

    if not name:
        return "for the user"

    parts = [f"for {name}"]
    if title and company:
        parts.append(f"the {title} of {company}")
        if company_desc:
            parts[1] += f" ({company_desc})"
    elif title:
        parts.append(f"the {title}")
    elif company:
        parts.append(f"at {company}")

    return ", ".join(parts)
