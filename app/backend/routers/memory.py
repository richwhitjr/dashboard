"""Persistent memory system — rolling log of compacted context snapshots.

Captures what the user is doing, working on, and where they're going by
periodically compacting dashboard state into memory entries. A single
total summary synthesizes the full history and gets injected into every
new Claude agent session.
"""

import json
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from app_config import get_prompt_context
from database import get_db_connection, get_write_db
from routers._ranking_cache import compute_items_hash

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/memory", tags=["memory"])


# ---------------------------------------------------------------------------
# Context gathering
# ---------------------------------------------------------------------------


def _gather_memory_context(db) -> dict:
    """Gather current state from all sources for memory compaction.

    Similar to status_context._build_raw_context() but also includes
    Claude session history and the previous memory entry for continuity.
    """

    calendar_today = [
        dict(r)
        for r in db.execute(
            "SELECT summary, start_time, end_time, attendees_json "
            "FROM calendar_events WHERE date(start_time) = date('now')"
            " AND COALESCE(status, 'confirmed') != 'cancelled'"
            " AND COALESCE(self_response, '') != 'declined'"
            " ORDER BY start_time"
        ).fetchall()
    ]

    open_notes = [
        dict(r)
        for r in db.execute(
            "SELECT n.text, n.priority, n.is_one_on_one, n.due_date, "
            "       p.name AS person_name "
            "FROM notes n LEFT JOIN people p ON n.person_id = p.id "
            "WHERE n.status = 'open' ORDER BY n.priority DESC, n.created_at DESC LIMIT 20"
        ).fetchall()
    ]

    open_issues = [
        dict(r)
        for r in db.execute(
            "SELECT title, description, priority, tshirt_size, due_date "
            "FROM issues WHERE status != 'done' "
            "ORDER BY priority DESC, created_at DESC LIMIT 15"
        ).fetchall()
    ]

    # Recent email threads (last 2 days)
    raw_emails = [
        dict(r)
        for r in db.execute(
            "SELECT thread_id, subject, snippet, from_name, date, is_unread "
            "FROM emails "
            "WHERE date >= datetime('now', '-2 days') "
            "AND labels_json NOT LIKE '%CATEGORY_PROMOTIONS%' "
            "AND labels_json NOT LIKE '%CATEGORY_SOCIAL%' "
            "ORDER BY date DESC LIMIT 30"
        ).fetchall()
    ]
    thread_map: dict[str, list[dict]] = {}
    for r in raw_emails:
        tid = r.get("thread_id") or r["subject"]
        thread_map.setdefault(tid, []).append(r)
    emails_recent = []
    for msgs in thread_map.values():
        latest = msgs[0]
        emails_recent.append(
            {
                "subject": latest["subject"],
                "from_name": latest["from_name"],
                "date": latest["date"],
                "is_unread": any(m["is_unread"] for m in msgs),
                "count": len(msgs),
            }
        )

    slack_recent = [
        dict(r)
        for r in db.execute(
            "SELECT user_name, text, channel_name, is_mention "
            "FROM slack_messages "
            "WHERE ts >= strftime('%%s', datetime('now', '-2 days')) "
            "ORDER BY ts DESC LIMIT 20"
        ).fetchall()
    ]

    recent_meetings = [
        dict(r)
        for r in db.execute(
            "SELECT title, created_at, panel_summary_plain "
            "FROM granola_meetings "
            "WHERE created_at >= datetime('now', '-3 days') "
            "ORDER BY created_at DESC LIMIT 8"
        ).fetchall()
    ]

    # Recent Claude session summaries (last 24h)
    claude_sessions = [
        dict(r)
        for r in db.execute(
            "SELECT title, summary, created_at "
            "FROM claude_sessions "
            "WHERE created_at >= datetime('now', '-1 day') "
            "AND summary IS NOT NULL AND summary != '' "
            "ORDER BY created_at DESC LIMIT 5"
        ).fetchall()
    ]

    # Recently completed notes/issues (activity delta)
    recently_completed_notes = [
        dict(r)
        for r in db.execute(
            "SELECT text FROM notes WHERE status = 'done' AND completed_at >= datetime('now', '-1 day') LIMIT 10"
        ).fetchall()
    ]

    recently_completed_issues = [
        dict(r)
        for r in db.execute(
            "SELECT title FROM issues WHERE status = 'done' AND completed_at >= datetime('now', '-1 day') LIMIT 10"
        ).fetchall()
    ]

    # Previous memory entry for continuity
    prev_entry = None
    row = db.execute("SELECT summary, created_at FROM memory_entries ORDER BY created_at DESC LIMIT 1").fetchone()
    if row:
        prev_entry = {"summary": row["summary"], "created_at": row["created_at"]}

    sources = []
    if calendar_today:
        sources.append("calendar")
    if open_notes or recently_completed_notes:
        sources.append("notes")
    if open_issues or recently_completed_issues:
        sources.append("issues")
    if emails_recent:
        sources.append("gmail")
    if slack_recent:
        sources.append("slack")
    if recent_meetings:
        sources.append("meetings")
    if claude_sessions:
        sources.append("claude")

    return {
        "calendar_today": calendar_today,
        "open_notes": open_notes,
        "open_issues": open_issues,
        "emails_recent": emails_recent,
        "slack_recent": slack_recent,
        "recent_meetings": recent_meetings,
        "claude_sessions": claude_sessions,
        "recently_completed_notes": recently_completed_notes,
        "recently_completed_issues": recently_completed_issues,
        "previous_entry": prev_entry,
        "sources": sources,
    }


