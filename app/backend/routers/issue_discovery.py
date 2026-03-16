import json
import logging
import threading
from datetime import datetime
from difflib import SequenceMatcher
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel

from app_config import get_profile, get_prompt_context
from database import get_db_connection, get_write_db, rebuild_fts_table
from routers.changes import bump

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/issues/discover", tags=["issue-discovery"])

# Module-level state for progress tracking (matches sync.py pattern)
_discovery_lock = threading.Lock()
_discovery_running = False
_discovery_run_id: Optional[int] = None
_discovery_step: str = ""
_discovery_steps_done: list[str] = []


class ProposalOverrides(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[int] = None
    tshirt_size: Optional[str] = None
    tags: Optional[list[str]] = None
    people: Optional[list[str]] = None


# ---------------------------------------------------------------------------
# Context gathering (follows priorities.py _build_context pattern)
# ---------------------------------------------------------------------------


def _get_last_scan_timestamp() -> Optional[str]:
    with get_db_connection(readonly=True) as db:
        row = db.execute(
            "SELECT started_at FROM issue_discovery_runs WHERE status = 'completed' ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        return row["started_at"] if row else None


def _build_discovery_context(db, since: Optional[str]) -> dict:
    """Gather recent data from all sources, filtered by since timestamp."""

    # Build time filters — parameterised per-column
    def time_clause(col: str) -> tuple[str, list]:
        if since:
            return f"AND {col} > ?", [since]
        return f"AND {col} > datetime('now', '-7 days')", []

    cal_clause, cal_params = time_clause("start_time")
    calendar = [
        dict(r)
        for r in db.execute(
            f"SELECT summary, start_time, end_time, attendees_json, description "
            f"FROM calendar_events WHERE 1=1 "
            f"AND COALESCE(status, 'confirmed') != 'cancelled' "
            f"AND COALESCE(self_response, '') != 'declined' "
            f"{cal_clause} ORDER BY start_time DESC LIMIT 50",
            cal_params,
        ).fetchall()
    ]

    # Get user's email domain for internal/external classification
    profile = get_profile()
    email_domain = profile.get("user_email_domain", "")

    email_clause, email_params = time_clause("date")
    raw_emails = [
        dict(r)
        for r in db.execute(
            f"SELECT thread_id, subject, snippet, from_name, from_email, date, is_unread "
            f"FROM emails WHERE 1=1 "
            f"AND labels_json NOT LIKE '%CATEGORY_PROMOTIONS%' "
            f"AND labels_json NOT LIKE '%CATEGORY_SOCIAL%' "
            f"AND labels_json NOT LIKE '%CATEGORY_UPDATES%' "
            f"AND labels_json NOT LIKE '%CATEGORY_FORUMS%' "
            f"AND labels_json NOT LIKE '%UNSUBSCRIBE%' "
            f"{email_clause} ORDER BY date DESC LIMIT 80",
            email_params,
        ).fetchall()
    ]
    # Group by thread (like priorities.py)
    thread_map: dict[str, list[dict]] = {}
    for r in raw_emails:
        tid = r.get("thread_id") or r["subject"]
        thread_map.setdefault(tid, []).append(r)
    emails = []
    for msgs in thread_map.values():
        latest = msgs[0]
        from_email = latest["from_email"] or ""
        is_internal = bool(email_domain and from_email.endswith(f"@{email_domain}"))
        emails.append(
            {
                "subject": latest["subject"],
                "snippet": latest["snippet"],
                "from_name": latest["from_name"],
                "from_email": from_email,
                "date": latest["date"],
                "is_unread": any(m["is_unread"] for m in msgs),
                "message_count": len(msgs),
                "is_internal": is_internal,
            }
        )

    slack_clause, slack_params = time_clause("ts")
    slack = [
        dict(r)
        for r in db.execute(
            f"SELECT user_name, text, channel_name, channel_type, ts, is_mention "
            f"FROM slack_messages WHERE 1=1 {slack_clause} ORDER BY ts DESC LIMIT 80",
            slack_params,
        ).fetchall()
    ]

    notion_clause, notion_params = time_clause("last_edited_time")
    notion = [
        dict(r)
        for r in db.execute(
            f"SELECT title, url, last_edited_time "
            f"FROM notion_pages WHERE 1=1 {notion_clause} ORDER BY last_edited_time DESC LIMIT 30",
            notion_params,
        ).fetchall()
    ]

    granola_clause, granola_params = time_clause("created_at")
    granola = [
        dict(r)
        for r in db.execute(
            f"SELECT title, created_at, attendees_json, "
            f"SUBSTR(panel_summary_plain, 1, 800) as summary, "
            f"SUBSTR(transcript_text, 1, 800) as transcript_excerpt "
            f"FROM granola_meetings WHERE valid_meeting = 1 "
            f"{granola_clause} ORDER BY created_at DESC LIMIT 20",
            granola_params,
        ).fetchall()
    ]

    drive_clause, drive_params = time_clause("modified_time")
    drive = [
        dict(r)
        for r in db.execute(
            f"SELECT name, mime_type, modified_time, modified_by_name, owner_name "
            f"FROM drive_files WHERE trashed = 0 "
            f"AND mime_type != 'application/vnd.google-apps.spreadsheet' "
            f"{drive_clause} ORDER BY modified_time DESC LIMIT 10",
            drive_params,
        ).fetchall()
    ]

    ramp_clause, ramp_params = time_clause("due_at")
    ramp_bills = [
        dict(r)
        for r in db.execute(
            f"SELECT vendor_name, amount, due_at, status, approval_status, memo "
            f"FROM ramp_bills WHERE 1=1 {ramp_clause} "
            f"AND payment_status NOT IN ('PAID','PAYMENT_COMPLETED') "
            f"ORDER BY amount DESC LIMIT 15",
            ramp_params,
        ).fetchall()
    ]

    return {
        "calendar": calendar,
        "emails": emails,
        "slack": slack,
        "notion": notion,
        "granola_meetings": granola,
        "drive": drive,
        "ramp_bills": ramp_bills,
    }


# ---------------------------------------------------------------------------
# Gemini prompt & call (follows priorities.py pattern)
# ---------------------------------------------------------------------------


def _is_duplicate_title(title: str, existing_titles: list[str], threshold: float = 0.6) -> bool:
    """Check if a title is a fuzzy duplicate of any existing title."""
    title_lower = title.lower().strip()
    for existing in existing_titles:
        existing_lower = existing.lower().strip()
        # Exact match
        if title_lower == existing_lower:
            return True
        # Fuzzy match
        if SequenceMatcher(None, title_lower, existing_lower).ratio() >= threshold:
            return True
        # Substring containment (either direction)
        if len(title_lower) > 10 and len(existing_lower) > 10:
            if title_lower in existing_lower or existing_lower in title_lower:
                return True
    return False


def _build_discovery_prompt(existing_titles: list[str], rejected_titles: list[str]) -> str:
    ctx = get_prompt_context()

    existing_section = ""
    if existing_titles:
        existing_section = "\n\nEXISTING ISSUES (do NOT suggest duplicates of these):\n" + "\n".join(
            f"- {t}" for t in existing_titles[:50]
        )

    rejected_section = ""
    if rejected_titles:
        rejected_section = "\n\nPREVIOUSLY REJECTED (do NOT suggest these again):\n" + "\n".join(
            f"- {t}" for t in rejected_titles[:50]
        )

    return f"""\
You are a task extraction assistant {ctx}. Analyze recent activities across \
Calendar, Email, Slack, Notion pages, meeting notes (Granola), Drive documents, and Ramp bills. \
Extract actionable tasks, issues, and follow-ups that the user should track.

Your response must be a JSON array of proposed issues. Each item has:
- "title": clear, actionable title (max 12 words)
- "description": 1-2 sentence description of what needs to be done
- "priority": 0 (critical), 1 (high), 2 (medium), or 3 (low)
- "tshirt_size": "s" (< 1 hour), "m" (half day), "l" (1-2 days), "xl" (multi-day)
- "source": which data source ("email", "slack", "calendar", "notion", "granola", "drive", "ramp")
- "source_context": the exact quote or snippet that prompted this issue (for user verification)
- "suggested_tags": array of 0-3 relevant tags (lowercase)
- "suggested_people": array of people names involved (from attendees, senders, etc.)

Guidelines:
1. Focus on ACTIONABLE items — things the user needs to DO, not just FYI
2. Extract follow-ups from meetings (action items, commitments made)
3. Identify requests made via email or Slack that need responses
4. Flag upcoming deadlines or time-sensitive items
5. Note bills needing approval or review
6. Look for commitments the user made in conversations
7. Deduplicate — if the same task appears in email AND Slack, combine them
8. For Notion pages: look for pages with action items, decisions needed, or open questions
9. For Drive documents: only extract if the document clearly needs the user's review or input — \
do NOT create issues for every modified file

EMAIL FILTERING — be very strict:
- Emails marked "is_internal": true are from coworkers and are MORE likely to be actionable
- Emails from external addresses are USUALLY not actionable — only extract if they are \
a direct personal request from a known contact (not a vendor, recruiter, or service)
- IGNORE all vendor outreach, sales pitches, recruitment emails, cold emails, \
SaaS product updates, billing notifications, subscription confirmations, \
newsletters, digest emails, automated reports, and mass mailings
- IGNORE emails where the subject contains: unsubscribe, webinar, demo, \
pricing, invoice, receipt, confirm, verify, welcome, digest, weekly update, \
no-reply, noreply, do-not-reply, talent, opportunity, candidate, recruiting
- When in doubt about an external email, skip it

Do NOT extract:
- Automated notifications, build alerts, CI/CD emails
- Marketing, promotional, newsletter, or vendor outreach emails
- Recruiter or talent/hiring platform emails
- SaaS product announcements, changelog emails, or feature updates
- Items that are purely informational with no action needed
- Already-completed items
- Drive files that were just viewed or trivially edited — only if action is clearly needed
{existing_section}{rejected_section}

Return 5-20 items, sorted by priority. Respond with ONLY valid JSON — an array of objects.
No markdown, no explanation, just the JSON array."""


def _call_gemini_discovery(context: dict, existing_titles: list[str], rejected_titles: list[str]) -> list[dict]:
    from ai_client import generate

    now = datetime.now().strftime("%A, %B %d %Y, %I:%M %p")
    user_message = f"Current time: {now}\n\nRecent activity data:\n{json.dumps(context, default=str)}"

    text = generate(
        system_prompt=_build_discovery_prompt(existing_titles, rejected_titles),
        user_message=user_message,
        json_mode=True,
        temperature=0.3,
    )
    if not text:
        return []

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict) and "items" in parsed:
            return parsed["items"]
    except (json.JSONDecodeError, TypeError):
        pass
    return []


# ---------------------------------------------------------------------------
# Background discovery task
# ---------------------------------------------------------------------------


def _run_discovery(run_id: int):
    global _discovery_running, _discovery_step, _discovery_steps_done, _discovery_run_id
    _discovery_steps_done = []
    _discovery_run_id = run_id

    try:
        _discovery_step = "preparing"
        since = _get_last_scan_timestamp()

        # Gather context from all sources
        _discovery_step = "gathering"
        with get_db_connection(readonly=True) as db:
            context = _build_discovery_context(db, since)

            # All open issues (not done)
            existing = [r["title"] for r in db.execute("SELECT title FROM issues WHERE status != 'done'").fetchall()]

            # All completed issues (to prevent re-suggesting finished work)
            done_issues = [r["title"] for r in db.execute("SELECT title FROM issues WHERE status = 'done'").fetchall()]

            # ALL previously proposed titles (accepted OR rejected) from last 60 days
            prior_proposals = [
                r["title"]
                for r in db.execute(
                    "SELECT pi.title FROM proposed_issues pi "
                    "JOIN issue_discovery_runs idr ON pi.run_id = idr.id "
                    "WHERE pi.status IN ('rejected', 'accepted') "
                    "AND idr.started_at > datetime('now', '-60 days')"
                ).fetchall()
            ]

            # For the Gemini prompt: tell it about rejected AND accepted
            rejected_for_prompt = [
                r["title"]
                for r in db.execute(
                    "SELECT pi.title FROM proposed_issues pi "
                    "JOIN issue_discovery_runs idr ON pi.run_id = idr.id "
                    "WHERE pi.status = 'rejected' "
                    "AND idr.started_at > datetime('now', '-60 days')"
                ).fetchall()
            ]

            # Combined list for post-generation fuzzy dedup
            all_known_titles = list(set(existing + done_issues + prior_proposals))
        _discovery_steps_done.append("gathering")

        # Call Gemini
        _discovery_step = "analyzing"
        proposals = _call_gemini_discovery(context, existing + done_issues, rejected_for_prompt)

        # Post-generation dedup: filter out proposals that fuzzy-match known titles
        filtered = []
        seen_in_batch: list[str] = []
        for p in proposals:
            title = p.get("title", "")
            if not title:
                continue
            if _is_duplicate_title(title, all_known_titles):
                logger.info("Filtered duplicate proposal: %s", title)
                continue
            if _is_duplicate_title(title, seen_in_batch):
                logger.info("Filtered intra-batch duplicate: %s", title)
                continue
            filtered.append(p)
            seen_in_batch.append(title)
        proposals = filtered
        _discovery_steps_done.append("analyzing")

        # Store proposals
        _discovery_step = "saving"
        with get_write_db() as db:
            for p in proposals:
                db.execute(
                    "INSERT INTO proposed_issues "
                    "(run_id, title, description, priority, tshirt_size, source, "
                    "source_context, suggested_tags, suggested_people) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        p.get("title", "")[:200],
                        p.get("description", ""),
                        max(0, min(3, int(p.get("priority", 1)))),
                        str(p.get("tshirt_size", "m")).lower()[:2],
                        p.get("source", ""),
                        p.get("source_context", ""),
                        json.dumps(p.get("suggested_tags", [])),
                        json.dumps(p.get("suggested_people", [])),
                    ),
                )
            db.execute(
                "UPDATE issue_discovery_runs SET status = 'completed', "
                "completed_at = ?, items_found = ?, since_timestamp = ? WHERE id = ?",
                (datetime.now().isoformat(), len(proposals), since, run_id),
            )
            db.commit()

        _discovery_steps_done.append("saving")
        _discovery_step = "done"

    except Exception as e:
        logger.exception("Issue discovery failed")
        with get_write_db() as db:
            db.execute(
                "UPDATE issue_discovery_runs SET status = 'failed', completed_at = ?, error = ? WHERE id = ?",
                (datetime.now().isoformat(), str(e)[:500], run_id),
            )
            db.commit()
        _discovery_step = "error"
    finally:
        _discovery_running = False


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("")
def trigger_discovery(background_tasks: BackgroundTasks):
    global _discovery_running
    with _discovery_lock:
        if _discovery_running:
            return {"status": "already_running", "run_id": _discovery_run_id}
        _discovery_running = True

    with get_write_db() as db:
        cursor = db.execute("INSERT INTO issue_discovery_runs (status) VALUES ('running')")
        run_id = cursor.lastrowid
        db.commit()

    background_tasks.add_task(_run_discovery, run_id)
    return {"status": "started", "run_id": run_id}


