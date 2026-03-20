"""Live GitHub API endpoints for PR browsing and repo search."""

import json
import logging
from datetime import datetime
from typing import Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app_config import get_prompt_context
from config import get_github_repo
from database import get_db_connection, get_write_db
from routers._ranking_cache import compute_items_hash

logger = logging.getLogger(__name__)

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
        rows = db.execute("SELECT item_id FROM dismissed_dashboard_items WHERE source = 'github'").fetchall()
        dismissed = {r["item_id"] for r in rows}
    return [i for i in items if str(i["number"]) not in dismissed]


@router.get("/all")
def get_all_github_prs(
    offset: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
    q: str | None = Query(None, description="Text search on title or author"),
    author: str | None = Query(None, description="Filter by PR author"),
    from_date: str | None = Query(None, description="ISO date string, e.g. 2026-01-01"),
    to_date: str | None = Query(None, description="ISO date string, inclusive"),
):
    """Return all synced GitHub PRs from local DB, newest first, with pagination and optional search."""
    import json as _json

    conditions: list[str] = []
    params: list = []

    if q:
        like = f"%{q}%"
        conditions.append("(title LIKE ? OR author LIKE ?)")
        params.extend([like, like])
    if author:
        conditions.append("author LIKE ?")
        params.append(f"%{author}%")
    if from_date:
        conditions.append("updated_at >= ?")
        params.append(from_date)
    if to_date:
        conditions.append("updated_at <= ?")
        params.append(to_date + "T23:59:59")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            f"SELECT * FROM github_pull_requests {where} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        total = db.execute(f"SELECT COUNT(*) as c FROM github_pull_requests {where}", params).fetchone()["c"]

    items = []
    for r in rows:
        d = dict(r)
        d["labels"] = _json.loads(d.pop("labels_json", "[]") or "[]")
        d["requested_reviewers"] = _json.loads(d.pop("requested_reviewers_json", "[]") or "[]")
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


# ---------------------------------------------------------------------------
# AI prioritization
# ---------------------------------------------------------------------------


def _build_github_rank_prompt() -> str:
    ctx = get_prompt_context()
    return f"""\
You are a priority-ranking assistant {ctx}. You will receive a list of open \
GitHub pull requests. Your job is to rank them by importance for the user to act on.

For each PR, assign a priority_score from 1-10 where:
- 10: Needs immediate attention (review explicitly requested from user, hotfix/production PRs)
- 8-9: High priority (from direct reports or executives, critical/blocking labels, PRs awaiting your approval)
- 5-7: Medium priority (active discussion, recently updated feature PRs with engagement)
- 1-4: Low priority (draft PRs, dormant PRs, bot-authored PRs like dependabot/renovate, docs-only changes)

Consider:
1. Review-requested PRs addressed to the user are highest priority
2. PRs authored by direct reports or executives matter more
3. Labels like "critical", "blocking", "hotfix", "p0" signal urgency
4. Draft PRs are almost always low priority
5. Bot-authored PRs (dependabot, renovate, etc.) are low unless they are security updates
6. Recency: recently updated PRs are more actionable than dormant ones

Return ONLY valid JSON — an array of objects with these keys:
  id (the PR number as a string), priority_score (integer 1-10), reason (one short sentence)
Order by priority_score descending. Include ALL PRs provided."""


