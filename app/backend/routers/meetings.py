"""Meetings API — unified view of calendar events + Granola meetings with personal notes."""

from fastapi import APIRouter, HTTPException, Query

from database import get_db_connection, get_write_db
from models import MeetingNoteUpsert

router = APIRouter(prefix="/api/meetings", tags=["meetings"])


def _dismissed_meeting_ids(db) -> set[str]:
    """Get set of dismissed meeting IDs from the dismissed_dashboard_items table."""
    rows = db.execute("SELECT item_id FROM dismissed_dashboard_items WHERE source = 'meeting'").fetchall()
    return {r["item_id"] for r in rows}


def _row_to_meeting(row) -> dict:
    """Convert a DB row to a meeting dict."""
    d = dict(row)
    # Rename transcript_text -> granola_transcript for API consistency
    if "transcript_text" in d:
        d["granola_transcript"] = d.pop("transcript_text")
    return d


@router.get("")
def list_meetings(
    tab: str = Query("upcoming", regex="^(upcoming|past)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    with get_db_connection(readonly=True) as db:
        if tab == "upcoming":
            rows = db.execute(
                """
                SELECT
                    ce.id as event_id, ce.summary, ce.start_time, ce.end_time,
                    ce.all_day, ce.attendees_json, ce.html_link, ce.description,
                    gm.id as granola_id, gm.panel_summary_html as granola_summary_html,
                    gm.panel_summary_plain as granola_summary_plain,
                    gm.granola_link, gm.transcript_text, gm.title as granola_title,
                    mn.id as note_id, mn.content as note_content,
                    'calendar' as source_type
                FROM calendar_events ce
                LEFT JOIN granola_meetings gm
                    ON gm.calendar_event_id = ce.id AND gm.valid_meeting = 1
                LEFT JOIN meeting_notes mn
                    ON mn.calendar_event_id = ce.id
                WHERE ce.start_time > datetime('now')
                ORDER BY ce.start_time ASC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()

            total = db.execute(
                "SELECT COUNT(*) as c FROM calendar_events WHERE start_time > datetime('now')"
            ).fetchone()["c"]

        else:  # past
            rows = db.execute(
                """
                SELECT * FROM (
                    -- Calendar events with optional Granola enrichment
                    SELECT
                        ce.id as event_id, ce.summary, ce.start_time, ce.end_time,
                        ce.all_day, ce.attendees_json, ce.html_link, ce.description,
                        gm.id as granola_id, gm.panel_summary_html as granola_summary_html,
                        gm.panel_summary_plain as granola_summary_plain,
                        gm.granola_link, gm.transcript_text, gm.title as granola_title,
                        COALESCE(mn.id, mn2.id) as note_id,
                        COALESCE(mn.content, mn2.content) as note_content,
                        'calendar' as source_type
                    FROM calendar_events ce
                    LEFT JOIN granola_meetings gm
                        ON gm.calendar_event_id = ce.id AND gm.valid_meeting = 1
                    LEFT JOIN meeting_notes mn ON mn.calendar_event_id = ce.id
                    LEFT JOIN meeting_notes mn2 ON mn2.granola_meeting_id = gm.id
                    WHERE ce.start_time <= datetime('now')

                    UNION ALL

                    -- Granola-only meetings (no matching calendar event)
                    SELECT
                        NULL as event_id, gm.title as summary,
                        gm.created_at as start_time, NULL as end_time,
                        0 as all_day, gm.attendees_json, NULL as html_link,
                        NULL as description,
                        gm.id as granola_id, gm.panel_summary_html as granola_summary_html,
                        gm.panel_summary_plain as granola_summary_plain,
                        gm.granola_link, gm.transcript_text, gm.title as granola_title,
                        mn.id as note_id, mn.content as note_content,
                        'granola' as source_type
                    FROM granola_meetings gm
                    LEFT JOIN meeting_notes mn ON mn.granola_meeting_id = gm.id
                    WHERE gm.valid_meeting = 1
                      AND gm.created_at <= datetime('now')
                      AND (gm.calendar_event_id IS NULL
                           OR gm.calendar_event_id = ''
                           OR gm.calendar_event_id NOT IN (SELECT id FROM calendar_events))
                )
                ORDER BY start_time DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()

            total_cal = db.execute(
                "SELECT COUNT(*) as c FROM calendar_events WHERE start_time <= datetime('now')"
            ).fetchone()["c"]
            total_granola = db.execute(
                """SELECT COUNT(*) as c FROM granola_meetings
                   WHERE valid_meeting = 1
                     AND created_at <= datetime('now')
                     AND (calendar_event_id IS NULL
                          OR calendar_event_id = ''
                          OR calendar_event_id NOT IN (SELECT id FROM calendar_events))"""
            ).fetchone()["c"]
            total = total_cal + total_granola

        # Filter out dismissed meetings
        dismissed = _dismissed_meeting_ids(db)

    meetings = []
    for r in rows:
        # A meeting is identified by its event_id (calendar) or granola_id (Granola)
        meeting_id = r["event_id"] or r["granola_id"]
        if meeting_id and meeting_id not in dismissed:
            meetings.append(_row_to_meeting(r))

    return {
        "meetings": meetings,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < total,
    }


@router.post("/{ref_type}/{ref_id}/notes")
def upsert_meeting_note(
    ref_type: str,
    ref_id: str,
    body: MeetingNoteUpsert,
):
    if ref_type not in ("calendar", "granola"):
        raise HTTPException(400, "ref_type must be 'calendar' or 'granola'")

    with get_write_db() as db:
        # Determine both IDs for cross-linking
        calendar_event_id = None
        granola_meeting_id = None

        if ref_type == "calendar":
            calendar_event_id = ref_id
            # Check if there's a linked Granola meeting
            gm = db.execute(
                "SELECT id FROM granola_meetings WHERE calendar_event_id = ? AND valid_meeting = 1",
                (ref_id,),
            ).fetchone()
            if gm:
                granola_meeting_id = gm["id"]
        else:
            granola_meeting_id = ref_id
            # Check if the Granola meeting has a calendar event
            gm = db.execute(
                "SELECT calendar_event_id FROM granola_meetings WHERE id = ?",
                (ref_id,),
            ).fetchone()
            if gm and gm["calendar_event_id"]:
                calendar_event_id = gm["calendar_event_id"]

        # Try to find existing note by either ID
        existing = None
        if calendar_event_id:
            existing = db.execute(
                "SELECT id FROM meeting_notes WHERE calendar_event_id = ?",
                (calendar_event_id,),
            ).fetchone()
        if not existing and granola_meeting_id:
            existing = db.execute(
                "SELECT id FROM meeting_notes WHERE granola_meeting_id = ?",
                (granola_meeting_id,),
            ).fetchone()

        if existing:
            db.execute(
                """UPDATE meeting_notes
                   SET content = ?, calendar_event_id = ?, granola_meeting_id = ?,
                       updated_at = datetime('now')
                   WHERE id = ?""",
                (body.content, calendar_event_id, granola_meeting_id, existing["id"]),
            )
            note_id = existing["id"]
        else:
            cur = db.execute(
                """INSERT INTO meeting_notes (calendar_event_id, granola_meeting_id, content)
                   VALUES (?, ?, ?)""",
                (calendar_event_id, granola_meeting_id, body.content),
            )
            note_id = cur.lastrowid

        db.commit()

        note = dict(db.execute("SELECT * FROM meeting_notes WHERE id = ?", (note_id,)).fetchone())
    return note


@router.delete("/{ref_type}/{ref_id}/notes")
def delete_meeting_note(ref_type: str, ref_id: str):
    if ref_type not in ("calendar", "granola"):
        raise HTTPException(400, "ref_type must be 'calendar' or 'granola'")

    MEETING_NOTE_COLS = {"calendar_event_id", "granola_meeting_id"}
    col = "calendar_event_id" if ref_type == "calendar" else "granola_meeting_id"
    assert col in MEETING_NOTE_COLS

    with get_write_db() as db:
        result = db.execute(f"DELETE FROM meeting_notes WHERE {col} = ?", (ref_id,))
        db.commit()

    if result.rowcount == 0:
        raise HTTPException(404, "Note not found")
    return {"status": "deleted"}