@router.get("/status")
def get_discovery_status():
    return {
        "running": _discovery_running,
        "run_id": _discovery_run_id,
        "current_step": _discovery_step,
        "steps_done": list(_discovery_steps_done),
    }


@router.get("/proposals")
def get_proposals(
    run_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
):
    with get_db_connection(readonly=True) as db:
        if run_id is None:
            row = db.execute(
                "SELECT id FROM issue_discovery_runs WHERE status = 'completed' ORDER BY completed_at DESC LIMIT 1"
            ).fetchone()
            if not row:
                return {"proposals": [], "run_id": None, "run": None}
            run_id = row["id"]

        query = "SELECT * FROM proposed_issues WHERE run_id = ?"
        params: list = [run_id]
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY priority ASC, id ASC"

        rows = db.execute(query, params).fetchall()
        proposals = []
        for r in rows:
            p = dict(r)
            p["suggested_tags"] = json.loads(p["suggested_tags"] or "[]")
            p["suggested_people"] = json.loads(p["suggested_people"] or "[]")
            proposals.append(p)

        run = db.execute("SELECT * FROM issue_discovery_runs WHERE id = ?", (run_id,)).fetchone()

    return {
        "proposals": proposals,
        "run_id": run_id,
        "run": dict(run) if run else None,
    }