# ---------------------------------------------------------------------------
# Compaction (individual entry)
# ---------------------------------------------------------------------------


def _build_fallback_entry(context: dict) -> str:
    """Build structured text entry when Gemini is unavailable."""
    lines = []
    now = datetime.now().strftime("%A, %B %d %Y, %I:%M %p")
    lines.append(f"Memory snapshot — {now}")

    if context.get("previous_entry"):
        lines.append(f"\nPrevious: {context['previous_entry']['created_at']}")

    if context["calendar_today"]:
        lines.append("\n**Calendar:**")
        for e in context["calendar_today"]:
            lines.append(f"- {e['start_time'][:16]} {e['summary']}")

    if context["open_notes"]:
        lines.append("\n**Open items:**")
        for n in context["open_notes"][:8]:
            person = f" (@{n['person_name']})" if n.get("person_name") else ""
            lines.append(f"- {n['text'][:100]}{person}")

    if context["open_issues"]:
        lines.append("\n**Active issues:**")
        for i in context["open_issues"][:6]:
            lines.append(f"- [{i.get('priority', '?')}] {i['title']}")

    if context["recently_completed_notes"]:
        lines.append("\n**Recently completed:**")
        for n in context["recently_completed_notes"][:5]:
            lines.append(f"- {n['text'][:80]}")

    if context["recently_completed_issues"]:
        for i in context["recently_completed_issues"][:5]:
            lines.append(f"- {i['title']}")

    if context["emails_recent"]:
        lines.append("\n**Email threads:**")
        for e in context["emails_recent"][:5]:
            unread = " (UNREAD)" if e.get("is_unread") else ""
            lines.append(f"- {e['from_name']}: {e['subject']}{unread}")

    if context["claude_sessions"]:
        lines.append("\n**Claude sessions:**")
        for s in context["claude_sessions"]:
            lines.append(f"- {s['title']}")

    return "\n".join(lines)


def _compact_with_gemini(context: dict) -> str:
    """Use AI to compress context into a memory entry."""
    from ai_client import generate

    ctx = get_prompt_context()
    now = datetime.now().strftime("%A, %B %d %Y, %I:%M %p")

    system_prompt = f"""\
You are maintaining a memory log {ctx}. Given the current state of their \
dashboard data and recent activity, write a concise memory entry (200-400 words) \
that captures:

1. **What they did** — meetings attended, emails, Slack conversations, notes \
created, issues worked on, Claude sessions conducted
2. **What changed** — new items, completed items, status changes since the \
previous memory entry
3. **Current focus** — what they appear to be actively working on right now
4. **Upcoming** — what's next on the horizon (calendar, deadlines, pending items)

Guidelines:
- Write in third person present tense.
- Be specific: use names, meeting titles, email subjects, issue titles.
- Be dense: no filler, no preamble.
- Use markdown bullets for scannability.
- If a previous memory entry is included, note what's changed since then.
- This entry will be part of a chronological log — provide narrative continuity."""

    user_message = f"Current time: {now}\n\nRaw data:\n{json.dumps(context, default=str)}"

    text = generate(system_prompt=system_prompt, user_message=user_message, temperature=0.3)
    return text.strip() if text else ""


