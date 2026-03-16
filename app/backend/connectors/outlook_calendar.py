"""Microsoft Outlook Calendar connector via Graph API.

Follows the same 3-phase sync pattern as calendar_sync.py:
  Phase 1: Fetch events from Graph API (no DB lock)
  Phase 2: Normalize into calendar_events table schema
  Phase 3: Batch upsert + cleanup stale events
"""

import json
from datetime import datetime, timedelta, timezone

import httpx

from app_config import load_config
from config import CALENDAR_DAYS_AHEAD, CALENDAR_DAYS_BEHIND
from connectors.microsoft_auth import get_microsoft_token
from database import batch_upsert, get_write_db

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def sync_outlook_events() -> int:
    token = get_microsoft_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Prefer": 'outlook.timezone="UTC"',
    }

    cfg = load_config()
    user_email = cfg.get("profile", {}).get("user_email", "").lower()

    now = datetime.now(timezone.utc)
    time_min = (now - timedelta(days=CALENDAR_DAYS_BEHIND)).isoformat()
    time_max = (now + timedelta(days=CALENDAR_DAYS_AHEAD)).isoformat()

    # Phase 1: Fetch all events via calendarView (paginated)
    events = []
    url = f"{GRAPH_BASE}/me/calendarView"
    params = {
        "startDateTime": time_min,
        "endDateTime": time_max,
        "$top": 500,
        "$select": "id,subject,bodyPreview,location,start,end,isAllDay,attendees,organizer,webLink,isCancelled",
        "$orderby": "start/dateTime",
    }
    while url:
        resp = httpx.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        events.extend(data.get("value", []))
        url = data.get("@odata.nextLink")
        params = None  # nextLink includes params

    # Phase 2: Build rows (same schema as Google Calendar)
    rows = []
    for event in events:
        if event.get("isCancelled"):
            continue

        start_dt = event.get("start", {})
        end_dt = event.get("end", {})
        start_time = start_dt.get("dateTime", "")
        end_time = end_dt.get("dateTime", "")
        all_day = event.get("isAllDay", False)

        # Track current user's RSVP response
        self_response = ""
        attendees = []
        for a in event.get("attendees", []):
            email_addr = a.get("emailAddress", {})
            email = email_addr.get("address", "")
            response = a.get("status", {}).get("response", "")
            attendees.append(
                {
                    "email": email,
                    "name": email_addr.get("name", ""),
                    "response": response,
                }
            )
            if user_email and email.lower() == user_email:
                self_response = response

        # Skip events the user has declined
        if self_response == "declined":
            continue

        location = event.get("location", {})
        location_str = location.get("displayName", "") if isinstance(location, dict) else ""

        organizer = event.get("organizer", {}).get("emailAddress", {})

        rows.append(
            (
                event["id"],
                event.get("subject", "(No title)"),
                event.get("bodyPreview", ""),
                location_str,
                start_time,
                end_time,
                int(all_day),
                json.dumps(attendees),
                organizer.get("address", ""),
                "primary",
                event.get("webLink", ""),
                "confirmed",  # Outlook doesn't expose status like Google
                self_response,
            )
        )

    # Phase 3: Write + cleanup stale events in sync window
    fetched_ids = {row[0] for row in rows}
    with get_write_db() as db:
        batch_upsert(
            db,
            """INSERT OR REPLACE INTO calendar_events
               (id, summary, description, location, start_time, end_time, all_day,
                attendees_json, organizer_email, calendar_id, html_link,
                status, self_response)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )

        if fetched_ids:
            placeholders = ",".join("?" * len(fetched_ids))
            db.execute(
                f"""DELETE FROM calendar_events
                    WHERE start_time >= ? AND start_time <= ?
                      AND id NOT IN ({placeholders})""",
                [time_min, time_max, *fetched_ids],
            )
        else:
            db.execute(
                """DELETE FROM calendar_events
                   WHERE start_time >= ? AND start_time <= ?""",
                [time_min, time_max],
            )
        db.commit()

    return len(events)


def search_outlook_events(query: str, max_results: int = 20) -> list[dict]:
    """Live search via Graph API (for /api/calendar/search equivalent)."""
    token = get_microsoft_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Prefer": 'outlook.timezone="UTC"',
    }

    now = datetime.now(timezone.utc)
    time_min = (now - timedelta(days=CALENDAR_DAYS_BEHIND)).isoformat()
    time_max = (now + timedelta(days=CALENDAR_DAYS_AHEAD)).isoformat()

    # Graph API calendarView doesn't support $search, so we fetch and filter
    resp = httpx.get(
        f"{GRAPH_BASE}/me/calendarView",
        headers=headers,
        params={
            "startDateTime": time_min,
            "endDateTime": time_max,
            "$top": 200,
            "$select": "id,subject,bodyPreview,location,start,end,isAllDay,attendees,organizer,webLink",
            "$orderby": "start/dateTime",
        },
        timeout=30,
    )
    resp.raise_for_status()
    events = resp.json().get("value", [])

    # Client-side filter by query
    query_lower = query.lower()
    results = []
    for event in events:
        subject = event.get("subject", "")
        body = event.get("bodyPreview", "")
        location = event.get("location", {}).get("displayName", "") if isinstance(event.get("location"), dict) else ""
        if query_lower in subject.lower() or query_lower in body.lower() or query_lower in location.lower():
            start_dt = event.get("start", {})
            end_dt = event.get("end", {})
            attendees = [
                {
                    "email": a.get("emailAddress", {}).get("address", ""),
                    "displayName": a.get("emailAddress", {}).get("name", ""),
                    "responseStatus": a.get("status", {}).get("response", ""),
                }
                for a in event.get("attendees", [])
            ]
            results.append(
                {
                    "id": event["id"],
                    "summary": subject,
                    "description": body,
                    "location": location,
                    "start": {"dateTime": start_dt.get("dateTime", "")},
                    "end": {"dateTime": end_dt.get("dateTime", "")},
                    "attendees": attendees,
                    "organizer": {"email": event.get("organizer", {}).get("emailAddress", {}).get("address", "")},
                    "htmlLink": event.get("webLink", ""),
                }
            )
            if len(results) >= max_results:
                break
    return results


def create_outlook_event(
    summary: str,
    start_time: str,
    end_time: str,
    description: str = "",
    location: str = "",
    attendees: list[str] | None = None,
) -> dict:
    """Create a calendar event via Graph API."""
    token = get_microsoft_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    event_body = {
        "subject": summary,
        "start": {"dateTime": start_time, "timeZone": "UTC"},
        "end": {"dateTime": end_time, "timeZone": "UTC"},
    }
    if description:
        event_body["body"] = {"contentType": "Text", "content": description}
    if location:
        event_body["location"] = {"displayName": location}
    if attendees:
        event_body["attendees"] = [{"emailAddress": {"address": email}, "type": "required"} for email in attendees]

    resp = httpx.post(f"{GRAPH_BASE}/me/events", headers=headers, json=event_body, timeout=30)
    resp.raise_for_status()
    return resp.json()


def update_outlook_event(event_id: str, updates: dict) -> dict:
    """Update a calendar event via Graph API."""
    token = get_microsoft_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    patch_body = {}
    if "summary" in updates:
        patch_body["subject"] = updates["summary"]
    if "description" in updates:
        patch_body["body"] = {"contentType": "Text", "content": updates["description"]}
    if "location" in updates:
        patch_body["location"] = {"displayName": updates["location"]}
    if "start_time" in updates:
        patch_body["start"] = {"dateTime": updates["start_time"], "timeZone": "UTC"}
    if "end_time" in updates:
        patch_body["end"] = {"dateTime": updates["end_time"], "timeZone": "UTC"}

    resp = httpx.patch(f"{GRAPH_BASE}/me/events/{event_id}", headers=headers, json=patch_body, timeout=30)
    resp.raise_for_status()
    return resp.json()


def delete_outlook_event(event_id: str):
    """Delete a calendar event via Graph API."""
    token = get_microsoft_token()
    headers = {"Authorization": f"Bearer {token}"}

    resp = httpx.delete(f"{GRAPH_BASE}/me/events/{event_id}", headers=headers, timeout=30)
    resp.raise_for_status()


def rsvp_outlook_event(event_id: str, response: str, comment: str = ""):
    """RSVP to a calendar event. response: 'accepted', 'declined', 'tentativelyAccepted'."""
    token = get_microsoft_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Map standard response values to Graph API endpoints
    action_map = {
        "accepted": "accept",
        "accept": "accept",
        "declined": "decline",
        "decline": "decline",
        "tentative": "tentativelyAccept",
        "tentativelyAccepted": "tentativelyAccept",
    }
    action = action_map.get(response, "accept")

    body = {}
    if comment:
        body["comment"] = comment

    resp = httpx.post(
        f"{GRAPH_BASE}/me/events/{event_id}/{action}",
        headers=headers,
        json=body,
        timeout=30,
    )
    resp.raise_for_status()
