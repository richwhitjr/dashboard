"""Live Notion API endpoints for search and page reading."""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app_config import get_prompt_context, get_secret
from database import get_db_connection, get_write_db
from models import NotionBlockAppend, NotionPageCreate, NotionPageUpdate
from routers._ranking_cache import compute_items_hash
from utils.notion_blocks import blocks_to_text

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notion", tags=["notion"])


def _iso_cutoff(days: int) -> str:
    """Return ISO datetime string for N days ago."""
    return (datetime.utcnow() - timedelta(days=days)).isoformat()


NOTION_API_BASE = "https://api.notion.com/v1"


def _get_headers() -> dict:
    token = get_secret("NOTION_TOKEN") or os.environ.get("NOTION_TOKEN", "")
    if not token:
        raise HTTPException(status_code=503, detail="NOTION_TOKEN not configured")
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }


def _extract_title(page: dict) -> str:
    props = page.get("properties", {})
    for prop in props.values():
        if prop.get("type") == "title":
            title_parts = prop.get("title", [])
            return "".join(t.get("plain_text", "") for t in title_parts)
    return "Untitled"


_blocks_to_text = blocks_to_text  # backwards compat for internal use


@router.get("/all")
def get_all_notion(
    offset: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
    q: str | None = Query(None, description="Text search on title, editor, snippet"),
    author: str | None = Query(None, description="Filter by last editor name"),
    from_date: str | None = Query(None, description="ISO date string, e.g. 2026-01-01"),
    to_date: str | None = Query(None, description="ISO date string, inclusive"),
):
    """Return all synced Notion pages, newest first, with pagination and optional search."""
    conditions: list[str] = []
    params: list = []

    if q:
        like = f"%{q}%"
        conditions.append("(title LIKE ? OR last_edited_by LIKE ? OR snippet LIKE ?)")
        params.extend([like, like, like])
    if author:
        conditions.append("last_edited_by LIKE ?")
        params.append(f"%{author}%")
    if from_date:
        conditions.append("last_edited_time >= ?")
        params.append(from_date)
    if to_date:
        conditions.append("last_edited_time <= ?")
        params.append(to_date + "T23:59:59")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            f"SELECT id, title, url, last_edited_time, last_edited_by, snippet "
            f"FROM notion_pages {where} ORDER BY last_edited_time DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        total = db.execute(f"SELECT COUNT(*) as c FROM notion_pages {where}", params).fetchone()["c"]
    return {
        "items": [dict(r) for r in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < total,
    }


@router.get("/search")
def search_notion(
    q: Optional[str] = Query(None, description="Search query text"),
    filter_type: Optional[str] = Query(None, description="Filter by 'page' or 'database'"),
    page_size: int = Query(10, ge=1, le=100),
):
    """Search Notion pages and databases."""
    import httpx

    headers = _get_headers()
    body: dict = {"page_size": page_size, "sort": {"direction": "descending", "timestamp": "last_edited_time"}}
    if q:
        body["query"] = q
    if filter_type in ("page", "database"):
        body["filter"] = {"value": filter_type, "property": "object"}

    try:
        with httpx.Client() as client:
            resp = client.post(f"{NOTION_API_BASE}/search", headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.error("Notion search failed: %s", e)
        raise HTTPException(status_code=500, detail="Notion search failed")

    results = []
    for item in data.get("results", []):
        icon = ""
        if item.get("icon"):
            icon_obj = item["icon"]
            if icon_obj.get("type") == "emoji":
                icon = icon_obj.get("emoji", "")

        results.append(
            {
                "id": item["id"],
                "object": item.get("object", ""),
                "title": (
                    _extract_title(item)
                    if item.get("object") == "page"
                    else item.get("title", [{}])[0].get("plain_text", "")
                    if item.get("title")
                    else "Untitled"
                ),
                "url": item.get("url", ""),
                "icon": icon,
                "last_edited_time": item.get("last_edited_time", ""),
                "created_time": item.get("created_time", ""),
            }
        )

    return {"query": q, "count": len(results), "results": results}


@router.get("/pages/{page_id}")
def get_page(page_id: str):
    """Get page properties."""
    import httpx

    headers = _get_headers()
    try:
        with httpx.Client() as client:
            resp = client.get(f"{NOTION_API_BASE}/pages/{page_id}", headers=headers)
            resp.raise_for_status()
            page = resp.json()
    except Exception as e:
        logger.error("Notion page not found: %s", e)
        raise HTTPException(status_code=404, detail="Page not found")

    # Extract all properties into readable format
    properties = {}
    for name, prop in page.get("properties", {}).items():
        ptype = prop.get("type", "")
        if ptype == "title":
            properties[name] = "".join(t.get("plain_text", "") for t in prop.get("title", []))
        elif ptype == "rich_text":
            properties[name] = "".join(t.get("plain_text", "") for t in prop.get("rich_text", []))
        elif ptype == "number":
            properties[name] = prop.get("number")
        elif ptype == "select":
            properties[name] = prop.get("select", {}).get("name", "") if prop.get("select") else None
        elif ptype == "multi_select":
            properties[name] = [s.get("name", "") for s in prop.get("multi_select", [])]
        elif ptype == "date":
            properties[name] = prop.get("date", {}).get("start", "") if prop.get("date") else None
        elif ptype == "checkbox":
            properties[name] = prop.get("checkbox", False)
        elif ptype == "url":
            properties[name] = prop.get("url", "")
        elif ptype == "email":
            properties[name] = prop.get("email", "")
        elif ptype == "status":
            properties[name] = prop.get("status", {}).get("name", "") if prop.get("status") else None
        elif ptype == "people":
            properties[name] = [p.get("name", "") for p in prop.get("people", [])]
        elif ptype == "relation":
            properties[name] = [r.get("id", "") for r in prop.get("relation", [])]
        else:
            properties[name] = f"[{ptype}]"

    icon = ""
    if page.get("icon"):
        icon_obj = page["icon"]
        if icon_obj.get("type") == "emoji":
            icon = icon_obj.get("emoji", "")

    return {
        "id": page["id"],
        "url": page.get("url", ""),
        "icon": icon,
        "created_time": page.get("created_time", ""),
        "last_edited_time": page.get("last_edited_time", ""),
        "properties": properties,
    }


@router.get("/pages/{page_id}/content")
def get_page_content(page_id: str):
    """Get page content as readable text (all blocks)."""
    import httpx

    headers = _get_headers()
    all_blocks = []

    try:
        with httpx.Client() as client:
            cursor = None
            while True:
                url = f"{NOTION_API_BASE}/blocks/{page_id}/children"
                params = {"page_size": 100}
                if cursor:
                    params["start_cursor"] = cursor
                resp = client.get(url, headers=headers, params=params)
                resp.raise_for_status()
                data = resp.json()
                all_blocks.extend(data.get("results", []))
                if not data.get("has_more"):
                    break
                cursor = data.get("next_cursor")
    except Exception as e:
        logger.error("Notion page content not found: %s", e)
        raise HTTPException(status_code=404, detail="Page content not found")

    text = _blocks_to_text(all_blocks)
    return {
        "page_id": page_id,
        "block_count": len(all_blocks),
        "content": text,
    }


# --- Write endpoints ---


@router.post("/pages")
def create_page(page: NotionPageCreate):
    """Create a new Notion page."""
    import httpx

    headers = _get_headers()
    body: dict = {
        "parent": {page.parent_type: page.parent_id},
        "properties": {
            "title": {"title": [{"text": {"content": page.title}}]},
            **(page.properties or {}),
        },
    }

    try:
        with httpx.Client() as client:
            resp = client.post(f"{NOTION_API_BASE}/pages", headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.error("Failed to create Notion page: %s", e)
        raise HTTPException(status_code=500, detail="Failed to create Notion page")

    return {"id": data["id"], "url": data.get("url", ""), "title": page.title}


@router.patch("/pages/{page_id}/properties")
def update_page_properties(page_id: str, update: NotionPageUpdate):
    """Update properties on a Notion page."""
    import httpx

    headers = _get_headers()
    try:
        with httpx.Client() as client:
            resp = client.patch(
                f"{NOTION_API_BASE}/pages/{page_id}",
                headers=headers,
                json={"properties": update.properties},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.error("Failed to update Notion page: %s", e)
        raise HTTPException(status_code=500, detail="Failed to update Notion page")
    return {"id": data["id"], "url": data.get("url", "")}


@router.post("/pages/{page_id}/blocks")
def append_blocks(page_id: str, body: NotionBlockAppend):
    """Append content blocks to a Notion page."""
    import httpx

    headers = _get_headers()

    blocks = body.blocks or []
    if body.text and not blocks:
        blocks = [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": body.text}}]},
            }
        ]

    if not blocks:
        raise HTTPException(status_code=400, detail="Provide either 'blocks' or 'text'")

    try:
        with httpx.Client() as client:
            resp = client.patch(
                f"{NOTION_API_BASE}/blocks/{page_id}/children",
                headers=headers,
                json={"children": blocks},
            )
            resp.raise_for_status()
    except Exception as e:
        logger.error("Failed to append blocks: %s", e)
        raise HTTPException(status_code=500, detail="Failed to append blocks")
    return {"page_id": page_id, "blocks_added": len(blocks)}


@router.delete("/pages/{page_id}")
def archive_page(page_id: str):
    """Archive (soft-delete) a Notion page."""
    import httpx

    headers = _get_headers()
    try:
        with httpx.Client() as client:
            resp = client.patch(
                f"{NOTION_API_BASE}/pages/{page_id}",
                headers=headers,
                json={"archived": True},
            )
            resp.raise_for_status()
    except Exception as e:
        logger.error("Failed to archive Notion page: %s", e)
        raise HTTPException(status_code=500, detail="Failed to archive page")
    return {"ok": True, "page_id": page_id, "archived": True}


# --- Gemini-ranked Notion pages ---


def _build_notion_rank_prompt() -> str:
    ctx = get_prompt_context()
    return f"""\
You are a priority-ranking assistant {ctx}. You will receive a list of \
recently edited Notion pages. Your job is to rank them by importance/relevance for the user.

For each page, assign a priority_score from 1-10 where:
- 10: Critical docs the user needs to review now (active project specs, decisions pending, launch docs)
- 7-9: High priority (roadmaps, team docs being actively worked on, meeting notes from key meetings)
- 4-6: Medium (reference docs, process pages, templates being updated)
- 1-3: Low (old/stale pages, personal notes from others, automated/bot edits)

Consider:
1. Pages edited very recently are more relevant
2. Pages the user edited themselves are high priority (their active work)
3. Product specs, roadmaps, and strategy docs are important
4. Meeting notes and 1:1 docs are valuable context
5. Pages with relevance reasons indicating the user's involvement score higher

Return ONLY valid JSON — an array of objects with keys: id, priority_score, reason (one short sentence).
Order by priority_score descending. Return ALL pages provided, scored."""


def _rank_notion_with_gemini(pages: list[dict]) -> list[dict]:
    """Rank Notion pages by priority using the configured AI provider."""
    from ai_client import generate

    now = datetime.now().strftime("%A, %B %d %Y, %I:%M %p")
    user_message = f"Current time: {now}\n\nNotion pages to rank:\n{json.dumps(pages, default=str)}"

    text = generate(system_prompt=_build_notion_rank_prompt(), user_message=user_message, json_mode=True)
    if not text:
        return []

    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def _dismissed_notion_ids(db) -> set[str]:
    rows = db.execute("SELECT item_id FROM dismissed_dashboard_items WHERE source = 'notion'").fetchall()
    return {r["item_id"] for r in rows}


def rerank_notion(days: int = 7) -> bool:
    """Rerank Notion items — updates cache if data changed. Returns True if cache was updated."""
    from routers._ranking_cache import finish_reranking, start_reranking

    if not start_reranking("notion"):
        return False
    try:
        return _do_rerank_notion(days)
    finally:
        finish_reranking("notion")


def _do_rerank_notion(days: int = 7) -> bool:
    cutoff = f"-{days} days"
    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            "SELECT id, title, url, last_edited_time, last_edited_by, snippet, "
            "relevance_score, relevance_reason "
            "FROM notion_pages "
            "WHERE last_edited_time >= datetime('now', ?) "
            "ORDER BY last_edited_time DESC LIMIT 100",
            (cutoff,),
        ).fetchall()

    if not rows:
        return False

    pages_for_llm = [
        {
            "id": r["id"],
            "title": r["title"],
            "last_edited_time": r["last_edited_time"],
            "last_edited_by": r["last_edited_by"],
            "snippet": (r["snippet"] or "")[:300],
            "relevance_reason": r["relevance_reason"],
        }
        for r in rows
    ]

    items_hash = compute_items_hash(pages_for_llm)
    with get_db_connection(readonly=True) as db:
        cached = db.execute("SELECT data_hash FROM cached_notion_priorities ORDER BY id DESC LIMIT 1").fetchone()
        if cached and cached["data_hash"] == items_hash:
            return False

    logger.info("Notion rerank — calling AI (%d pages)", len(pages_for_llm))
    try:
        ranked = _rank_notion_with_gemini(pages_for_llm)
    except Exception as e:
        logger.error("Notion rerank failed: %s", e)
        return False

    page_lookup = {r["id"]: dict(r) for r in rows}
    items = []
    for rank in ranked:
        page_id = rank.get("id", "")
        page = page_lookup.get(page_id)
        if not page:
            continue
        items.append(
            {
                "id": page["id"],
                "title": page["title"],
                "url": page["url"],
                "last_edited_time": page["last_edited_time"],
                "last_edited_by": page["last_edited_by"],
                "snippet": page["snippet"],
                "relevance_reason": page["relevance_reason"],
                "priority_score": rank.get("priority_score", 5),
                "priority_reason": rank.get("reason", ""),
            }
        )

    items.sort(key=lambda x: x["priority_score"], reverse=True)
    items = items[:50]

    if not items:
        logger.warning("Notion rerank produced 0 items — not caching empty result")
        return False

    result = {"items": items}

    with get_write_db() as db:
        db.execute("DELETE FROM cached_notion_priorities")
        db.execute(
            "INSERT INTO cached_notion_priorities (data_json, data_hash) VALUES (?, ?)",
            (json.dumps(result), items_hash),
        )
        db.commit()

    logger.info("Notion rerank complete — %d items cached", len(items))
    return True


@router.get("/prioritized")
def get_prioritized_notion(
    refresh: bool = Query(False),
    days: int = Query(7, ge=1, le=90),
    background_tasks: BackgroundTasks = None,
):
    """Return top 50 Notion pages ranked by Gemini priority score."""
    from routers._ranking_cache import is_reranking

    with get_db_connection(readonly=True) as db:
        dismissed = _dismissed_notion_ids(db)
        cached = db.execute(
            "SELECT data_json, generated_at FROM cached_notion_priorities ORDER BY id DESC LIMIT 1"
        ).fetchone()

    if cached:
        data = json.loads(cached["data_json"])
        data["items"] = [
            item
            for item in data.get("items", [])
            if item["id"] not in dismissed and (item.get("last_edited_time") or "") >= _iso_cutoff(days)
        ]

        if not refresh:
            return data

        if background_tasks and not is_reranking("notion"):
            background_tasks.add_task(rerank_notion, days)
        data["stale"] = True
        return data

    # No cache — synchronous first-time ranking
    result = _do_rerank_notion(days)
    if not result:
        return {"items": [], "error": "No Notion pages synced yet"}

    with get_db_connection(readonly=True) as db:
        cached = db.execute("SELECT data_json FROM cached_notion_priorities ORDER BY id DESC LIMIT 1").fetchone()
        if cached:
            data = json.loads(cached["data_json"])
            data["items"] = [
                item
                for item in data.get("items", [])
                if item["id"] not in dismissed and (item.get("last_edited_time") or "") >= _iso_cutoff(days)
            ]
            return data

    return {"items": []}
