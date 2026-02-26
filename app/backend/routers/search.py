"""Unified search endpoint combining FTS5 local search with optional external service queries."""

import asyncio
import logging

from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)

from database import get_db_connection

router = APIRouter(prefix="/api/search", tags=["search"])


def _build_fts_query(q: str) -> str:
    """Convert user query to FTS5 prefix search. Each word becomes "word"*, joined with AND."""
    clean = q.replace('"', "").replace("'", "").replace("*", "")
    words = clean.split()
    if not words:
        return '""'
    return " AND ".join(f'"{w}"*' for w in words)


def _search_people(db, fts_query: str, raw_query: str, limit: int) -> list[dict]:
    results = []
    try:
        rows = db.execute(
            """SELECT p.id, p.name, p.title, p.email, p.group_name,
                      p.is_coworker, p.company,
                      highlight(fts_people, 0, '<mark>', '</mark>') as name_hl,
                      highlight(fts_people, 1, '<mark>', '</mark>') as title_hl,
                      rank
               FROM fts_people
               JOIN people p ON p.rowid = fts_people.rowid
               WHERE fts_people MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (fts_query, limit),
        ).fetchall()
        results = [dict(r) for r in rows]
    except Exception:
        pass

    # Fallback: LIKE for very short queries (1-2 chars) where FTS prefix may not match
    if not results and len(raw_query.strip()) <= 2:
        escaped = raw_query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        rows = db.execute(
            """SELECT id, name, title, email, group_name, is_coworker, company
               FROM people WHERE name LIKE ? ESCAPE '\\' OR title LIKE ? ESCAPE '\\'
               LIMIT ?""",
            (pattern, pattern, limit),
        ).fetchall()
        results = [dict(r) for r in rows]

    return results


def _search_notes(db, fts_query: str, limit: int) -> list[dict]:
    try:
        rows = db.execute(
            """SELECT n.id, n.text, n.status, n.person_id, n.is_one_on_one,
                      n.created_at, n.due_date,
                      p.name as person_name,
                      highlight(fts_notes, 0, '<mark>', '</mark>') as text_hl,
                      rank
               FROM fts_notes
               JOIN notes n ON n.id = fts_notes.rowid
               LEFT JOIN people p ON n.person_id = p.id
               WHERE fts_notes MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (fts_query, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _search_granola(db, fts_query: str, limit: int) -> list[dict]:
    try:
        rows = db.execute(
            """SELECT g.id, g.title, g.created_at, g.person_id, g.granola_link,
                      p.name as person_name,
                      highlight(fts_granola, 0, '<mark>', '</mark>') as title_hl,
                      snippet(fts_granola, 1, '<mark>', '</mark>', '...', 40) as summary_snippet,
                      rank
               FROM fts_granola
               JOIN granola_meetings g ON g.rowid = fts_granola.rowid
               LEFT JOIN people p ON g.person_id = p.id
               WHERE fts_granola MATCH ? AND g.valid_meeting = 1
               ORDER BY rank
               LIMIT ?""",
            (fts_query, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _search_meeting_files(db, fts_query: str, limit: int) -> list[dict]:
    try:
        rows = db.execute(
            """SELECT mf.id, mf.title, mf.meeting_date, mf.person_id, mf.summary,
                      p.name as person_name,
                      highlight(fts_meeting_files, 0, '<mark>', '</mark>') as title_hl,
                      snippet(fts_meeting_files, 1, '<mark>', '</mark>', '...', 40) as summary_snippet,
                      rank
               FROM fts_meeting_files
               JOIN meeting_files mf ON mf.id = fts_meeting_files.rowid
               LEFT JOIN people p ON mf.person_id = p.id
               WHERE fts_meeting_files MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (fts_query, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _search_issues(db, fts_query: str, limit: int) -> list[dict]:
    try:
        rows = db.execute(
            """SELECT i.id, i.title, i.description, i.status, i.priority,
                      i.tshirt_size, i.created_at,
                      highlight(fts_issues, 0, '<mark>', '</mark>') as title_hl,
                      snippet(fts_issues, 1, '<mark>', '</mark>', '...', 40) as description_snippet,
                      rank
               FROM fts_issues
               JOIN issues i ON i.id = fts_issues.rowid
               WHERE fts_issues MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (fts_query, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _search_longform(db, fts_query: str, limit: int) -> list[dict]:
    try:
        rows = db.execute(
            """SELECT lp.id, lp.title, lp.status, lp.word_count,
                      lp.created_at,
                      highlight(fts_longform, 0, '<mark>', '</mark>') as title_hl,
                      snippet(fts_longform, 1, '<mark>', '</mark>', '...', 40) as body_snippet_hl,
                      rank
               FROM fts_longform
               JOIN longform_posts lp ON lp.id = fts_longform.rowid
               WHERE fts_longform MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (fts_query, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _search_emails(db, fts_query: str, limit: int) -> list[dict]:
    try:
        rows = db.execute(
            """SELECT e.id, e.thread_id, e.subject, e.snippet, e.from_name,
                      e.from_email, e.date, e.is_unread,
                      highlight(fts_emails, 0, '<mark>', '</mark>') as subject_hl,
                      snippet(fts_emails, 1, '<mark>', '</mark>', '...', 40) as snippet_hl,
                      rank
               FROM fts_emails
               JOIN emails e ON e.rowid = fts_emails.rowid
               WHERE fts_emails MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (fts_query, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _search_drive_files(db, fts_query: str, limit: int) -> list[dict]:
    try:
        rows = db.execute(
            """SELECT df.id, df.name, df.mime_type, df.web_view_link,
                      df.modified_time, df.owner_name, df.content_preview,
                      highlight(fts_drive_files, 0, '<mark>', '</mark>') as name_hl,
                      snippet(fts_drive_files, 2, '<mark>', '</mark>', '...', 40) as preview_snippet,
                      rank
               FROM fts_drive_files
               JOIN drive_files df ON df.rowid = fts_drive_files.rowid
               WHERE fts_drive_files MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (fts_query, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _search_one_on_one(db, fts_query: str, limit: int) -> list[dict]:
    try:
        rows = db.execute(
            """SELECT oo.id, oo.title, oo.meeting_date, oo.person_id,
                      p.name as person_name,
                      highlight(fts_one_on_one, 0, '<mark>', '</mark>') as title_hl,
                      snippet(fts_one_on_one, 1, '<mark>', '</mark>', '...', 40) as content_snippet,
                      rank
               FROM fts_one_on_one
               JOIN one_on_one_notes oo ON oo.id = fts_one_on_one.rowid
               LEFT JOIN people p ON oo.person_id = p.id
               WHERE fts_one_on_one MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (fts_query, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


# --- External search wrappers ---


async def _search_external(q: str, limit: int) -> dict:
    """Search external services concurrently. Each failure is isolated."""
    loop = asyncio.get_event_loop()

    async def _gmail():
        try:
            from routers.gmail import search_gmail

            result = await loop.run_in_executor(None, lambda: search_gmail(q=q, max_results=limit))
            return {
                "items": [
                    {
                        "id": m["id"],
                        "title": m.get("subject", ""),
                        "subtitle": m.get("from_name", ""),
                        "snippet": m.get("snippet", ""),
                        "date": m.get("date", ""),
                    }
                    for m in result.get("messages", [])[:limit]
                ]
            }
        except Exception as e:
            logger.error("External search failed: %s", e)
            return {"items": [], "error": "Search unavailable"}

    async def _calendar():
        try:
            from routers.calendar_api import search_calendar

            result = await loop.run_in_executor(None, lambda: search_calendar(q=q))
            return {
                "items": [
                    {
                        "id": ev["id"],
                        "title": ev.get("summary", ""),
                        "subtitle": ev.get("start_time", ""),
                        "date": ev.get("start_time", ""),
                        "url": ev.get("html_link", ""),
                    }
                    for ev in result.get("events", [])[:limit]
                ]
            }
        except Exception as e:
            logger.error("External search failed: %s", e)
            return {"items": [], "error": "Search unavailable"}

    async def _slack():
        try:
            from routers.slack_api import search_slack

            result = await loop.run_in_executor(None, lambda: search_slack(q=q, count=limit))
            return {
                "items": [
                    {
                        "id": m.get("ts", ""),
                        "title": m.get("text", "")[:100],
                        "subtitle": m.get("user", ""),
                        "snippet": m.get("text", "")[:200],
                        "permalink": m.get("permalink", ""),
                    }
                    for m in result.get("messages", [])[:limit]
                ]
            }
        except Exception as e:
            logger.error("External search failed: %s", e)
            return {"items": [], "error": "Search unavailable"}

    async def _notion():
        try:
            from routers.notion_api import search_notion

            result = await loop.run_in_executor(None, lambda: search_notion(q=q, page_size=limit))
            return {
                "items": [
                    {
                        "id": p["id"],
                        "title": p.get("title", ""),
                        "url": p.get("url", ""),
                    }
                    for p in result.get("results", [])[:limit]
                ]
            }
        except Exception as e:
            logger.error("External search failed: %s", e)
            return {"items": [], "error": "Search unavailable"}

    async def _github():
        try:
            from routers.github_api import search_github

            result = await loop.run_in_executor(None, lambda: search_github(q=q, per_page=limit))
            return {
                "items": [
                    {
                        "id": str(item["number"]),
                        "title": f"#{item['number']} {item['title']}",
                        "subtitle": item.get("author", ""),
                        "url": item.get("html_url", ""),
                        "date": item.get("updated_at", ""),
                    }
                    for item in result.get("items", [])[:limit]
                ]
            }
        except Exception as e:
            logger.error("External search failed: %s", e)
            return {"items": [], "error": "Search unavailable"}

    async def _drive():
        try:
            from routers.drive_api import search_drive

            result = await loop.run_in_executor(None, lambda: search_drive(q=q, max_results=limit))
            return {
                "items": [
                    {
                        "id": f["id"],
                        "title": f.get("name", ""),
                        "subtitle": f.get("owner_name", ""),
                        "date": f.get("modified_time", ""),
                        "url": f.get("web_view_link", ""),
                    }
                    for f in result.get("files", [])[:limit]
                ]
            }
        except Exception as e:
            logger.error("External search failed: %s", e)
            return {"items": [], "error": "Search unavailable"}

    gmail, calendar, slack, notion, github, drive = await asyncio.gather(
        _gmail(), _calendar(), _slack(), _notion(), _github(), _drive()
    )

    return {
        "gmail": gmail,
        "calendar": calendar,
        "slack": slack,
        "notion": notion,
        "github": github,
        "drive": drive,
    }


@router.get("")
async def search(
    q: str = Query(..., min_length=1, description="Search query"),
    sources: str = Query("all", description="Comma-separated: people,notes,meetings,all"),
    include_external: bool = Query(False, description="Also search Gmail, Slack, Calendar, Notion"),
    limit: int = Query(10, ge=1, le=50, description="Max results per category"),
):
    source_set = set(s.strip() for s in sources.split(","))
    if "all" in source_set:
        source_set = {"people", "notes", "meetings", "emails", "drive"}

    # Backward compat: accept "employees" as alias for "people"
    if "employees" in source_set:
        source_set.discard("employees")
        source_set.add("people")

    results = {}

    with get_db_connection(readonly=True) as db:
        fts_query = _build_fts_query(q)

        if "people" in source_set:
            results["people"] = _search_people(db, fts_query, q, limit)

        if "notes" in source_set:
            results["notes"] = _search_notes(db, fts_query, limit)
            results["issues"] = _search_issues(db, fts_query, limit)
            results["longform"] = _search_longform(db, fts_query, limit)
            results["one_on_one_notes"] = _search_one_on_one(db, fts_query, limit)

        if "meetings" in source_set:
            results["granola_meetings"] = _search_granola(db, fts_query, limit)
            results["meeting_files"] = _search_meeting_files(db, fts_query, limit)

        if "emails" in source_set:
            results["emails"] = _search_emails(db, fts_query, limit)

        if "drive" in source_set:
            results["drive_files"] = _search_drive_files(db, fts_query, limit)

    if include_external:
        external = await _search_external(q, limit)
        results.update(external)

    return {"query": q, "results": results}
