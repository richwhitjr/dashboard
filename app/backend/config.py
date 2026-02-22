import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _data_dir() -> Path:
    """Resolve the user data directory. Creates it if needed."""
    d = Path(os.environ.get("DASHBOARD_DATA_DIR", Path.home() / ".personal-dashboard"))
    d.mkdir(parents=True, exist_ok=True)
    return d


DATA_DIR = _data_dir()
CONFIG_PATH = DATA_DIR / "config.json"


def _resolve_db_path() -> Path:
    """Resolve database path."""
    env_path = os.environ.get("DASHBOARD_DB_PATH")
    if env_path:
        return Path(env_path)
    return DATA_DIR / "dashboard.db"


DATABASE_PATH = _resolve_db_path()

TEAMS_DIR = REPO_ROOT / "teams"
HIDDEN_TEAMS_DIR = REPO_ROOT / "hidden" / "teams"
EXECUTIVES_DIR = REPO_ROOT / "executives"

GRANOLA_CACHE_PATH = Path.home() / "Library" / "Application Support" / "Granola" / "cache-v3.json"
GCLOUD_CREDENTIALS_PATH = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]

GMAIL_MAX_RESULTS = 50
CALENDAR_DAYS_AHEAD = 14
CALENDAR_DAYS_BEHIND = 90
SLACK_MESSAGE_LIMIT = 100

GITHUB_PR_SYNC_LIMIT = 50


def get_github_repo() -> str:
    """Get the GitHub repo from user config, with env var fallback."""
    from app_config import get_profile

    repo = get_profile().get("github_repo", "")
    return repo or os.environ.get("GITHUB_REPO", "")


RAMP_TRANSACTION_SYNC_DAYS = 90