@router.post("/accept/{proposal_id}")
def accept_proposal(proposal_id: int, overrides: Optional[ProposalOverrides] = None):
    with get_write_db() as db:
        prop = db.execute("SELECT * FROM proposed_issues WHERE id = ?", (proposal_id,)).fetchone()
        if not prop:
            raise HTTPException(status_code=404, detail="Proposal not found")
        if prop["status"] != "pending":
            return {"error": f"Proposal already {prop['status']}"}

        ov = overrides or ProposalOverrides()
        title = ov.title or prop["title"]
        description = ov.description or prop["description"]
        priority = max(0, min(3, ov.priority if ov.priority is not None else prop["priority"]))
        tshirt_size = (ov.tshirt_size or prop["tshirt_size"]).lower()
        if tshirt_size not in {"s", "m", "l", "xl"}:
            tshirt_size = "m"
        tags = ov.tags if ov.tags is not None else json.loads(prop["suggested_tags"] or "[]")

        # Create the real issue
        cursor = db.execute(
            "INSERT INTO issues (title, description, priority, tshirt_size, status) VALUES (?, ?, ?, ?, 'open')",
            (title, description, priority, tshirt_size),
        )
        issue_id = cursor.lastrowid

        # Add tags
        for tag in tags:
            tag = tag.strip().lower()
            if tag:
                db.execute(
                    "INSERT OR IGNORE INTO issue_tags (issue_id, tag) VALUES (?, ?)",
                    (issue_id, tag),
                )

        # Resolve suggested people
        people_names = ov.people if ov.people is not None else json.loads(prop["suggested_people"] or "[]")
        for name in people_names:
            person = db.execute(
                "SELECT id FROM people WHERE LOWER(name) LIKE ? LIMIT 1",
                (f"%{name.lower()}%",),
            ).fetchone()
            if person:
                db.execute(
                    "INSERT OR IGNORE INTO issue_people (issue_id, person_id) VALUES (?, ?)",
                    (issue_id, person["id"]),
                )

        # Mark proposal as accepted
        db.execute(
            "UPDATE proposed_issues SET status = 'accepted', created_issue_id = ? WHERE id = ?",
            (issue_id, proposal_id),
        )
        db.execute(
            "UPDATE issue_discovery_runs SET items_accepted = items_accepted + 1 WHERE id = ?",
            (prop["run_id"],),
        )
        db.commit()

        row = db.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()

    rebuild_fts_table("fts_issues")
    bump("issues")
    return {"ok": True, "issue_id": issue_id, "issue": dict(row)}


