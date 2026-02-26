"""Live Gmail API endpoints for search, message reading, and prioritized email."""

import base64
import json
import logging
import re
from collections import OrderedDict
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from googleapiclient.discovery import build

from app_config import get_prompt_context, get_secret
from connectors.google_auth import get_google_credentials
from database import get_db_connection, get_write_db
from routers._ranking_cache import compute_items_hash

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/gmail", tags=["gmail"])


def _get_service():
    try:
        creds = get_google_credentials()
        return build("gmail", "v1", credentials=creds)
    except Exception as e:
        logger.error("Gmail not authenticated: %s", e)
        raise HTTPException(status_code=503, detail="Gmail not authenticated")


def _parse_email_header(header: str) -> tuple[str, str]:
    if "<" in header and ">" in header:
        name = header.split("<")[0].strip().strip('"')
        email = header.split("<")[1].split(">")[0].strip()
        return name, email
    return "", header.strip()


def _extract_body(payload: dict) -> str:
    """Recursively extract plain text body from Gmail message payload."""
    mime = payload.get("mimeType", "")

    # Direct text/plain part
    if mime == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    # Multipart: recurse into parts, prefer text/plain
    parts = payload.get("parts", [])
    plain = ""
    html = ""
    for part in parts:
        part_mime = part.get("mimeType", "")
        if part_mime == "text/plain" and part.get("body", {}).get("data"):
            plain = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
        elif part_mime == "text/html" and part.get("body", {}).get("data"):
            html = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
        elif "multipart" in part_mime:
            result = _extract_body(part)
            if result:
                plain = plain or result

    if plain:
        return plain
    if html:
        # Strip HTML tags for a rough plain text version
        return re.sub(r"<[^>]+>", "", html).strip()
    return ""


def _message_to_dict(msg: dict, include_body: bool = False) -> dict:
    headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
    from_name, from_email = _parse_email_header(headers.get("From", ""))
    labels = msg.get("labelIds", [])

    result = {
        "id": msg["id"],
        "thread_id": msg.get("threadId", ""),
        "subject": headers.get("Subject", "(No subject)"),
        "from_name": from_name,
        "from_email": from_email,
        "to": headers.get("To", ""),
        "date": headers.get("Date", ""),
        "snippet": msg.get("snippet", ""),
        "labels": labels,
        "is_unread": "UNREAD" in labels,
    }

    if include_body:
        result["body"] = _extract_body(msg.get("payload", {}))

    return result


