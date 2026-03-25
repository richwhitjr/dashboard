"""Sync Granola meetings via official MCP server."""

import json
import logging
import re
from datetime import datetime, timedelta

from connectors.mcp_client import call_granola_tool_sync
from database import batch_upsert, get_write_db
from utils.person_matching import match_attendees_to_person

logger = logging.getLogger(__name__)

# Regex patterns for parsing Granola's pseudo-XML (contains bare <email> which breaks real XML)
_MEETING_RE = re.compile(
    r'<meeting\s+id="([^"]+)"\s+title="([^"]+)"\s+date="([^"]+)"',
)
_PARTICIPANTS_RE = re.compile(r"<known_participants>\s*(.*?)\s*</known_participants>", re.DOTALL)
_SUMMARY_RE = re.compile(r"<summary>\s*(.*?)\s*</summary>", re.DOTALL)
_MEETING_BLOCK_RE = re.compile(r"<meeting\s[^>]*>.*?</meeting>", re.DOTALL)

# Granola returns dates like "Mar 5, 2026 7:30 PM" — normalize to ISO 8601
_HUMAN_DATE_FMT = "%b %d, %Y %I:%M %p"

# Placeholder texts Granola uses when no real summary exists
_PLACEHOLDER_SUMMARIES = {"no summary", "no summary available", "no summary yet"}

# SQL fragment that matches any missing/placeholder summary value
_EMPTY_SUMMARY_SQL = (
    "(summary_plain IS NULL OR summary_plain = '' OR LOWER(summary_plain)"
    " IN ('no summary', 'no summary available', 'no summary yet'))"
)


def _normalize_date(date_str: str) -> str:
    """Convert Granola's human-readable dates to ISO 8601, passing through ISO dates unchanged."""
    if not date_str:
        return date_str
    # Already ISO format
    if date_str[:4].isdigit() and "-" in date_str[:5]:
        return date_str
    try:
        dt = datetime.strptime(date_str, _HUMAN_DATE_FMT)
        return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    except ValueError:
        return date_str


def _parse_participants(text: str) -> list[str]:
    """Extract email addresses from participant text like 'Name <email>, ...'."""
    if not text or text.strip() == "Unknown":
        return []
    return re.findall(r"<([^>]+@[^>]+)>", text)


def _parse_meetings_xml(raw: str) -> list[dict]:
    """Parse the pseudo-XML response from Granola MCP into meeting dicts.

    Granola returns XML-like markup where <known_participants> contains bare
    angle-bracketed emails (e.g. <rich@osmo.ai>) which breaks standard XML
    parsers. We use regex instead.
    """
    if not raw or "<meeting" not in raw:
        return []

    meetings = []
    for block in _MEETING_BLOCK_RE.findall(raw):
        m = _MEETING_RE.search(block)
        if not m:
            continue
        mid, title, date = m.group(1), m.group(2), m.group(3)

        participants_match = _PARTICIPANTS_RE.search(block)
        participants_text = participants_match.group(1) if participants_match else ""
        attendees = _parse_participants(participants_text)

        summary_match = _SUMMARY_RE.search(block)
        summary = summary_match.group(1) if summary_match else ""

        meetings.append(
            {
                "id": mid,
                "title": title,
                "date": date,
                "attendees": attendees,
                "summary": summary,
            }
        )
    return meetings


def _extract_notes_text(detail: dict) -> str:
    """Extract summary text from a meeting detail dict, returning '' for placeholders."""
    text = detail.get("summary", "") or detail.get("enhanced_notes", "") or detail.get("private_notes", "")
    if not text or text.strip().lower() in _PLACEHOLDER_SUMMARIES:
        return ""
    return text


def _meeting_has_ended(date_iso: str, buffer_hours: float = 1.5) -> bool:
    """Return True if the meeting started more than buffer_hours ago (likely ended)."""
    if not date_iso:
        return False
    try:
        dt_str = date_iso.replace("+00:00", "").replace("Z", "")[:19]
        meeting_dt = datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%S")
        return meeting_dt < datetime.utcnow() - timedelta(hours=buffer_hours)
    except ValueError:
        return False


