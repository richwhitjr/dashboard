"""Live GitHub API endpoints for PR browsing and repo search."""

import logging
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

from config import get_github_repo
from database import get_db_connection

router = APIRouter(prefix="/api/github", tags=["github"])

GITHUB_API_BASE = "https://api.github.com"


def _require_repo() -> str:
    """Return the configured repo or raise 400 if not set."""
    repo = get_github_repo()
    if not repo:
        raise HTTPException(
            status_code=400,
            detail="No GitHub repo configured. Set github_repo in your profile settings.",
        )
    return repo


def _get_headers() -> dict:
    """Get auth headers. Raises HTTPException(503) if gh CLI not authenticated."""
    try:
        from connectors.github import _get_headers as gh_headers

        return gh_headers()
    except Exception as e:
        logger.error("GitHub auth not available: %s", e)
        raise HTTPException(status_code=503, detail="GitHub auth not available")


def _parse_pr(pr: dict) -> dict:
    """Normalize a PR from the GitHub API into our response format."""
    return {
        "number": pr["number"],
        "title": pr["title"],
        "state": "merged" if pr.get("pull_request", {}).get("merged_at") or pr.get("merged_at") else pr["state"],
        "draft": pr.get("draft", False),
        "author": pr.get("user", {}).get("login", ""),
        "html_url": pr.get("html_url", ""),
        "created_at": pr.get("created_at", ""),
        "updated_at": pr.get("updated_at", ""),
        "merged_at": pr.get("merged_at") or pr.get("pull_request", {}).get("merged_at"),
        "head_ref": pr.get("head", {}).get("ref", ""),
        "base_ref": pr.get("base", {}).get("ref", ""),
        "labels": [lb["name"] for lb in pr.get("labels", [])],
        "requested_reviewers": [r["login"] for r in pr.get("requested_reviewers", [])],
        "review_requested": False,
    }


def _parse_search_item(item: dict) -> dict:
    """Normalize a search result item (issue-shaped)."""
    is_pr = "pull_request" in item
    return {
        "number": item["number"],
        "title": item["title"],
        "type": "pr" if is_pr else "issue",
        "state": "merged" if is_pr and item.get("pull_request", {}).get("merged_at") else item["state"],
        "author": item.get("user", {}).get("login", ""),
        "html_url": item.get("html_url", ""),
        "created_at": item.get("created_at", ""),
        "updated_at": item.get("updated_at", ""),
        "labels": [lb["name"] for lb in item.get("labels", [])],
        "comments": item.get("comments", 0),
    }


def _filter_dismissed(items: list[dict]) -> list[dict]:
    """Remove dismissed GitHub items."""
    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            "SELECT item_id FROM dismissed_dashboard_items WHERE source = 'github'"
        ).fetchall()
        dismissed = {r["item_id"] for r in rows}
    return [i for i in items if str(i["number"]) not in dismissed]


@router.get("/all")
def get_all_github_prs(
    offset: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
):
    """Return all synced GitHub PRs from local DB, newest first, with pagination."""
    import json as _json

    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            "SELECT * FROM github_pull_requests ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        total = db.execute(
            "SELECT COUNT(*) as c FROM github_pull_requests"
        ).fetchone()["c"]

    items = []
    for r in rows:
        d = dict(r)
        d["labels"] = _json.loads(d.pop("labels_json", "[]") or "[]")
        d["requested_reviewers"] = _json.loads(
            d.pop("requested_reviewers_json", "[]") or "[]"
        )
        d["draft"] = bool(d.get("draft"))
        d["review_requested"] = bool(d.get("review_requested"))
        items.append(d)

    return {
        "items": items,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < total,
    }


