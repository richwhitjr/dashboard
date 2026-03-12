"""Live Gmail API endpoints for search, message reading, and prioritized email."""

import base64
import json
import logging
import re
from collections import OrderedDict
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from googleapiclient.discovery import build

from app_config import get_prompt_context
from connectors.google_auth import get_google_credentials
from database import get_db_connection, get_write_db
from models import GmailArchive, GmailDraftCreate, GmailDraftUpdate, GmailSend, GmailTrash
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


# --- Write endpoints ---


def _build_mime_message(
    to: str,
    subject: str,
    body: str,
    cc: str | None = None,
    bcc: str | None = None,
    reply_to_message_id: str | None = None,
) -> str:
    """Build a raw base64url-encoded MIME message."""
    from email.mime.text import MIMEText

    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject
    if cc:
        message["cc"] = cc
    if bcc:
        message["bcc"] = bcc
    if reply_to_message_id:
        message["In-Reply-To"] = reply_to_message_id
        message["References"] = reply_to_message_id

    return base64.urlsafe_b64encode(message.as_bytes()).decode()


@router.post("/send")
def send_email(email: GmailSend):
    """Send an email (new or reply)."""
    service = _get_service()
    raw = _build_mime_message(
        email.to,
        email.subject,
        email.body,
        cc=email.cc,
        bcc=email.bcc,
        reply_to_message_id=email.reply_to_message_id,
    )
    send_body: dict = {"raw": raw}
    if email.reply_to_thread_id:
        send_body["threadId"] = email.reply_to_thread_id

    try:
        result = service.users().messages().send(userId="me", body=send_body).execute()
    except Exception as e:
        logger.error("Failed to send email: %s", e)
        raise HTTPException(status_code=500, detail="Failed to send email")

    return {
        "id": result.get("id"),
        "thread_id": result.get("threadId"),
        "label_ids": result.get("labelIds", []),
    }


@router.get("/drafts")
def list_drafts(max_results: int = Query(20, ge=1, le=100)):
    """List email drafts."""
    service = _get_service()
    try:
        results = service.users().drafts().list(userId="me", maxResults=max_results).execute()
    except Exception as e:
        logger.error("Failed to list drafts: %s", e)
        raise HTTPException(status_code=500, detail="Failed to list drafts")

    drafts = []
    for d in results.get("drafts", []):
        try:
            draft = (
                service.users()
                .drafts()
                .get(userId="me", id=d["id"], format="metadata", metadataHeaders=["To", "Subject"])
                .execute()
            )
            msg = draft.get("message", {})
            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            drafts.append(
                {
                    "id": d["id"],
                    "message_id": msg.get("id", ""),
                    "subject": headers.get("Subject", "(No subject)"),
                    "to": headers.get("To", ""),
                    "snippet": msg.get("snippet", ""),
                }
            )
        except Exception:
            continue

    return {"count": len(drafts), "drafts": drafts}


@router.post("/drafts")
def create_draft(draft: GmailDraftCreate):
    """Create an email draft."""
    service = _get_service()
    raw = _build_mime_message(draft.to, draft.subject, draft.body, cc=draft.cc, bcc=draft.bcc)

    try:
        result = service.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
    except Exception as e:
        logger.error("Failed to create draft: %s", e)
        raise HTTPException(status_code=500, detail="Failed to create draft")

    return {"id": result.get("id"), "message_id": result.get("message", {}).get("id", "")}


@router.patch("/drafts/{draft_id}")
def update_draft(draft_id: str, draft: GmailDraftUpdate):
    """Update an existing draft."""
    service = _get_service()

    # Fetch current draft to fill in unchanged fields
    try:
        current = service.users().drafts().get(userId="me", id=draft_id, format="full").execute()
        msg = current.get("message", {})
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
    except Exception as e:
        logger.error("Draft not found: %s", e)
        raise HTTPException(status_code=404, detail="Draft not found")

    to = draft.to or headers.get("To", "")
    subject = draft.subject or headers.get("Subject", "")
    body_text = draft.body if draft.body is not None else _extract_body(msg.get("payload", {}))
    cc = draft.cc or headers.get("Cc")
    bcc = draft.bcc or headers.get("Bcc")

    raw = _build_mime_message(to, subject, body_text, cc=cc, bcc=bcc)

    try:
        result = service.users().drafts().update(userId="me", id=draft_id, body={"message": {"raw": raw}}).execute()
    except Exception as e:
        logger.error("Failed to update draft: %s", e)
        raise HTTPException(status_code=500, detail="Failed to update draft")

    return {"id": result.get("id"), "message_id": result.get("message", {}).get("id", "")}


@router.delete("/drafts/{draft_id}")
def delete_draft(draft_id: str):
    """Delete a draft."""
    service = _get_service()
    try:
        service.users().drafts().delete(userId="me", id=draft_id).execute()
    except Exception as e:
        logger.error("Failed to delete draft: %s", e)
        raise HTTPException(status_code=500, detail="Failed to delete draft")
    return {"ok": True, "draft_id": draft_id}