def _fetch_and_update_summaries(ids: list[str]) -> int:
    """Fetch summaries from Granola for the given meeting IDs and update DB.

    Only updates rows where a real (non-placeholder) summary is returned.
    Returns the number of meetings updated.
    """
    if not ids:
        return 0

    details_map: dict = {}
    for i in range(0, len(ids), 10):
        batch = ids[i : i + 10]
        try:
            detail_raw = call_granola_tool_sync("get_meetings", {"meeting_ids": batch})
            for detail in _parse_meetings_xml(detail_raw):
                if detail.get("id"):
                    details_map[detail["id"]] = detail
        except Exception as e:
            logger.warning("Could not fetch Granola details for resync batch starting at %d: %s", i, e)

    updated = 0
    with get_write_db() as db:
        for mid, detail in details_map.items():
            notes_text = _extract_notes_text(detail)
            if not notes_text:
                continue
            db.execute(
                "UPDATE meeting_notes_external SET summary_html = ?, summary_plain = ? WHERE id = ?",
                (notes_text, notes_text, mid),
            )
            db.execute(
                "UPDATE granola_meetings SET panel_summary_html = ?, panel_summary_plain = ? WHERE id = ?",
                (notes_text, notes_text, mid),
            )
            updated += 1
        db.commit()

    logger.info("Granola resync: updated summaries for %d/%d meetings", updated, len(ids))
    return updated