@router.get("/all")
def get_all_emails(
    offset: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
):
    """Return all synced emails, newest first, with pagination."""
    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            "SELECT id, thread_id, subject, snippet, from_name, from_email, date, is_unread "
            "FROM emails ORDER BY date DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        total = db.execute("SELECT COUNT(*) as c FROM emails").fetchone()["c"]
    return {
        "items": [dict(r) for r in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < total,
    }


@router.get("/search")
def search_gmail(
    q: str = Query(..., description="Gmail search query (e.g. 'from:alice subject:review')"),
    max_results: int = Query(20, ge=1, le=100),
):
    """Search Gmail using native query syntax."""
    service = _get_service()
    try:
        results = service.users().messages().list(userId="me", q=q, maxResults=max_results).execute()
    except Exception as e:
        logger.error("Gmail search failed: %s", e)
        raise HTTPException(status_code=500, detail="Gmail search failed")

    messages = results.get("messages", [])
    if not messages:
        return {"query": q, "count": 0, "messages": []}

    output = []
    for msg_ref in messages:
        try:
            msg = (
                service.users()
                .messages()
                .get(
                    userId="me",
                    id=msg_ref["id"],
                    format="metadata",
                    metadataHeaders=["From", "To", "Subject", "Date"],
                )
                .execute()
            )
            output.append(_message_to_dict(msg))
        except Exception:
            continue

    return {"query": q, "count": len(output), "messages": output}


@router.get("/thread/{thread_id}")
def get_thread(thread_id: str):
    """Get a full email thread with message bodies."""
    service = _get_service()
    try:
        thread = service.users().threads().get(userId="me", id=thread_id, format="full").execute()
    except Exception as e:
        logger.error("Gmail thread not found: %s", e)
        raise HTTPException(status_code=404, detail="Thread not found")

    messages = []
    for msg in thread.get("messages", []):
        messages.append(_message_to_dict(msg, include_body=True))

    return {"thread_id": thread_id, "message_count": len(messages), "messages": messages}


@router.get("/message/{message_id}")
def get_message(message_id: str):
    """Get a single email message with full body text."""
    service = _get_service()
    try:
        msg = service.users().messages().get(userId="me", id=message_id, format="full").execute()
    except Exception as e:
        logger.error("Gmail message not found: %s", e)
        raise HTTPException(status_code=404, detail="Message not found")

    return _message_to_dict(msg, include_body=True)


# --- Gemini-ranked emails ---


def _build_email_rank_prompt() -> str:
    ctx = get_prompt_context()
    return f"""\
You are a priority-ranking assistant {ctx}. You will receive a list of \
recent emails. Your job is to rank them by importance/priority for the user.

For each email, assign a priority_score from 1-10 where:
- 10: Urgent, needs immediate response (exec requests, board/investor comms, production incidents)
- 7-9: High priority (direct reports needing input, external stakeholders, time-sensitive decisions)
- 4-6: Medium (project updates, meeting follow-ups, useful context)
- 1-3: Low (newsletters, automated notifications, marketing, mass mailing lists)

Each item represents an email thread (conversation). The "message_count" field shows how many messages \
are in the thread. Multi-message threads with recent activity often indicate active discussions that \
may need attention.

Consider:
1. Emails from executives, board members, or investors are highest priority
2. Emails from direct reports asking questions or needing decisions are high priority
3. Unread emails are more important than read ones
4. Emails requiring a reply or action from the user score higher
5. Time-sensitive content (deadlines, meeting prep) scores higher
6. Marketing, promotional, newsletter, and automated emails are low priority
7. Active multi-message threads where the user may need to weigh in score higher

Return ONLY valid JSON — an array of objects with keys: id, priority_score, reason (one short sentence).
Order by priority_score descending. Return ALL emails provided, scored."""


def _rank_email_with_gemini(emails: list[dict]) -> list[dict]:
    """Call Gemini to rank emails by priority."""
    api_key = get_secret("GEMINI_API_KEY") or ""
    if not api_key:
        return []

    from google import genai

    client = genai.Client(api_key=api_key)
    now = datetime.now().strftime("%A, %B %d %Y, %I:%M %p")
    user_message = f"Current time: {now}\n\nEmails to rank:\n{json.dumps(emails, default=str)}"

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=user_message,
        config={
            "system_instruction": _build_email_rank_prompt(),
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


def _dismissed_email_ids(db) -> set[str]:
    rows = db.execute("SELECT item_id FROM dismissed_dashboard_items WHERE source = 'email'").fetchall()
    return {r["item_id"] for r in rows}


@router.get("/prioritized")
def get_prioritized_email(refresh: bool = Query(False), days: int = Query(7, ge=1, le=90)):
    """Return recent emails ranked by Gemini priority score."""
    with get_db_connection(readonly=True) as db:
        dismissed = _dismissed_email_ids(db)
        cutoff = f"-{days} days"

        # Check cache first
        if not refresh:
            cached = db.execute(
                "SELECT data_json, generated_at FROM cached_email_priorities ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if cached:
                data = json.loads(cached["data_json"])
                data["items"] = [item for item in data.get("items", []) if item["id"] not in dismissed]
                return data

        # Fetch recent emails from DB
        rows = db.execute(
            "SELECT id, thread_id, subject, snippet, from_name, from_email, date, "
            "labels_json, is_unread, body_preview "
            "FROM emails "
            "WHERE synced_at >= datetime('now', ?) "
            "ORDER BY date DESC LIMIT 100",
            (cutoff,),
        ).fetchall()

    if not rows:
        return {"items": [], "error": "No emails synced yet"}

    # Group by thread before sending to Gemini
    thread_groups: OrderedDict[str, list[dict]] = OrderedDict()
    for r in rows:
        tid = r["thread_id"] or r["id"]
        if tid not in thread_groups:
            thread_groups[tid] = []
        thread_groups[tid].append(dict(r))

    emails_for_llm = []
    for tid, msgs in thread_groups.items():
        latest = msgs[0]  # rows ordered by date DESC
        combined_snippet = " | ".join((m["snippet"] or "")[:150] for m in msgs[:3])
        emails_for_llm.append(
            {
                "id": tid,
                "subject": latest["subject"],
                "from_name": latest["from_name"],
                "from_email": latest["from_email"],
                "snippet": combined_snippet[:400],
                "is_unread": any(m["is_unread"] for m in msgs),
                "date": latest["date"],
                "message_count": len(msgs),
            }
        )

    # Check if input data has changed since last ranking
    items_hash = compute_items_hash(emails_for_llm)
    with get_db_connection(readonly=True) as db:
        cached = db.execute(
            "SELECT data_json, data_hash FROM cached_email_priorities ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if cached and cached["data_hash"] == items_hash:
            logger.info("Email ranking cache hit (hash match)")
            data = json.loads(cached["data_json"])
            data["items"] = [item for item in data.get("items", []) if item["id"] not in dismissed]
            return data

    logger.info("Email ranking cache miss — calling Gemini (%d threads)", len(emails_for_llm))
    try:
        ranked = _rank_email_with_gemini(emails_for_llm)
    except Exception as e:
        logger.error("Email ranking failed: %s", e)
        return {"items": [], "error": "Ranking service unavailable"}

    # Build thread-level lookup
    thread_lookup = {}
    for tid, msgs in thread_groups.items():
        latest = msgs[0]
        thread_lookup[tid] = {
            "id": tid,
            "thread_id": tid,
            "subject": latest["subject"],
            "snippet": latest["snippet"],
            "from_name": latest["from_name"],
            "from_email": latest["from_email"],
            "date": latest["date"],
            "is_unread": any(bool(m["is_unread"]) for m in msgs),
            "message_count": len(msgs),
        }

    # Merge rankings with thread data
    items = []
    for rank in ranked:
        tid = rank.get("id", "")
        thread = thread_lookup.get(tid)
        if not thread:
            continue
        items.append(
            {
                **thread,
                "priority_score": rank.get("priority_score", 5),
                "priority_reason": rank.get("reason", ""),
            }
        )

    # Sort by score desc, filter dismissed, take top 50
    items.sort(key=lambda x: x["priority_score"], reverse=True)
    items = [i for i in items if i["id"] not in dismissed][:50]

    result = {"items": items}

    # Cache result with hash
    with get_write_db() as db:
        db.execute("DELETE FROM cached_email_priorities")
        db.execute(
            "INSERT INTO cached_email_priorities (data_json, data_hash) VALUES (?, ?)",
            (json.dumps(result), items_hash),
        )
        db.commit()

    return result