@router.post("/archive")
def archive_messages(body: GmailArchive):
    """Archive messages by removing INBOX label."""
    service = _get_service()
    results = []
    for msg_id in body.message_ids:
        try:
            service.users().messages().modify(
                userId="me",
                id=msg_id,
                body={"removeLabelIds": ["INBOX"]},
            ).execute()
            results.append({"id": msg_id, "ok": True})
        except Exception as e:
            results.append({"id": msg_id, "ok": False, "error": str(e)})
    return {"results": results}


@router.post("/trash")
def trash_messages(body: GmailTrash):
    """Move messages to trash."""
    service = _get_service()
    results = []
    for msg_id in body.message_ids:
        try:
            service.users().messages().trash(userId="me", id=msg_id).execute()
            results.append({"id": msg_id, "ok": True})
        except Exception as e:
            results.append({"id": msg_id, "ok": False, "error": str(e)})
    return {"results": results}


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
    """Rank emails by priority using the configured AI provider."""
    from ai_client import generate

    now = datetime.now().strftime("%A, %B %d %Y, %I:%M %p")
    user_message = f"Current time: {now}\n\nEmails to rank:\n{json.dumps(emails, default=str)}"

    text = generate(system_prompt=_build_email_rank_prompt(), user_message=user_message, json_mode=True)
    if not text:
        return []

    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def _dismissed_email_ids(db) -> set[str]:
    rows = db.execute("SELECT item_id FROM dismissed_dashboard_items WHERE source = 'email'").fetchall()
    return {r["item_id"] for r in rows}


def rerank_email(days: int = 7) -> bool:
    """Rerank email items — updates cache if data changed. Returns True if cache was updated."""
    from routers._ranking_cache import finish_reranking, start_reranking

    if not start_reranking("email"):
        return False
    try:
        return _do_rerank_email(days)
    finally:
        finish_reranking("email")


def _do_rerank_email(days: int = 7) -> bool:
    cutoff = f"-{days} days"
    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            "SELECT id, thread_id, subject, snippet, from_name, from_email, date, "
            "labels_json, is_unread, body_preview "
            "FROM emails "
            "WHERE synced_at >= datetime('now', ?) "
            "ORDER BY date DESC LIMIT 100",
            (cutoff,),
        ).fetchall()

    if not rows:
        return False

    thread_groups: OrderedDict[str, list[dict]] = OrderedDict()
    for r in rows:
        tid = r["thread_id"] or r["id"]
        if tid not in thread_groups:
            thread_groups[tid] = []
        thread_groups[tid].append(dict(r))

    emails_for_llm = []
    for tid, msgs in thread_groups.items():
        latest = msgs[0]
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

    items_hash = compute_items_hash(emails_for_llm)
    with get_db_connection(readonly=True) as db:
        cached = db.execute("SELECT data_hash FROM cached_email_priorities ORDER BY id DESC LIMIT 1").fetchone()
        if cached and cached["data_hash"] == items_hash:
            return False

    logger.info("Email rerank — calling AI (%d threads)", len(emails_for_llm))
    try:
        ranked = _rank_email_with_gemini(emails_for_llm)
    except Exception as e:
        logger.error("Email rerank failed: %s", e)
        return False

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

    items.sort(key=lambda x: x["priority_score"], reverse=True)
    items = items[:50]

    if not items:
        logger.warning("Email rerank produced 0 items — not caching empty result")
        return False

    result = {"items": items}

    with get_write_db() as db:
        db.execute("DELETE FROM cached_email_priorities")
        db.execute(
            "INSERT INTO cached_email_priorities (data_json, data_hash) VALUES (?, ?)",
            (json.dumps(result), items_hash),
        )
        db.commit()

    logger.info("Email rerank complete — %d items cached", len(items))
    return True


@router.get("/prioritized")
def get_prioritized_email(
    refresh: bool = Query(False),
    days: int = Query(7, ge=1, le=90),
    background_tasks: BackgroundTasks = None,
):
    """Return recent emails ranked by Gemini priority score."""
    from routers._ranking_cache import is_reranking

    with get_db_connection(readonly=True) as db:
        dismissed = _dismissed_email_ids(db)
        cached = db.execute(
            "SELECT data_json, generated_at FROM cached_email_priorities ORDER BY id DESC LIMIT 1"
        ).fetchone()

    if cached:
        data = json.loads(cached["data_json"])
        data["items"] = [item for item in data.get("items", []) if item["id"] not in dismissed]

        if not refresh:
            return data

        # Stale-while-revalidate: return cached data, rerank in background
        if background_tasks and not is_reranking("email"):
            background_tasks.add_task(rerank_email, days)
        data["stale"] = True
        return data

    # No cache — synchronous first-time ranking
    result = _do_rerank_email(days)
    if not result:
        return {"items": [], "error": "No emails synced yet"}

    # Read back from cache
    with get_db_connection(readonly=True) as db:
        cached = db.execute("SELECT data_json FROM cached_email_priorities ORDER BY id DESC LIMIT 1").fetchone()
        if cached:
            data = json.loads(cached["data_json"])
            data["items"] = [item for item in data.get("items", []) if item["id"] not in dismissed]
            return data

    return {"items": []}