def _rank_github_with_gemini(prs: list[dict]) -> list[dict]:
    from ai_client import generate

    now = datetime.now().strftime("%A, %B %d %Y, %I:%M %p")
    user_message = f"Current time: {now}\n\nGitHub PRs to rank:\n{json.dumps(prs, default=str)}"
    text = generate(system_prompt=_build_github_rank_prompt(), user_message=user_message, json_mode=True)
    if not text:
        return []
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def _do_rerank_github() -> bool:
    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            "SELECT number, title, state, draft, author, html_url, head_ref, base_ref, "
            "labels_json, requested_reviewers_json, review_requested, "
            "additions, deletions, changed_files, updated_at "
            "FROM github_pull_requests WHERE state = 'open' ORDER BY updated_at DESC LIMIT 100"
        ).fetchall()

    if not rows:
        logger.info("GitHub rerank — no open PRs in DB")
        return False

    prs_for_llm = []
    for r in rows:
        prs_for_llm.append(
            {
                "id": str(r["number"]),
                "title": r["title"],
                "author": r["author"],
                "draft": bool(r["draft"]),
                "head_ref": r["head_ref"],
                "base_ref": r["base_ref"],
                "labels": json.loads(r["labels_json"] or "[]"),
                "requested_reviewers": json.loads(r["requested_reviewers_json"] or "[]"),
                "review_requested": bool(r["review_requested"]),
                "additions": r["additions"],
                "deletions": r["deletions"],
                "changed_files": r["changed_files"],
                "updated_at": r["updated_at"],
            }
        )

    items_hash = compute_items_hash(prs_for_llm)
    with get_db_connection(readonly=True) as db:
        cached = db.execute("SELECT data_hash FROM cached_github_priorities ORDER BY id DESC LIMIT 1").fetchone()
        if cached and cached["data_hash"] == items_hash:
            logger.info("GitHub rerank — cache still valid")
            return False

    logger.info("GitHub rerank — calling AI (%d PRs)", len(prs_for_llm))
    try:
        ranked = _rank_github_with_gemini(prs_for_llm)
    except Exception as e:
        logger.error("GitHub rerank failed: %s", e)
        return False

    pr_lookup = {str(r["number"]): dict(r) for r in rows}
    items = []
    for rank in ranked:
        pr_id = str(rank.get("id", ""))
        pr = pr_lookup.get(pr_id)
        if not pr:
            continue
        items.append(
            {
                "id": pr_id,
                "number": int(pr_id),
                "title": pr["title"],
                "author": pr["author"],
                "draft": bool(pr["draft"]),
                "head_ref": pr["head_ref"],
                "base_ref": pr["base_ref"],
                "labels": json.loads(pr["labels_json"] or "[]"),
                "requested_reviewers": json.loads(pr["requested_reviewers_json"] or "[]"),
                "review_requested": bool(pr["review_requested"]),
                "updated_at": pr["updated_at"],
                "html_url": pr["html_url"],
                "priority_score": rank.get("priority_score", 5),
                "priority_reason": rank.get("reason", ""),
            }
        )

    items.sort(key=lambda x: x["priority_score"], reverse=True)

    if not items:
        logger.warning("GitHub rerank produced 0 items — not caching")
        return False

    result = {"items": items}
    with get_write_db() as db:
        db.execute("DELETE FROM cached_github_priorities")
        db.execute(
            "INSERT INTO cached_github_priorities (data_json, data_hash) VALUES (?, ?)",
            (json.dumps(result), items_hash),
        )
        db.commit()

    logger.info("GitHub rerank complete — %d items cached", len(items))
    return True


def rerank_github() -> bool:
    """Rerank GitHub PRs — updates cache if data changed. Returns True if cache was updated."""
    from routers._ranking_cache import finish_reranking, start_reranking

    if not start_reranking("github"):
        return False
    try:
        return _do_rerank_github()
    finally:
        finish_reranking("github")


@router.get("/prioritized")
def get_prioritized_github(
    refresh: bool = Query(False),
    background_tasks: BackgroundTasks = None,
):
    """Return open GitHub PRs ranked by AI priority score (0-10)."""
    from routers._ranking_cache import is_reranking

    with get_db_connection(readonly=True) as db:
        dismissed_rows = db.execute("SELECT item_id FROM dismissed_dashboard_items WHERE source = 'github'").fetchall()
        dismissed = {r["item_id"] for r in dismissed_rows}
        cached = db.execute(
            "SELECT data_json, generated_at FROM cached_github_priorities ORDER BY id DESC LIMIT 1"
        ).fetchone()

    if cached:
        data = json.loads(cached["data_json"])
        data["items"] = [item for item in data.get("items", []) if str(item.get("number", "")) not in dismissed]

        if not refresh:
            return data

        # Stale-while-revalidate: return current cache, rerank in background
        if background_tasks and not is_reranking("github"):
            background_tasks.add_task(rerank_github)
        data["stale"] = True
        return data

    # No cache — synchronous first-time ranking
    updated = _do_rerank_github()
    if not updated:
        return {"items": [], "error": "No open GitHub PRs synced yet. Run a sync first."}

    with get_db_connection(readonly=True) as db:
        cached = db.execute("SELECT data_json FROM cached_github_priorities ORDER BY id DESC LIMIT 1").fetchone()
        if cached:
            data = json.loads(cached["data_json"])
            data["items"] = [i for i in data.get("items", []) if str(i.get("number", "")) not in dismissed]
            return data

    return {"items": []}