def resync_missing_summaries(limit: int = 500) -> int:
    """Re-fetch summaries for all historical Granola meetings with empty summaries.

    Only processes meetings that have likely ended (started > 1.5 hours ago).
    Returns the number of meetings updated.
    """
    logger.info("Granola resync: starting missing summary scan (limit=%d)", limit)
    from database import get_db

    with get_db() as db:
        rows = db.execute(
            """SELECT id FROM meeting_notes_external
               WHERE provider = 'granola'
                 AND {_EMPTY_SUMMARY_SQL}
                 AND datetime(created_at) < datetime('now', '-2 hours')
               ORDER BY created_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()

    ids = [r["id"] for r in rows]
    if not ids:
        logger.info("Granola resync: no meetings with missing summaries")
        return 0

    logger.info("Granola resync: re-fetching summaries for %d meetings", len(ids))
    return _fetch_and_update_summaries(ids)


def sync_granola_meetings(
    time_range: str = "last_30_days",
    custom_start: str | None = None,
    custom_end: str | None = None,
) -> int:
    """Fetch meetings from Granola MCP server and upsert into DB.

    Also re-syncs summaries for any recently-ended meetings in the current window
    that are still missing them (e.g. synced while the meeting was in progress).

    Args:
        time_range: One of "this_week", "last_week", "last_30_days", "custom".
        custom_start: ISO date for custom range start (required if time_range is "custom").
        custom_end: ISO date for custom range end (required if time_range is "custom").
    """
    # list_meetings returns meeting metadata (id, title, date, attendees)
    args: dict = {"time_range": time_range}
    if time_range == "custom":
        if custom_start:
            args["custom_start"] = custom_start
        if custom_end:
            args["custom_end"] = custom_end
    raw = call_granola_tool_sync("list_meetings", args)
    if not raw:
        logger.warning("Granola MCP returned empty response — check authentication")
        return 0

    # Granola MCP returns XML; fall back to JSON for backwards compat
    meetings_list = _parse_meetings_xml(raw)
    if not meetings_list:
        try:
            meetings_list = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.error("Granola MCP returned unparseable response: %s", raw[:200])
            return 0

    if not meetings_list:
        return 0

    # Determine which meetings are new (not yet in DB) so we only fetch
    # details/transcripts for those — avoids slow re-fetches on every sync.
    from database import get_db

    existing_ids: set[str] = set()
    with get_db() as db:
        rows_db = db.execute("SELECT id FROM granola_meetings").fetchall()
        existing_ids = {r[0] for r in rows_db}

    all_ids = [m["id"] for m in meetings_list if m.get("id")]
    new_ids = [mid for mid in all_ids if mid not in existing_ids]
    logger.info("Granola: %d meetings listed, %d new", len(all_ids), len(new_ids))

    # Fetch details (summaries) only for new meetings, in batches of 10
    details_map: dict = {}
    if new_ids:
        for i in range(0, len(new_ids), 10):
            batch = new_ids[i : i + 10]
            try:
                detail_raw = call_granola_tool_sync("get_meetings", {"meeting_ids": batch})
                details = _parse_meetings_xml(detail_raw)
                for detail in details:
                    if detail.get("id"):
                        details_map[detail["id"]] = detail
            except Exception as e:
                logger.warning("Could not fetch Granola details for new meetings batch %d: %s", i, e)

    # Build insert rows for new meetings
    rows = []
    for m in meetings_list:
        mid = m.get("id", "")
        if not mid or mid in existing_ids:
            continue

        raw_attendees = m.get("attendees", [])
        # Convert plain email strings to dicts expected by match_attendees_to_person
        attendees = [{"email": a} if isinstance(a, str) else a for a in raw_attendees]
        person_id = match_attendees_to_person(attendees)
        granola_link = f"https://notes.granola.ai/d/{mid}"

        detail = details_map.get(mid, {})
        notes_text = _extract_notes_text(detail)

        date_iso = _normalize_date(m.get("date", m.get("created_at", "")))
        rows.append(
            (
                mid,
                m.get("title", ""),
                date_iso,
                date_iso,
                "",  # calendar_event_id
                "",  # calendar_event_summary
                json.dumps(attendees),
                notes_text,  # panel_summary_html
                notes_text,  # panel_summary_plain
                "",  # transcript_text — skip to keep sync fast
                granola_link,
                person_id,
                1,  # valid_meeting
            )
        )

    if rows:
        with get_write_db() as db:
            batch_upsert(
                db,
                """INSERT OR REPLACE INTO granola_meetings
                   (id, title, created_at, updated_at, calendar_event_id,
                    calendar_event_summary, attendees_json, panel_summary_html,
                    panel_summary_plain, transcript_text, granola_link,
                    person_id, valid_meeting)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )

            # Dual-write to provider-agnostic meeting_notes_external table
            external_rows = [
                (
                    r[0],  # id
                    "granola",  # provider
                    r[1],  # title
                    r[2],  # created_at
                    r[3],  # updated_at
                    r[4],  # calendar_event_id
                    r[6],  # attendees_json
                    r[7],  # summary_html (panel_summary_html)
                    r[8],  # summary_plain (panel_summary_plain)
                    r[9],  # transcript_text
                    r[10],  # external_link (granola_link)
                    r[11],  # person_id
                    r[12],  # valid_meeting
                    "{}",  # raw_metadata
                )
                for r in rows
            ]
            batch_upsert(
                db,
                """INSERT OR REPLACE INTO meeting_notes_external
                   (id, provider, title, created_at, updated_at, calendar_event_id,
                    attendees_json, summary_html, summary_plain, transcript_text,
                    external_link, person_id, valid_meeting, raw_metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                external_rows,
            )

    # Re-sync summaries for existing meetings in this window that ended but are still missing them.
    # This handles the case where a meeting was synced while in progress.
    ended_missing: list[str] = []
    if existing_ids:
        date_by_id = {
            m["id"]: _normalize_date(m.get("date", m.get("created_at", "")))
            for m in meetings_list
            if m.get("id") and m["id"] in existing_ids
        }
        ended_candidates = [mid for mid, d in date_by_id.items() if _meeting_has_ended(d)]

        if ended_candidates:
            with get_db() as db:
                placeholders = ",".join("?" * len(ended_candidates))
                missing_rows = db.execute(
                    f"SELECT id FROM meeting_notes_external WHERE id IN ({placeholders}) AND {_EMPTY_SUMMARY_SQL}",
                    tuple(ended_candidates),
                ).fetchall()
            ended_missing = [r["id"] for r in missing_rows]

    if ended_missing:
        logger.info("Granola: %d ended meetings missing summaries — re-fetching", len(ended_missing))
        _fetch_and_update_summaries(ended_missing)

    return len(rows)