@router.post("/reject/{proposal_id}")
def reject_proposal(proposal_id: int):
    with get_write_db() as db:
        prop = db.execute("SELECT * FROM proposed_issues WHERE id = ?", (proposal_id,)).fetchone()
        if not prop:
            raise HTTPException(status_code=404, detail="Proposal not found")

        db.execute("UPDATE proposed_issues SET status = 'rejected' WHERE id = ?", (proposal_id,))
        db.execute(
            "UPDATE issue_discovery_runs SET items_rejected = items_rejected + 1 WHERE id = ?",
            (prop["run_id"],),
        )
        db.commit()
    return {"ok": True}


@router.post("/bulk")
def bulk_action(body: dict):
    action = body.get("action")
    run_id = body.get("run_id")
    if action not in ("accept_all", "reject_all") or not run_id:
        raise HTTPException(status_code=400, detail="Invalid request: need action and run_id")

    with get_db_connection(readonly=True) as db:
        pending = db.execute(
            "SELECT id FROM proposed_issues WHERE run_id = ? AND status = 'pending'",
            (run_id,),
        ).fetchall()

    count = 0
    for row in pending:
        if action == "accept_all":
            accept_proposal(row["id"])
        else:
            reject_proposal(row["id"])
        count += 1

    return {"ok": True, "count": count}


@router.get("/history")
def get_discovery_history(limit: int = Query(5)):
    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            "SELECT * FROM issue_discovery_runs ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return {"runs": [dict(r) for r in rows]}
