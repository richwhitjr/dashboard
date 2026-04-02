"""Google Calendar API connector."""

import json
from datetime import datetime, timedelta, timezone

from googleapiclient.discovery import build

from app_config import load_config
from config import CALENDAR_DAYS_AHEAD, CALENDAR_DAYS_BEHIND
from connectors.google_auth import get_google_credentials
from database import batch_upsert, get_write_db


def sync_calendar_events() -> int:
    creds = get_google_credentials()
    service = build("calendar", "v3", credentials=creds)

    # Get user email for self-response detection (fallback when API self flag is missing)
    cfg = load_config()
    user_email = cfg.get("profile", {}).get("user_email", "").lower()

    now = datetime.now(timezone.utc)
    time_min = (now - timedelta(days=CALENDAR_DAYS_BEHIND)).isoformat()
    time_max = (now + timedelta(days=CALENDAR_DAYS_AHEAD)).isoformat()

    # Phase 1: Fetch all events from API (no DB connection held)
    events = []
    page_token = None
    while True:
        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=time_min,
                timeMax=time_max,
                maxResults=2500,
                singleEvents=True,
                orderBy="startTime",
                pageToken=page_token,
            )
            .execute()
        )
        events.extend(events_result.get("items", []))
        page_token = events_result.get("nextPageToken")
        if not page_token:
            break

    # Phase 2: Build rows (skip cancelled events)
    rows = []
    for event in events:
        status = event.get("status", "confirmed")
        if status == "cancelled":
            continue

        start = event.get("start", {})
        end = event.get("end", {})
        start_time = start.get("dateTime", start.get("date", ""))
        end_time = end.get("dateTime", end.get("date", ""))
        all_day = "date" in start and "dateTime" not in start

        # Track the current user's RSVP response
        self_response = ""
        attendees = []
        for a in event.get("attendees", []):
            attendees.append(
                {
                    "email": a.get("email", ""),
                    "name": a.get("displayName", ""),
                    "response": a.get("responseStatus", ""),
                }
            )
            # Use API self flag, or match by user email from profile
            if a.get("self") or (user_email and a.get("email", "").lower() == user_email):
                self_response = a.get("responseStatus", "")

        # Skip events the user has declined
        if self_response == "declined":
            continue

        rows.append(
            (
                event["id"],
                event.get("summary", "(No title)"),
                event.get("description", ""),
                event.get("location", ""),
                start_time,
                end_time,
                int(all_day),
                json.dumps(attendees),
                event.get("organizer", {}).get("email", ""),
                "primary",
                event.get("htmlLink", ""),
                status,
                self_response,
                event.get("colorId", ""),
            )
        )

    # Phase 3: Write in batches and remove deleted events
    fetched_ids = {row[0] for row in rows}
    with get_write_db() as db:
        batch_upsert(
            db,
            """INSERT OR REPLACE INTO calendar_events
               (id, summary, description, location, start_time, end_time, all_day,
                attendees_json, organizer_email, calendar_id, html_link,
                status, self_response, color_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )

        # Remove events that exist in the DB within the sync window but were
        # not returned by the API (i.e. deleted/cancelled in Google Calendar)
        if fetched_ids:
            placeholders = ",".join("?" * len(fetched_ids))
            db.execute(
                f"""DELETE FROM calendar_events
                    WHERE start_time >= ? AND start_time <= ?
                      AND id NOT IN ({placeholders})""",
                [time_min, time_max, *fetched_ids],
            )
        else:
            # API returned zero events — clear everything in the window
            db.execute(
                """DELETE FROM calendar_events
                   WHERE start_time >= ? AND start_time <= ?""",
                [time_min, time_max],
            )
        db.commit()

    return len(events)
