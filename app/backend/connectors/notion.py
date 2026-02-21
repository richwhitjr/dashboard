"""Notion REST API connector for recent page activity with LLM relevance scoring."""

import json
import logging
import os
from pathlib import Path

from database import get_db
from utils.notion_blocks import blocks_to_text

try:
    import httpx

    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

logger = logging.getLogger(__name__)

NOTION_API_BASE = "https://api.notion.com/v1"
SNIPPET_MAX_CHARS = 500
SNIPPET_TOP_N = 10  # Only fetch content snippets for top-scored pages


def _get_token() -> str:
    token = os.environ.get("NOTION_TOKEN", "")
    if not token:
        env_path = Path(__file__).parent.parent / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("NOTION_TOKEN="):
                    token = line.split("=", 1)[1].strip().strip('"')
                    break
    if not token:
        raise ValueError("NOTION_TOKEN not set. Add it to app/backend/.env")
    return token


def _get_headers() -> dict:
    return {
        "Authorization": f"Bearer {_get_token()}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }


def _extract_title(page: dict) -> str:
    """Extract page title from Notion page properties."""
    props = page.get("properties", {})
    for prop in props.values():
        if prop.get("type") == "title":
            title_parts = prop.get("title", [])
            return "".join(t.get("plain_text", "") for t in title_parts)
    return "Untitled"


def _fetch_page_snippet(client: "httpx.Client", headers: dict, page_id: str) -> str:
    """Fetch first blocks of a Notion page and return a text snippet."""
    try:
        resp = client.get(
            f"{NOTION_API_BASE}/blocks/{page_id}/children?page_size=20",
            headers=headers,
            timeout=10,
        )
        resp.raise_for_status()
        blocks = resp.json().get("results", [])
        text = blocks_to_text(blocks)
        return text[:SNIPPET_MAX_CHARS] if text else ""
    except Exception as e:
        logger.debug(f"Failed to fetch snippet for {page_id}: {e}")
        return ""


def _build_scoring_context(db) -> dict:
    """Gather current work context for LLM relevance scoring."""
    calendar_today = [
        dict(r)
        for r in db.execute(
            "SELECT summary, start_time, attendees_json FROM calendar_events "
            "WHERE date(start_time) = date('now') ORDER BY start_time"
        ).fetchall()
    ]

    meetings_upcoming = [
        dict(r)
        for r in db.execute(
            "SELECT summary, start_time, attendees_json FROM calendar_events "
            "WHERE start_time > datetime('now') ORDER BY start_time LIMIT 5"
        ).fetchall()
    ]

    open_notes = [
        dict(r)
        for r in db.execute(
            "SELECT text, priority, is_one_on_one FROM notes WHERE status = 'open' ORDER BY priority DESC LIMIT 15"
        ).fetchall()
    ]

    slack_recent = [
        dict(r)
        for r in db.execute(
            "SELECT user_name, text, channel_name FROM slack_messages ORDER BY ts DESC LIMIT 15"
        ).fetchall()
    ]

    emails_recent = [
        dict(r)
        for r in db.execute(
            "SELECT subject, from_name FROM emails "
            "WHERE labels_json NOT LIKE '%CATEGORY_PROMOTIONS%' "
            "AND labels_json NOT LIKE '%CATEGORY_UPDATES%' "
            "ORDER BY date DESC LIMIT 10"
        ).fetchall()
    ]

    return {
        "calendar_today": calendar_today,
        "meetings_upcoming": meetings_upcoming,
        "open_notes": open_notes,
        "slack_recent": slack_recent,
        "emails_recent": emails_recent,
    }


SCORING_PROMPT = """\
You are scoring Notion pages by relevance to Rich, the CTO of Osmo. \
Given his current work context (calendar, tasks, Slack, email) and a list of Notion pages, \
score each page from 0.0 to 1.0 for how relevant and important it is to him RIGHT NOW.

Score higher for pages that:
- Relate to today's or upcoming meetings
- Connect to open tasks or 1:1 topics
- Cover active projects or decisions being discussed in Slack/email
- Are strategic docs (roadmaps, specs, architecture) actively in use
- Were recently edited by Rich or his direct reports

Score lower for:
- Old or archived pages with no current relevance
- Personal notes from other people
- Template pages or empty stubs
- Pages about completed or inactive projects

For each page, return a short reason (max 8 words) explaining WHY it's relevant (or not).

Respond with ONLY valid JSON — an array of objects with keys: id, score, reason.
No markdown, no explanation, just the JSON array."""


SCORING_BATCH_SIZE = 75  # Pages per Gemini call to avoid output truncation


def _score_batch_with_gemini(genai_client, page_summaries: list[dict], context_str: str, now: str) -> list[dict]:
    """Score a single batch of pages with Gemini."""
    user_message = (
        f"Current time: {now}\n\n"
        f"Work context:\n{context_str}\n\n"
        f"Notion pages to score:\n{json.dumps(page_summaries, default=str)}"
    )

    response = genai_client.models.generate_content(
        model="gemini-2.0-flash",
        contents=user_message,
        config={
            "system_instruction": SCORING_PROMPT,
            "temperature": 0.2,
            "response_mime_type": "application/json",
        },
    )

    try:
        items = json.loads(response.text)
        if isinstance(items, list):
            return items
    except (json.JSONDecodeError, TypeError):
        logger.warning(f"Failed to parse Gemini scoring response: {response.text[:200]}")
    return []


def _score_with_gemini(pages: list[dict], context: dict) -> list[dict]:
    """Call Gemini to score Notion pages by relevance, batching to avoid truncation."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        logger.info("GEMINI_API_KEY not set, skipping Notion relevance scoring")
        return []

    try:
        from google import genai
    except ImportError:
        logger.info("google-genai not installed, skipping Notion relevance scoring")
        return []

    page_summaries = []
    for p in pages:
        entry = {"id": p["id"], "title": p["title"], "last_edited": p.get("last_edited_time", "")}
        if p.get("snippet"):
            entry["snippet"] = p["snippet"]
        page_summaries.append(entry)

    from datetime import datetime

    now = datetime.now().strftime("%A, %B %d %Y, %I:%M %p")
    context_str = json.dumps(context, default=str)

    client = genai.Client(api_key=api_key)

    # Batch pages to keep each Gemini call manageable
    all_scores = []
    for i in range(0, len(page_summaries), SCORING_BATCH_SIZE):
        batch = page_summaries[i : i + SCORING_BATCH_SIZE]
        batch_num = i // SCORING_BATCH_SIZE + 1
        total_batches = (len(page_summaries) + SCORING_BATCH_SIZE - 1) // SCORING_BATCH_SIZE
        logger.info(f"Scoring batch {batch_num}/{total_batches} ({len(batch)} pages)")
        try:
            scores = _score_batch_with_gemini(client, batch, context_str, now)
            all_scores.extend(scores)
        except Exception as e:
            logger.warning(f"Batch {batch_num} scoring failed: {e}")

    return all_scores


def _fetch_all_recent_pages(client: "httpx.Client", headers: dict, max_pages: int = 500) -> list[dict]:
    """Paginate through Notion search to get up to max_pages recent pages."""
    all_results = []
    cursor = None

    while len(all_results) < max_pages:
        batch_size = min(100, max_pages - len(all_results))
        body = {
            "sort": {"direction": "descending", "timestamp": "last_edited_time"},
            "page_size": batch_size,
            "filter": {"value": "page", "property": "object"},
        }
        if cursor:
            body["start_cursor"] = cursor

        resp = client.post(f"{NOTION_API_BASE}/search", headers=headers, json=body)
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        all_results.extend(results)

        if not data.get("has_more") or not data.get("next_cursor"):
            break
        cursor = data["next_cursor"]

    return all_results


def _extract_page_data(page: dict) -> dict:
    """Extract structured data from a raw Notion page object."""
    title = _extract_title(page)
    icon = ""
    if page.get("icon"):
        icon_obj = page["icon"]
        if icon_obj.get("type") == "emoji":
            icon = icon_obj.get("emoji", "")

    return {
        "id": page["id"],
        "title": title,
        "url": page.get("url", ""),
        "last_edited_time": page.get("last_edited_time", ""),
        "last_edited_by": page.get("last_edited_by", {}).get("id", ""),
        "parent_type": page.get("parent", {}).get("type", ""),
        "parent_id": page.get("parent", {}).get(page.get("parent", {}).get("type", ""), ""),
        "icon": icon,
        "snippet": "",
    }


def sync_notion_pages(limit: int = 50) -> int:
    if not HAS_HTTPX:
        raise ImportError("httpx not installed")

    headers = _get_headers()

    with httpx.Client(timeout=30) as client:
        # Phase 1: Fetch a large pool of page metadata (no content yet)
        results = _fetch_all_recent_pages(client, headers, max_pages=limit)

        # Deduplicate by title — keep the most recently edited version
        seen_titles: dict[str, dict] = {}
        for page in results:
            title = _extract_title(page)
            edited = page.get("last_edited_time", "")
            if title in seen_titles:
                existing_edited = seen_titles[title].get("last_edited_time", "")
                if edited > existing_edited:
                    seen_titles[title] = page
            else:
                seen_titles[title] = page

        unique_pages = list(seen_titles.values())
        logger.info(f"Fetched {len(results)} pages, {len(unique_pages)} unique by title")

        # Extract structured data (no snippets yet — too expensive for all pages)
        pages = [_extract_page_data(page) for page in unique_pages]

        # Phase 2: Score all pages with Gemini based on titles + context
        db = get_db()
        scores_by_id: dict[str, dict] = {}
        try:
            context = _build_scoring_context(db)
            scores = _score_with_gemini(pages, context)
            for item in scores:
                scores_by_id[item.get("id", "")] = item
            logger.info(f"Scored {len(scores)} Notion pages with Gemini")
        except Exception as e:
            logger.warning(f"Notion relevance scoring failed: {e}")

        # Phase 3: Fetch snippets only for the top-scored pages
        scored_pages = sorted(
            pages,
            key=lambda p: float(scores_by_id.get(p["id"], {}).get("score", 0)),
            reverse=True,
        )
        for p in scored_pages[:SNIPPET_TOP_N]:
            p["snippet"] = _fetch_page_snippet(client, headers, p["id"])

        logger.info(f"Fetched snippets for top {min(SNIPPET_TOP_N, len(scored_pages))} pages")

    # Insert all pages into DB
    for p in pages:
        score_data = scores_by_id.get(p["id"], {})
        score = min(1.0, max(0.0, float(score_data.get("score", 0))))
        reason = score_data.get("reason", "")

        db.execute(
            """INSERT OR REPLACE INTO notion_pages
               (id, title, url, last_edited_time, last_edited_by,
                parent_type, parent_id, icon, snippet,
                relevance_score, relevance_reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                p["id"],
                p["title"],
                p["url"],
                p["last_edited_time"],
                p["last_edited_by"],
                p["parent_type"],
                p["parent_id"],
                p["icon"],
                p["snippet"],
                score,
                reason,
            ),
        )

    db.commit()
    db.close()
    return len(pages)