# ---------------------------------------------------------------------------
# Total summary rebuild
# ---------------------------------------------------------------------------


def _rebuild_total_summary():
    """Rebuild the single total summary from the most recent entries."""
    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            "SELECT id, summary, created_at FROM memory_entries ORDER BY created_at DESC LIMIT 20"
        ).fetchall()

    if not rows:
        return

    entries = [dict(r) for r in reversed(rows)]  # oldest first
    entries_hash = compute_items_hash(entries)

    # Check if we already have this summary
    with get_db_connection(readonly=True) as db:
        existing = db.execute("SELECT data_hash FROM memory_summary WHERE id = 1").fetchone()
        if existing and existing["data_hash"] == entries_hash:
            logger.info("Memory summary cache hit — skipping rebuild")
            return

    summary_text = ""

    try:
        from ai_client import generate

        ctx = get_prompt_context()
        now = datetime.now().strftime("%A, %B %d %Y, %I:%M %p")

        system_prompt = f"""\
You are synthesizing a chronological memory log into a single "current state" \
document {ctx}. This document will be given to AI assistants so they immediately \
understand this person's context.

From these memory entries (oldest to newest), produce a comprehensive summary \
(600-1000 words) covering:

1. **Role & Context** — who they are, their team, their responsibilities
2. **Active Workstreams** — current projects, open issues, key tasks
3. **Key Relationships** — people they interact with most, team dynamics
4. **Recent History** — what they've been doing over the last few days/weeks
5. **Priorities & Direction** — where they're headed, what matters most
6. **Patterns** — recurring themes, habits, preferences observed

Guidelines:
- Write in third person.
- Be specific and information-dense.
- Use markdown headers and bullets.
- This is for an LLM context window — optimize for information per token."""

        entries_text = "\n\n---\n\n".join(f"**{e['created_at']}**\n{e['summary']}" for e in entries)
        user_message = f"Current time: {now}\n\nMemory entries:\n{entries_text}"

        result = generate(system_prompt=system_prompt, user_message=user_message, temperature=0.2)
        if result:
            summary_text = result.strip()
    except Exception as e:
        logger.error("Memory summary AI call failed: %s", e)

    if not summary_text:
        # Fallback: concatenate recent entries
        summary_text = "# Memory Summary\n\n"
        for e in entries[-10:]:
            summary_text += f"## {e['created_at']}\n{e['summary']}\n\n"

    with get_write_db() as db:
        db.execute(
            "INSERT INTO memory_summary (id, summary_text, last_entry_id, entry_count, data_hash, generated_at) "
            "VALUES (1, ?, ?, ?, ?, datetime('now')) "
            "ON CONFLICT(id) DO UPDATE SET summary_text = excluded.summary_text, "
            "last_entry_id = excluded.last_entry_id, entry_count = excluded.entry_count, "
            "data_hash = excluded.data_hash, generated_at = excluded.generated_at",
            (summary_text, entries[-1]["id"], len(entries), entries_hash),
        )
        db.commit()

    logger.info("Memory summary rebuilt (%d chars from %d entries)", len(summary_text), len(entries))


# ---------------------------------------------------------------------------
# Public API: create memory entry
# ---------------------------------------------------------------------------