@router.get("/pulls")
def list_pulls(
    state: str = Query("open", description="PR state: open, closed, all"),
    review_requested: bool = Query(False, description="Only PRs requesting your review"),
    author: Optional[str] = Query(None, description="Filter by author login"),
    sort: str = Query("updated", description="Sort: created, updated, popularity"),
    direction: str = Query("desc", description="Sort direction: asc, desc"),
    per_page: int = Query(30, ge=1, le=100),
    page: int = Query(1, ge=1),
):
    """List pull requests with optional filters."""
    headers = _get_headers()

    try:
        with httpx.Client(timeout=30) as client:
            if review_requested:
                # Use search API to find review-requested PRs
                from connectors.github import _get_username

                username = _get_username(client)
                q_parts = [f"is:pr is:open review-requested:{username} repo:{_require_repo()}"]
                if author:
                    q_parts.append(f"author:{author}")
                resp = client.get(
                    f"{GITHUB_API_BASE}/search/issues",
                    headers=headers,
                    params={
                        "q": " ".join(q_parts),
                        "per_page": per_page,
                        "page": page,
                        "sort": sort if sort != "popularity" else "reactions",
                        "order": direction,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                items = [_parse_search_item(i) for i in data.get("items", [])]
                for item in items:
                    item["review_requested"] = True
                items = _filter_dismissed(items)
                return {"total": data.get("total_count", 0), "count": len(items), "pulls": items}
            else:
                # Use list PRs endpoint
                params: dict = {
                    "state": state,
                    "sort": sort if sort in ("created", "updated", "popularity", "long-running") else "updated",
                    "direction": direction,
                    "per_page": per_page,
                    "page": page,
                }
                resp = client.get(
                    f"{GITHUB_API_BASE}/repos/{_require_repo()}/pulls",
                    headers=headers,
                    params=params,
                )
                resp.raise_for_status()
                prs = resp.json()
                if author:
                    prs = [p for p in prs if p.get("user", {}).get("login") == author]
                pulls = _filter_dismissed([_parse_pr(p) for p in prs])
                return {"total": len(pulls), "count": len(pulls), "pulls": pulls}
    except httpx.HTTPStatusError as e:
        logger.error("GitHub API error: %s", e.response.text[:500])
        raise HTTPException(status_code=e.response.status_code, detail="GitHub API error")
    except Exception as e:
        logger.error("GitHub request failed: %s", e)
        raise HTTPException(status_code=500, detail="GitHub request failed")


@router.get("/pulls/{number}")
def get_pull(number: int):
    """Get detailed information about a single pull request."""
    headers = _get_headers()

    try:
        with httpx.Client(timeout=30) as client:
            # Fetch PR detail (includes additions/deletions/changed_files)
            pr_resp = client.get(
                f"{GITHUB_API_BASE}/repos/{_require_repo()}/pulls/{number}",
                headers=headers,
            )
            pr_resp.raise_for_status()
            pr = pr_resp.json()

            # Fetch reviews
            reviews_resp = client.get(
                f"{GITHUB_API_BASE}/repos/{_require_repo()}/pulls/{number}/reviews",
                headers=headers,
                params={"per_page": 50},
            )
            reviews_resp.raise_for_status()
            reviews = [
                {
                    "user": r.get("user", {}).get("login", ""),
                    "state": r.get("state", ""),
                    "submitted_at": r.get("submitted_at", ""),
                }
                for r in reviews_resp.json()
            ]

            # Fetch changed files (first 30)
            files_resp = client.get(
                f"{GITHUB_API_BASE}/repos/{_require_repo()}/pulls/{number}/files",
                headers=headers,
                params={"per_page": 30},
            )
            files_resp.raise_for_status()
            files = [
                {
                    "filename": f["filename"],
                    "status": f["status"],
                    "additions": f.get("additions", 0),
                    "deletions": f.get("deletions", 0),
                }
                for f in files_resp.json()
            ]

        result = _parse_pr(pr)
        result.update(
            {
                "body": pr.get("body") or "",
                "additions": pr.get("additions", 0),
                "deletions": pr.get("deletions", 0),
                "changed_files": pr.get("changed_files", 0),
                "files": files,
                "reviews": reviews,
                "comments": pr.get("comments", 0),
                "review_comments": pr.get("review_comments", 0),
            }
        )
        return result
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail=f"PR #{number} not found in {_require_repo()}")
        logger.error("GitHub API error: %s", e.response.text[:500])
        raise HTTPException(status_code=e.response.status_code, detail="GitHub API error")
    except Exception as e:
        logger.error("GitHub request failed: %s", e)
        raise HTTPException(status_code=500, detail="GitHub request failed")


@router.get("/search")
def search_github(
    q: str = Query(..., description="Search query (scoped to repo)"),
    type: str = Query("pr", description="Type: pr, issue, all"),
    state: Optional[str] = Query(None, description="Filter: open, closed"),
    per_page: int = Query(20, ge=1, le=100),
):
    """Search issues and pull requests in the repo."""
    headers = _get_headers()

    q_parts = [q, f"repo:{_require_repo()}"]
    if type == "pr":
        q_parts.append("is:pr")
    elif type == "issue":
        q_parts.append("is:issue")
    if state:
        q_parts.append(f"is:{state}")

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.get(
                f"{GITHUB_API_BASE}/search/issues",
                headers=headers,
                params={"q": " ".join(q_parts), "per_page": per_page},
            )
            resp.raise_for_status()
            data = resp.json()
            items = [_parse_search_item(i) for i in data.get("items", [])]
            return {
                "query": q,
                "total": data.get("total_count", 0),
                "count": len(items),
                "items": items,
            }
    except httpx.HTTPStatusError as e:
        logger.error("GitHub search failed: %s", e.response.text[:500])
        raise HTTPException(status_code=e.response.status_code, detail="GitHub search failed")
    except Exception as e:
        logger.error("GitHub search failed: %s", e)
        raise HTTPException(status_code=500, detail="GitHub search failed")


@router.get("/search/code")
def search_code(
    q: str = Query(..., description="Code search query"),
    per_page: int = Query(20, ge=1, le=50),
):
    """Search code in the repo."""
    headers = _get_headers()
    # Use text-match accept header for highlighted fragments
    headers["Accept"] = "application/vnd.github.text-match+json"

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.get(
                f"{GITHUB_API_BASE}/search/code",
                headers=headers,
                params={
                    "q": f"{q} repo:{_require_repo()}",
                    "per_page": per_page,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            items = [
                {
                    "name": item["name"],
                    "path": item["path"],
                    "html_url": item["html_url"],
                    "text_matches": [{"fragment": tm.get("fragment", "")} for tm in item.get("text_matches", [])],
                }
                for item in data.get("items", [])
            ]
            return {
                "query": q,
                "total": data.get("total_count", 0),
                "count": len(items),
                "items": items,
            }
    except httpx.HTTPStatusError as e:
        logger.error("GitHub code search failed: %s", e.response.text[:500])
        raise HTTPException(status_code=e.response.status_code, detail="GitHub code search failed")
    except Exception as e:
        logger.error("GitHub code search failed: %s", e)
        raise HTTPException(status_code=500, detail="GitHub code search failed")
