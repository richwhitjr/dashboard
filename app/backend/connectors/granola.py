"""Parse Granola cache and sync meetings to SQLite."""

import json

from config import GRANOLA_CACHE_PATH
from connectors.prosemirror import pm_to_html, pm_to_text
from database import batch_upsert, get_write_db
from utils.employee_matching import match_attendees_to_employee


def parse_granola_cache() -> list[dict]:
    """Read and parse the Granola cache file into meeting records."""
    if not GRANOLA_CACHE_PATH.exists():
        return []

    with open(GRANOLA_CACHE_PATH) as f:
        raw = json.load(f)

    cache = json.loads(raw["cache"])
    state = cache["state"]

    documents = state.get("documents", {})
    panels = state.get("documentPanels", {})
    transcripts = state.get("transcripts", {})

    meetings = []
    for doc_id, doc in documents.items():
        if doc.get("deleted_at"):
            continue
        if not doc.get("valid_meeting", True):
            continue

        # Extract attendees
        attendees = []
        people = doc.get("people") or {}
        for a in people.get("attendees", []):
            attendees.append(
                {
                    "name": a.get("name", ""),
                    "email": a.get("email", a.get("name", "")),
                }
            )

        # Extract panel content (summary)
        panel_html = ""
        panel_text = ""
        doc_panels = panels.get(doc_id, {})
        if isinstance(doc_panels, dict):
            for panel_id, panel in doc_panels.items():
                if isinstance(panel, dict) and panel.get("content"):
                    panel_text = pm_to_text(panel["content"]).strip()
                    panel_html = pm_to_html(panel["content"])
                    break  # Use first panel (usually the summary)

        # Extract transcript
        transcript_segments = transcripts.get(doc_id, [])
        transcript_text = ""
        if isinstance(transcript_segments, list):
            transcript_text = " ".join(
                s.get("text", "") for s in transcript_segments if isinstance(s, dict) and s.get("text")
            )

        # Calendar event info
        cal_event = doc.get("google_calendar_event") or {}
        cal_event_id = cal_event.get("id", "")
        cal_event_summary = cal_event.get("summary", "")

        # Match to employee
        employee_id = match_attendees_to_employee(attendees)

        # Build Granola link
        granola_link = f"https://notes.granola.ai/d/{doc_id}"

        meetings.append(
            {
                "id": doc_id,
                "title": doc.get("title", ""),
                "created_at": doc.get("created_at", ""),
                "updated_at": doc.get("updated_at", ""),
                "calendar_event_id": cal_event_id,
                "calendar_event_summary": cal_event_summary,
                "attendees_json": json.dumps(attendees),
                "panel_summary_html": panel_html,
                "panel_summary_plain": panel_text,
                "transcript_text": transcript_text[:10000] if transcript_text else "",
                "granola_link": granola_link,
                "employee_id": employee_id,
                "valid_meeting": 1,
            }
        )

    return meetings


def sync_granola_meetings() -> int:
    """Parse Granola cache and upsert into granola_meetings table."""
    meetings = parse_granola_cache()
    if not meetings:
        return 0

    # Build rows from parsed meetings (no DB connection held during parsing)
    rows = [
        (
            m["id"],
            m["title"],
            m["created_at"],
            m["updated_at"],
            m["calendar_event_id"],
            m["calendar_event_summary"],
            m["attendees_json"],
            m["panel_summary_html"],
            m["panel_summary_plain"],
            m["transcript_text"],
            m["granola_link"],
            m["employee_id"],
            m["valid_meeting"],
        )
        for m in meetings
    ]

    with get_write_db() as db:
        batch_upsert(
            db,
            """INSERT OR REPLACE INTO granola_meetings
               (id, title, created_at, updated_at, calendar_event_id, calendar_event_summary,
                attendees_json, panel_summary_html, panel_summary_plain, transcript_text,
                granola_link, employee_id, valid_meeting)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )

    return len(meetings)
