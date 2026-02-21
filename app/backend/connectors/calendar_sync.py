"""Google Calendar API connector."""

import json
from datetime import datetime, timedelta, timezone

from googleapiclient.discovery import build

from config import CALENDAR_DAYS_AHEAD, CALENDAR_DAYS_BEHIND
from connectors.google_auth import get_google_credentials
from database import get_db


def sync_calendar_events() -> int:
    creds = get_google_credentials()
    service = build("calendar", "v3", credentials=creds)

    now = datetime.now(timezone.utc)
    time_min = (now - timedelta(days=CALENDAR_DAYS_BEHIND)).isoformat()
    time_max = (now + timedelta(days=CALENDAR_DAYS_AHEAD)).isoformat()

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
    db = get_db()

    for event in events:
        start = event.get("start", {})
        end = event.get("end", {})
        start_time = start.get("dateTime", start.get("date", ""))
        end_time = end.get("dateTime", end.get("date", ""))
        all_day = "date" in start and "dateTime" not in start

        attendees = []
        for a in event.get("attendees", []):
            attendees.append(
                {
                    "email": a.get("email", ""),
                    "name": a.get("displayName", ""),
                    "response": a.get("responseStatus", ""),
                }
            )

        db.execute(
            """INSERT OR REPLACE INTO calendar_events
               (id, summary, description, location, start_time, end_time, all_day,
                attendees_json, organizer_email, calendar_id, html_link)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
            ),
        )

    db.commit()
    db.close()
    return len(events)
