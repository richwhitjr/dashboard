"""Live Notion API endpoints for search and page reading."""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app_config import get_prompt_context, get_secret
from database import get_db_connection, get_write_db
from utils.notion_blocks import blocks_to_text

router = APIRouter(prefix="/api/notion", tags=["notion"])


def _iso_cutoff(days: int) -> str:
    """Return ISO datetime string for N days ago."""
    return (datetime.utcnow() - timedelta(days=days)).isoformat()


NOTION_API_BASE = "https://api.notion.com/v1"


def _get_headers() -> dict:
    token = os.environ.get("NOTION_TOKEN", "")
    if not token:
        env_path = Path(__file__).parent.parent / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("NOTION_TOKEN="):
                    token = line.split("=", 1)[1].strip().strip('"')
                    break
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
        raise HTTPException(status_code=500, detail=f"Notion search failed: {e}")

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
        raise HTTPException(status_code=404, detail=f"Page not found: {e}")

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
                url = f"{NOTION_API_BASE}/blocks/{page_id}/children?page_size=100"
                if cursor:
                    url += f"&start_cursor={cursor}"
                resp = client.get(url, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                all_blocks.extend(data.get("results", []))
                if not data.get("has_more"):
                    break
                cursor = data.get("next_cursor")
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Page content not found: {e}")

    text = _blocks_to_text(all_blocks)
    return {
        "page_id": page_id,
        "block_count": len(all_blocks),
        "content": text,
    }


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
    """Call Gemini to rank Notion pages by priority."""
    api_key = get_secret("GEMINI_API_KEY") or ""
    if not api_key:
        return []

    from google import genai

    client = genai.Client(api_key=api_key)
    now = datetime.now().strftime("%A, %B %d %Y, %I:%M %p")
    user_message = f"Current time: {now}\n\nNotion pages to rank:\n{json.dumps(pages, default=str)}"

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=user_message,
        config={
            "system_instruction": _build_notion_rank_prompt(),
            "temperature": 0.2,
            "response_mime_type": "application/json",
        },
    )

    try:
        items = json.loads(response.text)
        if isinstance(items, list):
            return items
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def _dismissed_notion_ids(db) -> set[str]:
    rows = db.execute("SELECT item_id FROM dismissed_dashboard_items WHERE source = 'notion'").fetchall()
    return {r["item_id"] for r in rows}


@router.get("/prioritized")
def get_prioritized_notion(refresh: bool = Query(False), days: int = Query(7, ge=1, le=90)):
    """Return top 50 Notion pages ranked by Gemini priority score."""
    with get_db_connection(readonly=True) as db:
        dismissed = _dismissed_notion_ids(db)
        cutoff = f"-{days} days"

        # Check cache first
        if not refresh:
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
                return data

        # Fetch recent pages from DB
        rows = db.execute(
            "SELECT id, title, url, last_edited_time, last_edited_by, snippet, "
            "relevance_score, relevance_reason "
            "FROM notion_pages "
            "WHERE last_edited_time >= datetime('now', ?) "
            "ORDER BY last_edited_time DESC LIMIT 100",
            (cutoff,),
        ).fetchall()

    if not rows:
        return {"items": [], "error": "No Notion pages synced yet"}

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

    try:
        ranked = _rank_notion_with_gemini(pages_for_llm)
    except Exception as e:
        return {"items": [], "error": str(e)}

    # Build lookup of full page data
    page_lookup = {r["id"]: dict(r) for r in rows}

    # Merge rankings with full page data
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

    # Sort by score desc, filter dismissed, take top 50
    items.sort(key=lambda x: x["priority_score"], reverse=True)
    items = [i for i in items if i["id"] not in dismissed][:50]

    result = {"items": items}

    # Cache result
    with get_write_db() as db:
        db.execute("DELETE FROM cached_notion_priorities")
        db.execute(
            "INSERT INTO cached_notion_priorities (data_json) VALUES (?)",
            (json.dumps(result),),
        )
        db.commit()

    return result
