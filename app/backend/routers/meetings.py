"""Meetings API — unified view of calendar events + external meeting notes."""

from fastapi import APIRouter, HTTPException, Query

from database import get_db_connection, get_write_db
from models import MeetingNoteUpsert

router = APIRouter(prefix="/api/meetings", tags=["meetings"])


def _dismissed_meeting_ids(db) -> set[str]:
    """Get set of dismissed meeting IDs from the dismissed_dashboard_items table."""
    rows = db.execute("SELECT item_id FROM dismissed_dashboard_items WHERE source = 'meeting'").fetchall()
    return {r["item_id"] for r in rows}


def _row_to_meeting(row) -> dict:
    """Convert a DB row to a meeting dict with both new and legacy field names."""
    d = dict(row)
    # Provider-agnostic fields
    if "transcript_text" in d:
        d["notes_transcript"] = d.pop("transcript_text")
    # Legacy aliases for backward compat
    if "notes_id" in d:
        d["granola_id"] = d["notes_id"] if d.get("notes_provider") == "granola" else None
    if "notes_summary_html" in d:
        d["granola_summary_html"] = d["notes_summary_html"]
    if "notes_summary_plain" in d:
        d["granola_summary_plain"] = d["notes_summary_plain"]
    if "notes_link" in d:
        d["granola_link"] = d["notes_link"]
    if "notes_transcript" in d:
        d["granola_transcript"] = d["notes_transcript"]
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
                    ce.color_id,
                    mne.id as notes_id, mne.provider as notes_provider,
                    mne.summary_html as notes_summary_html,
                    mne.summary_plain as notes_summary_plain,
                    mne.external_link as notes_link,
                    mne.transcript_text,
                    mne.title as notes_title,
                    mn.id as note_id, mn.content as note_content,
                    'calendar' as source_type
                FROM calendar_events ce
                LEFT JOIN meeting_notes_external mne
                    ON mne.calendar_event_id = ce.id AND mne.valid_meeting = 1
                LEFT JOIN meeting_notes mn
                    ON mn.calendar_event_id = ce.id
                WHERE ce.start_time > datetime('now')
                  AND COALESCE(ce.status, 'confirmed') != 'cancelled'
                  AND COALESCE(ce.self_response, '') != 'declined'
                ORDER BY ce.start_time ASC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()

            total = db.execute(
                "SELECT COUNT(*) as c FROM calendar_events WHERE start_time > datetime('now')"
                " AND COALESCE(status, 'confirmed') != 'cancelled'"
                " AND COALESCE(self_response, '') != 'declined'"
            ).fetchone()["c"]

        else:  # past
            rows = db.execute(
                """
                SELECT * FROM (
                    -- Calendar events with optional external notes enrichment
                    SELECT
                        ce.id as event_id, ce.summary, ce.start_time, ce.end_time,
                        ce.all_day, ce.attendees_json, ce.html_link, ce.description,
                        ce.color_id,
                        mne.id as notes_id, mne.provider as notes_provider,
                        mne.summary_html as notes_summary_html,
                        mne.summary_plain as notes_summary_plain,
                        mne.external_link as notes_link,
                        mne.transcript_text,
                        mne.title as notes_title,
                        COALESCE(mn.id, mn2.id) as note_id,
                        COALESCE(mn.content, mn2.content) as note_content,
                        'calendar' as source_type
                    FROM calendar_events ce
                    LEFT JOIN meeting_notes_external mne
                        ON mne.calendar_event_id = ce.id AND mne.valid_meeting = 1
                    LEFT JOIN meeting_notes mn ON mn.calendar_event_id = ce.id
                    LEFT JOIN meeting_notes mn2 ON mn2.external_note_id = mne.id
                    WHERE ce.start_time <= datetime('now')
                      AND COALESCE(ce.status, 'confirmed') != 'cancelled'
                      AND COALESCE(ce.self_response, '') != 'declined'

                    UNION ALL

                    -- External notes without matching calendar event
                    SELECT
                        NULL as event_id, mne.title as summary,
                        mne.created_at as start_time, NULL as end_time,
                        0 as all_day, mne.attendees_json, NULL as html_link,
                        NULL as description,
                        NULL as color_id,
                        mne.id as notes_id, mne.provider as notes_provider,
                        mne.summary_html as notes_summary_html,
                        mne.summary_plain as notes_summary_plain,
                        mne.external_link as notes_link,
                        mne.transcript_text,
                        mne.title as notes_title,
                        mn.id as note_id, mn.content as note_content,
                        'external' as source_type
                    FROM meeting_notes_external mne
                    LEFT JOIN meeting_notes mn ON mn.external_note_id = mne.id
                    WHERE mne.valid_meeting = 1
                      AND mne.created_at <= datetime('now')
                      AND (mne.calendar_event_id IS NULL
                           OR mne.calendar_event_id = ''
                           OR mne.calendar_event_id NOT IN (SELECT id FROM calendar_events))
                )
                ORDER BY start_time DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()

            total_cal = db.execute(
                "SELECT COUNT(*) as c FROM calendar_events WHERE start_time <= datetime('now')"
                " AND COALESCE(status, 'confirmed') != 'cancelled'"
                " AND COALESCE(self_response, '') != 'declined'"
            ).fetchone()["c"]
            total_ext = db.execute(
                """SELECT COUNT(*) as c FROM meeting_notes_external
                   WHERE valid_meeting = 1
                     AND created_at <= datetime('now')
                     AND (calendar_event_id IS NULL
                          OR calendar_event_id = ''
                          OR calendar_event_id NOT IN (SELECT id FROM calendar_events))"""
            ).fetchone()["c"]
            total = total_cal + total_ext

        # Filter out dismissed meetings
        dismissed = _dismissed_meeting_ids(db)

    meetings = []
    for r in rows:
        meeting_id = r["event_id"] or r["notes_id"]
        if meeting_id and meeting_id not in dismissed:
            meetings.append(_row_to_meeting(r))

    return {
        "meetings": meetings,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < total,
    }


@router.get("/notes/all")
def get_all_meeting_notes(
    offset: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
    provider: str | None = None,
):
    """Return all external meeting notes, newest first, with optional provider filter."""
    with get_db_connection(readonly=True) as db:
        if provider:
            rows = db.execute(
                """SELECT id, provider, title, created_at, updated_at, attendees_json,
                          summary_html, summary_plain, external_link,
                          transcript_text, person_id
                   FROM meeting_notes_external
                   WHERE valid_meeting = 1 AND provider = ?
                   ORDER BY created_at DESC
                   LIMIT ? OFFSET ?""",
                (provider, limit, offset),
            ).fetchall()
            total = db.execute(
                "SELECT COUNT(*) as c FROM meeting_notes_external WHERE valid_meeting = 1 AND provider = ?",
                (provider,),
            ).fetchone()["c"]
        else:
            rows = db.execute(
                """SELECT id, provider, title, created_at, updated_at, attendees_json,
                          summary_html, summary_plain, external_link,
                          transcript_text, person_id
                   FROM meeting_notes_external
                   WHERE valid_meeting = 1
                   ORDER BY created_at DESC
                   LIMIT ? OFFSET ?""",
                (limit, offset),
            ).fetchall()
            total = db.execute("SELECT COUNT(*) as c FROM meeting_notes_external WHERE valid_meeting = 1").fetchone()[
                "c"
            ]
    return {
        "items": [_row_to_meeting(r) for r in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < total,
    }


# Keep legacy endpoint as alias
@router.get("/granola/all")
def get_all_granola(
    offset: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
):
    """Legacy endpoint — returns Granola notes from meeting_notes_external."""
    return get_all_meeting_notes(offset=offset, limit=limit, provider="granola")


@router.post("/{ref_type}/{ref_id}/notes")
def upsert_meeting_note(
    ref_type: str,
    ref_id: str,
    body: MeetingNoteUpsert,
):
    if ref_type not in ("calendar", "granola", "external"):
        raise HTTPException(400, "ref_type must be 'calendar', 'granola', or 'external'")

    with get_write_db() as db:
        # Determine IDs for cross-linking
        calendar_event_id = None
        granola_meeting_id = None
        external_note_id = None

        if ref_type == "calendar":
            calendar_event_id = ref_id
            # Check if there's a linked external note
            mne = db.execute(
                "SELECT id FROM meeting_notes_external WHERE calendar_event_id = ? AND valid_meeting = 1",
                (ref_id,),
            ).fetchone()
            if mne:
                external_note_id = mne["id"]
            # Legacy: check granola_meetings too
            gm = db.execute(
                "SELECT id FROM granola_meetings WHERE calendar_event_id = ? AND valid_meeting = 1",
                (ref_id,),
            ).fetchone()
            if gm:
                granola_meeting_id = gm["id"]
        elif ref_type == "granola":
            granola_meeting_id = ref_id
            external_note_id = ref_id  # Same ID in meeting_notes_external
            gm = db.execute(
                "SELECT calendar_event_id FROM granola_meetings WHERE id = ?",
                (ref_id,),
            ).fetchone()
            if gm and gm["calendar_event_id"]:
                calendar_event_id = gm["calendar_event_id"]
        else:  # external
            external_note_id = ref_id
            mne = db.execute(
                "SELECT calendar_event_id FROM meeting_notes_external WHERE id = ?",
                (ref_id,),
            ).fetchone()
            if mne and mne["calendar_event_id"]:
                calendar_event_id = mne["calendar_event_id"]

        # Try to find existing note by any ID
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
        if not existing and external_note_id:
            existing = db.execute(
                "SELECT id FROM meeting_notes WHERE external_note_id = ?",
                (external_note_id,),
            ).fetchone()

        if existing:
            db.execute(
                """UPDATE meeting_notes
                   SET content = ?, calendar_event_id = ?, granola_meeting_id = ?,
                       external_note_id = ?, updated_at = datetime('now')
                   WHERE id = ?""",
                (body.content, calendar_event_id, granola_meeting_id, external_note_id, existing["id"]),
            )
            note_id = existing["id"]
        else:
            cur = db.execute(
                """INSERT INTO meeting_notes (calendar_event_id, granola_meeting_id, external_note_id, content)
                   VALUES (?, ?, ?, ?)""",
                (calendar_event_id, granola_meeting_id, external_note_id, body.content),
            )
            note_id = cur.lastrowid

        db.commit()

        note = dict(db.execute("SELECT * FROM meeting_notes WHERE id = ?", (note_id,)).fetchone())
    return note


@router.delete("/{ref_type}/{ref_id}/notes")
def delete_meeting_note(ref_type: str, ref_id: str):
    if ref_type not in ("calendar", "granola", "external"):
        raise HTTPException(400, "ref_type must be 'calendar', 'granola', or 'external'")

    col_map = {
        "calendar": "calendar_event_id",
        "granola": "granola_meeting_id",
        "external": "external_note_id",
    }
    col = col_map[ref_type]

    with get_write_db() as db:
        result = db.execute(f"DELETE FROM meeting_notes WHERE {col} = ?", (ref_id,))
        db.commit()

    if result.rowcount == 0:
        raise HTTPException(404, "Note not found")
    return {"status": "deleted"}
