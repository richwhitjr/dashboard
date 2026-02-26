import json
import logging
from datetime import datetime

from fastapi import APIRouter, Query

from app_config import get_prompt_context, get_secret
from database import get_db_connection, get_write_db
from routers._ranking_cache import compute_items_hash

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/priorities", tags=["priorities"])


def _build_context(db) -> dict:
    """Gather recent slack, email, and calendar data for LLM analysis."""
    calendar_today = [
        dict(r)
        for r in db.execute(
            "SELECT summary, start_time, end_time, attendees_json, description "
            "FROM calendar_events WHERE date(start_time) = date('now')"
            " AND COALESCE(status, 'confirmed') != 'cancelled'"
            " AND COALESCE(self_response, '') != 'declined'"
            " ORDER BY start_time"
        ).fetchall()
    ]

    meetings_upcoming = [
        dict(r)
        for r in db.execute(
            "SELECT summary, start_time, end_time, attendees_json "
            "FROM calendar_events WHERE start_time > datetime('now')"
            " AND COALESCE(status, 'confirmed') != 'cancelled'"
            " AND COALESCE(self_response, '') != 'declined'"
            " ORDER BY start_time LIMIT 5"
        ).fetchall()
    ]

    raw_emails = [
        dict(r)
        for r in db.execute(
            "SELECT thread_id, subject, snippet, from_name, from_email, date, is_unread "
            "FROM emails "
            "WHERE labels_json NOT LIKE '%CATEGORY_PROMOTIONS%' "
            "AND labels_json NOT LIKE '%CATEGORY_SOCIAL%' "
            "AND labels_json NOT LIKE '%CATEGORY_UPDATES%' "
            "AND labels_json NOT LIKE '%CATEGORY_FORUMS%' "
            "ORDER BY date DESC LIMIT 60"
        ).fetchall()
    ]
    # Group by thread so the AI sees conversations, not fragments
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
                "snippet": latest["snippet"],
                "from_name": latest["from_name"],
                "from_email": latest["from_email"],
                "date": latest["date"],
                "is_unread": any(m["is_unread"] for m in msgs),
                "message_count": len(msgs),
            }
        )

    slack_recent = [
        dict(r)
        for r in db.execute(
            "SELECT user_name, text, channel_name, channel_type, ts, is_mention "
            "FROM slack_messages ORDER BY ts DESC LIMIT 50"
        ).fetchall()
    ]

    open_notes = [
        dict(r)
        for r in db.execute(
            "SELECT text, priority, person_id, is_one_on_one, due_date "
            "FROM notes WHERE status = 'open' ORDER BY priority DESC, created_at DESC LIMIT 15"
        ).fetchall()
    ]

    # Bills needing attention: overdue, large, or pending approval
    ramp_bills_notable = [
        dict(r)
        for r in db.execute(
            """SELECT vendor_name, amount, currency, due_at, status, approval_status, invoice_number, memo
               FROM ramp_bills
               WHERE (
                 (due_at < datetime('now')
                  AND payment_status NOT IN ('PAID','PAYMENT_COMPLETED')
                  AND payment_status != '')
                 OR approval_status = 'PENDING'
                 OR amount >= 10000
               )
               AND payment_status NOT IN ('PAID','PAYMENT_COMPLETED')
               ORDER BY amount DESC
               LIMIT 15"""
        ).fetchall()
    ]

    drive_recent = [
        dict(r)
        for r in db.execute(
            "SELECT name, mime_type, modified_time, modified_by_name, owner_name, shared "
            "FROM drive_files "
            "WHERE modified_time >= datetime('now', '-3 days') AND trashed = 0 "
            "ORDER BY modified_time DESC LIMIT 15"
        ).fetchall()
    ]

    return {
        "calendar_today": calendar_today,
        "meetings_upcoming": meetings_upcoming,
        "emails_recent": emails_recent,
        "slack_recent": slack_recent,
        "open_notes": open_notes,
        "ramp_bills_notable": ramp_bills_notable,
        "drive_recent": drive_recent,
    }


def _build_system_prompt() -> str:
    ctx = get_prompt_context()
    return f"""\
You are a morning briefing assistant {ctx}. Your job is to analyze \
the user's Slack messages, emails, calendar, open notes, Ramp bills, and recently modified Drive files \
and produce a morning briefing.

Your response must be a JSON object with two keys:

1. "summary" — A concise 2-3 sentence narrative overview of the day ahead. \
Write it like an executive assistant briefing their boss: what kind of day is it, \
what are the key themes, what deserves their focus. Be direct and specific, not generic. \
Reference specific meetings, people, or topics by name. Do not use bullet points.

2. "items" — An array of up to 25 important items to focus on today. Each item has:
   - title: short (max 10 words)
   - reason: one sentence — why it matters or what action to take
   - source: "slack", "email", "calendar", "note", "ramp", or "drive"
   - urgency: "high", "medium", or "low"

Prioritize items:
1. Direct messages or mentions that need a reply
2. Meetings happening today that need prep
3. Unread emails from executives, direct reports, or external stakeholders
4. Threads where the user was asked a question or tagged
5. Open notes/tasks that are due or high priority
6. Anything that looks time-sensitive or blocking someone
7. Ramp bills that are overdue, pending approval, or unusually large (>$10k)
8. Recently modified Drive documents shared with you or being actively collaborated on

Ignore and never surface:
- Marketing, promotional, or newsletter emails
- Automated notifications (build alerts, billing receipts, subscription confirmations)
- Mass mailing list messages that don't require a personal reply
- Ramp bills that are already paid

Be concise and actionable. Focus on what the user should DO, not just what happened.

Respond with ONLY valid JSON — an object with keys "summary" (string) and "items" (array).
No markdown, no explanation, just the JSON object."""