def create_memory_entry(trigger: str = "manual", claude_session_id: int | None = None) -> dict:
    """Gather context, compact via Gemini, store as memory entry.

    Called from sync pipeline, Claude session end, or manual trigger.
    Returns the new entry dict, or empty dict if skipped (dedup).
    """
    with get_db_connection(readonly=True) as db:
        context = _gather_memory_context(db)

    # Hash-check to avoid duplicate entries when nothing changed
    ctx_hash = compute_items_hash([context])
    with get_db_connection(readonly=True) as db:
        last = db.execute("SELECT data_hash FROM memory_entries ORDER BY created_at DESC LIMIT 1").fetchone()
        if last and last["data_hash"] == ctx_hash:
            logger.info("Memory entry skipped — data unchanged since last entry")
            return {}

    # Compact via Gemini, fall back to structured text
    summary = _compact_with_gemini(context)
    if not summary:
        summary = _build_fallback_entry(context)

    if not summary:
        logger.info("Memory entry skipped — no data to compact")
        return {}

    sources = context.get("sources", [])
    word_count = len(summary.split())

    with get_write_db() as db:
        cursor = db.execute(
            "INSERT INTO memory_entries "
            "(trigger, summary, raw_context_json, claude_session_id, sources_json, word_count, data_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                trigger,
                summary,
                json.dumps(context, default=str),
                claude_session_id,
                json.dumps(sources),
                word_count,
                ctx_hash,
            ),
        )
        entry_id = cursor.lastrowid

        # Rebuild FTS
        db.execute(
            "INSERT INTO fts_memory(rowid, summary) VALUES (?, ?)",
            (entry_id, summary),
        )
        db.commit()

        row = db.execute("SELECT * FROM memory_entries WHERE id = ?", (entry_id,)).fetchone()
        result = dict(row)

    logger.info("Memory entry #%d created (trigger=%s, %d words)", entry_id, trigger, word_count)

    # Rebuild total summary every 5th entry
    with get_db_connection(readonly=True) as db:
        count = db.execute("SELECT COUNT(*) as c FROM memory_entries").fetchone()["c"]
    if count % 5 == 0 or count == 1:
        _rebuild_total_summary()

    return result


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


@router.get("")
def list_memory_entries(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List memory entries, newest first."""
    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            "SELECT id, trigger, summary, sources_json, word_count, "
            "claude_session_id, data_hash, created_at "
            "FROM memory_entries ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    result = []
    for r in rows:
        entry = dict(r)
        entry["sources"] = json.loads(entry.pop("sources_json", "[]"))
        result.append(entry)
    return result


@router.get("/summary")
def get_memory_summary():
    """Return the current total memory summary."""
    with get_db_connection(readonly=True) as db:
        row = db.execute(
            "SELECT summary_text, last_entry_id, entry_count, generated_at FROM memory_summary WHERE id = 1"
        ).fetchone()
    if not row or not row["summary_text"]:
        return {"summary_text": None, "last_entry_id": 0, "entry_count": 0, "generated_at": None}
    return dict(row)


@router.get("/search")
def search_memory(q: str = Query(..., min_length=2)):
    """Full-text search over memory entries."""
    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            "SELECT m.id, m.trigger, m.summary, m.sources_json, m.word_count, "
            "m.claude_session_id, m.created_at "
            "FROM memory_entries m "
            "JOIN fts_memory f ON m.id = f.rowid "
            "WHERE fts_memory MATCH ? "
            "ORDER BY rank LIMIT 20",
            (q,),
        ).fetchall()
    result = []
    for r in rows:
        entry = dict(r)
        entry["sources"] = json.loads(entry.pop("sources_json", "[]"))
        result.append(entry)
    return result


@router.get("/{entry_id}")
def get_memory_entry(entry_id: int):
    """Get a single memory entry."""
    with get_db_connection(readonly=True) as db:
        row = db.execute("SELECT * FROM memory_entries WHERE id = ?", (entry_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Memory entry not found")
    entry = dict(row)
    entry["sources"] = json.loads(entry.pop("sources_json", "[]"))
    return entry


@router.post("/compact")
def trigger_compact():
    """Trigger manual memory compaction."""
    result = create_memory_entry(trigger="manual")
    if not result:
        return {"status": "skipped", "reason": "No new data since last entry"}
    return result


@router.post("/rebuild-summary")
def trigger_rebuild_summary():
    """Force rebuild of the total memory summary."""
    _rebuild_total_summary()
    return get_memory_summary()


@router.delete("/{entry_id}")
def delete_memory_entry(entry_id: int):
    """Delete a memory entry."""
    with get_write_db() as db:
        row = db.execute("SELECT id FROM memory_entries WHERE id = ?", (entry_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Memory entry not found")
        db.execute("DELETE FROM memory_entries WHERE id = ?", (entry_id,))
        # Remove from FTS
        db.execute("DELETE FROM fts_memory WHERE rowid = ?", (entry_id,))
        db.commit()
    return {"ok": True}
