"""GitHub REST API connector for PR sync."""

import json
import os
import shutil
import subprocess

import httpx

from config import GITHUB_PR_SYNC_LIMIT, get_github_repo
from database import batch_upsert, get_write_db

GITHUB_API_BASE = "https://api.github.com"

_cached_token: str | None = None

# Common install locations for gh CLI on macOS
_GH_FALLBACK_PATHS = ["/opt/homebrew/bin/gh", "/usr/local/bin/gh", "/usr/bin/gh"]


def _find_gh() -> str:
    """Return path to gh CLI, searching PATH and common Homebrew locations."""
    # Try with an augmented PATH that includes Homebrew
    augmented_env = os.environ.copy()
    augmented_env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + augmented_env.get("PATH", "")
    found = shutil.which("gh", path=augmented_env["PATH"])
    if found:
        return found
    for path in _GH_FALLBACK_PATHS:
        if os.path.isfile(path):
            return path
    return "gh"  # fall back to bare name; will raise FileNotFoundError if missing


def _get_token() -> str:
    """Get GitHub token from gh CLI auth. Cached after first call."""
    global _cached_token
    if _cached_token:
        return _cached_token
    result = subprocess.run(
        [_find_gh(), "auth", "token"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode != 0:
        raise ValueError(f"gh auth token failed: {result.stderr.strip()}")
    token = result.stdout.strip()
    if not token:
        raise ValueError("gh auth token returned empty string")
    _cached_token = token
    return token


def _get_headers() -> dict:
    return {
        "Authorization": f"Bearer {_get_token()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def clear_token_cache():
    """Clear cached token (e.g. on 401)."""
    global _cached_token
    _cached_token = None


def _get_username(client: httpx.Client) -> str:
    """Get the authenticated user's login."""
    resp = client.get(f"{GITHUB_API_BASE}/user", headers=_get_headers())
    resp.raise_for_status()
    return resp.json()["login"]


def _fetch_prs(client: httpx.Client, params: dict, limit: int) -> list[dict]:
    """Fetch PRs with pagination up to limit."""
    all_prs = []
    page = 1
    per_page = min(limit, 100)
    while len(all_prs) < limit:
        resp = client.get(
            f"{GITHUB_API_BASE}/repos/{get_github_repo()}/pulls",
            headers=_get_headers(),
            params={**params, "per_page": per_page, "page": page},
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        all_prs.extend(batch)
        if len(batch) < per_page:
            break
        page += 1
    return all_prs[:limit]


def _pr_to_row(pr: dict, review_requested: bool) -> tuple:
    """Convert GitHub API PR dict to a DB row tuple."""
    return (
        pr["id"],
        pr["number"],
        pr["title"],
        "merged" if pr.get("merged_at") else pr["state"],
        int(pr.get("draft", False)),
        pr["user"]["login"],
        pr["html_url"],
        pr["created_at"],
        pr["updated_at"],
        pr.get("merged_at"),
        pr["head"]["ref"],
        pr["base"]["ref"],
        json.dumps([label["name"] for label in pr.get("labels", [])]),
        json.dumps([r["login"] for r in pr.get("requested_reviewers", [])]),
        int(review_requested),
        pr.get("additions"),
        pr.get("deletions"),
        pr.get("changed_files"),
        (pr.get("body") or "")[:500],
    )


def sync_github_prs() -> int:
    """Sync open PRs from the configured GitHub repo. Returns count of PRs synced."""
    repo = get_github_repo()
    if not repo:
        raise ValueError("No GitHub repo configured. Set github_repo in your profile or GITHUB_REPO env var.")

    # Phase 1: Fetch all data from GitHub API (no DB connection held)
    with httpx.Client(timeout=30) as client:
        # Get authenticated username
        username = _get_username(client)

        # 1. PRs where user is a requested reviewer (via search API)
        review_resp = client.get(
            f"{GITHUB_API_BASE}/search/issues",
            headers=_get_headers(),
            params={
                "q": f"is:pr is:open review-requested:{username} repo:{get_github_repo()}",
                "per_page": GITHUB_PR_SYNC_LIMIT,
            },
        )
        review_resp.raise_for_status()
        review_numbers = {item["number"] for item in review_resp.json().get("items", [])}

        # 2. All open PRs (for general visibility)
        open_prs = _fetch_prs(
            client,
            {"state": "open", "sort": "updated", "direction": "desc"},
            GITHUB_PR_SYNC_LIMIT,
        )

        # 3. Recently merged PRs (for context)
        closed_prs = _fetch_prs(
            client,
            {"state": "closed", "sort": "updated", "direction": "desc"},
            20,
        )
        merged_prs = [p for p in closed_prs if p.get("merged_at")]

    # Deduplicate by PR id
    seen = set()
    all_rows = []
    for pr in open_prs + merged_prs:
        if pr["id"] not in seen:
            seen.add(pr["id"])
            is_review = pr["number"] in review_numbers or username in [
                r["login"] for r in pr.get("requested_reviewers", [])
            ]
            all_rows.append(_pr_to_row(pr, is_review))

    # Phase 2: Write in batches
    with get_write_db() as db:
        batch_upsert(
            db,
            """INSERT OR REPLACE INTO github_pull_requests
               (id, number, title, state, draft, author, html_url, created_at, updated_at,
                merged_at, head_ref, base_ref, labels_json,
                requested_reviewers_json, review_requested,
                additions, deletions, changed_files, body_preview)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            all_rows,
        )

    return len(all_rows)