def _call_gemini(context: dict, dismissed_titles: list[str]) -> dict:
    """Call Gemini API to analyze priorities. Returns {"summary": str, "items": list}."""
    api_key = get_secret("GEMINI_API_KEY") or ""
    if not api_key:
        return {"summary": "", "items": []}

    from google import genai

    client = genai.Client(api_key=api_key)

    now = datetime.now().strftime("%A, %B %d %Y, %I:%M %p")
    user_message = f"Current time: {now}\n\nHere is the data to analyze:\n{json.dumps(context, default=str)}"

    if dismissed_titles:
        user_message += (
            "\n\nIMPORTANT: The following topics have already been addressed or dismissed. "
            "Do NOT suggest items about these same topics, even with different wording:\n"
            + "\n".join(f"- {t}" for t in dismissed_titles)
        )

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=user_message,
        config={
            "system_instruction": _build_system_prompt(),
            "temperature": 0.3,
            "response_mime_type": "application/json",
        },
    )

    try:
        parsed = json.loads(response.text)
        # Handle both new format {"summary": ..., "items": [...]} and legacy format [...]
        if isinstance(parsed, dict):
            return {
                "summary": parsed.get("summary", ""),
                "items": parsed.get("items", []),
            }
        if isinstance(parsed, list):
            return {"summary": "", "items": parsed}
    except (json.JSONDecodeError, TypeError):
        pass
    return {"summary": "", "items": []}


def _get_cached(db) -> list[dict] | None:
    """Return cached priorities, or None if cache is empty."""
    rows = db.execute("SELECT title, reason, source, urgency FROM cached_priorities ORDER BY id").fetchall()
    if not rows:
        return None
    return [dict(r) for r in rows]


def _save_cache(db, items: list[dict], summary: str = "", data_hash: str = ""):
    """Replace cached priorities and summary."""
    db.execute("DELETE FROM cached_priorities")
    for item in items:
        db.execute(
            "INSERT INTO cached_priorities (title, reason, source, urgency) VALUES (?, ?, ?, ?)",
            (item.get("title", ""), item.get("reason", ""), item.get("source", ""), item.get("urgency", "")),
        )
    # Save summary with hash
    db.execute("DELETE FROM cached_briefing_summary")
    if summary:
        db.execute(
            "INSERT INTO cached_briefing_summary (id, summary, data_hash) VALUES (1, ?, ?)",
            (summary, data_hash),
        )
    db.commit()


def get_cached_summary(db) -> str | None:
    """Return cached briefing summary, or None."""
    row = db.execute("SELECT summary FROM cached_briefing_summary WHERE id = 1").fetchone()
    return row["summary"] if row else None


@router.get("")
def get_priorities(refresh: bool = Query(False)):
    with get_db_connection(readonly=True) as db:
        # Load dismissed titles
        dismissed = {r["title"] for r in db.execute("SELECT title FROM dismissed_priorities").fetchall()}

        if not refresh:
            cached = _get_cached(db)
            if cached is not None:
                items = [item for item in cached if item.get("title") not in dismissed]
                summary = get_cached_summary(db)
                return {"items": items, "summary": summary}

        # Generate fresh priorities from Gemini
        context = _build_context(db)

    # Check if input data has changed since last ranking
    ctx_hash = compute_items_hash([context])
    with get_db_connection(readonly=True) as db:
        row = db.execute("SELECT data_hash FROM cached_briefing_summary WHERE id = 1").fetchone()
        if row and row["data_hash"] == ctx_hash:
            logger.info("Priorities ranking cache hit (hash match)")
            cached = _get_cached(db)
            if cached is not None:
                items = [item for item in cached if item.get("title") not in dismissed]
                summary = get_cached_summary(db)
                return {"items": items, "summary": summary}

    logger.info("Priorities ranking cache miss — calling Gemini")
    try:
        result = _call_gemini(context, list(dismissed))
    except Exception as e:
        logger.error("Priorities ranking failed: %s", e)
        return {"items": [], "summary": None, "error": "Ranking service unavailable"}

    items = result["items"]
    summary = result["summary"]

    # Cache the results with hash
    with get_write_db() as db:
        _save_cache(db, items, summary, data_hash=ctx_hash)

    items = [item for item in items if item.get("title") not in dismissed]
    return {"items": items, "summary": summary}


@router.post("/dismiss")
def dismiss_priority(body: dict):
    title = body.get("title", "").strip()
    reason = body.get("reason", "ignored")
    if not title:
        return {"error": "title is required"}
    with get_write_db() as db:
        db.execute(
            "INSERT OR REPLACE INTO dismissed_priorities (title, reason) VALUES (?, ?)",
            (title, reason),
        )
        db.commit()
    return {"ok": True}


@router.post("/undismiss")
def undismiss_priority(body: dict):
    title = body.get("title", "").strip()
    if not title:
        return {"error": "title is required"}
    with get_write_db() as db:
        db.execute("DELETE FROM dismissed_priorities WHERE title = ?", (title,))
        db.commit()
    return {"ok": True}
