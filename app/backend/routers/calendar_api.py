"""Live Google Calendar API endpoints for searching and reading events."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

from connectors.google_auth import get_google_credentials

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


def _get_service():
    try:
        creds = get_google_credentials()
        return build("calendar", "v3", credentials=creds)
    except Exception as e:
        logger.error("Calendar not authenticated: %s", e)
        raise HTTPException(status_code=503, detail="Calendar not authenticated")


def _event_to_dict(event: dict) -> dict:
    start = event.get("start", {})
    end = event.get("end", {})

    attendees = []
    for a in event.get("attendees", []):
        attendees.append(
            {
                "email": a.get("email", ""),
                "name": a.get("displayName", ""),
                "response": a.get("responseStatus", ""),
                "self": a.get("self", False),
            }
        )

    return {
        "id": event["id"],
        "summary": event.get("summary", "(No title)"),
        "description": event.get("description", ""),
        "location": event.get("location", ""),
        "start_time": start.get("dateTime", start.get("date", "")),
        "end_time": end.get("dateTime", end.get("date", "")),
        "all_day": "date" in start and "dateTime" not in start,
        "attendees": attendees,
        "organizer_email": event.get("organizer", {}).get("email", ""),
        "html_link": event.get("htmlLink", ""),
        "status": event.get("status", ""),
        "recurring_event_id": event.get("recurringEventId"),
        "conference_data": event.get("conferenceData", {}).get("entryPoints", []),
    }


@router.get("/search")
def search_calendar(
    q: Optional[str] = Query(None, description="Text search across event fields"),
    start: Optional[str] = Query(None, description="Start date/time (ISO format)"),
    end: Optional[str] = Query(None, description="End date/time (ISO format)"),
    max_results: int = Query(50, ge=1, le=250),
):
    """Search calendar events by text and/or date range."""
    service = _get_service()

    now = datetime.now(timezone.utc)
    time_min = start if start else (now - timedelta(days=30)).isoformat()
    time_max = end if end else (now + timedelta(days=30)).isoformat()

    try:
        kwargs = {
            "calendarId": "primary",
            "timeMin": time_min,
            "timeMax": time_max,
            "maxResults": max_results,
            "singleEvents": True,
            "orderBy": "startTime",
        }
        if q:
            kwargs["q"] = q

        events_result = service.events().list(**kwargs).execute()
    except Exception as e:
        logger.error("Calendar search failed: %s", e)
        raise HTTPException(status_code=500, detail="Calendar search failed")

    events = [_event_to_dict(e) for e in events_result.get("items", [])]
    return {"query": q, "time_range": {"start": time_min, "end": time_max}, "count": len(events), "events": events}


@router.get("/event/{event_id}")
def get_event(event_id: str):
    """Get a single calendar event with full details."""
    service = _get_service()
    try:
        event = service.events().get(calendarId="primary", eventId=event_id).execute()
    except Exception as e:
        logger.error("Calendar event not found: %s", e)
        raise HTTPException(status_code=404, detail="Event not found")

    return _event_to_dict(event)
