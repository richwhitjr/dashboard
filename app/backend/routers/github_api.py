"""Live GitHub API endpoints for PR browsing and repo search."""

from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query

from config import get_github_repo

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
        raise HTTPException(status_code=503, detail=f"GitHub auth not available: {e}")


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
                pulls = [_parse_pr(p) for p in prs]
                return {"total": len(pulls), "count": len(pulls), "pulls": pulls}
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"GitHub API error: {e.response.text[:500]}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"GitHub request failed: {e}")


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
        raise HTTPException(status_code=e.response.status_code, detail=f"GitHub API error: {e.response.text[:500]}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"GitHub request failed: {e}")


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
        raise HTTPException(status_code=e.response.status_code, detail=f"GitHub search failed: {e.response.text[:500]}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"GitHub search failed: {e}")


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
        detail = f"GitHub code search failed: {e.response.text[:500]}"
        raise HTTPException(status_code=e.response.status_code, detail=detail)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"GitHub code search failed: {e}")
