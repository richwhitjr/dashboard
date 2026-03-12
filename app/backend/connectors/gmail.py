"""Google Gmail API connector."""

import json
from datetime import datetime, timezone

from googleapiclient.discovery import build

from config import GMAIL_MAX_RESULTS
from connectors.google_auth import get_google_credentials
from database import batch_upsert, get_write_db


def sync_gmail_messages() -> int:
    creds = get_google_credentials()
    service = build("gmail", "v1", credentials=creds)

    # Get recent inbox message IDs
    results = service.users().messages().list(userId="me", maxResults=GMAIL_MAX_RESULTS, labelIds=["INBOX"]).execute()
    messages = results.get("messages", [])
    if not messages:
        return 0

    # Phase 1: Batch fetch all messages in a single HTTP request (no DB connection held)
    fetched: list[dict] = []

    def _on_message(request_id, response, exception):
        if exception is None and response:
            fetched.append(response)

    batch = service.new_batch_http_request(callback=_on_message)
    for msg_ref in messages:
        batch.add(
            service.users()
            .messages()
            .get(userId="me", id=msg_ref["id"], format="metadata", metadataHeaders=["From", "To", "Subject", "Date"])
        )
    batch.execute()

    # Phase 2: Build rows
    rows = []
    for msg in fetched:
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}

        from_header = headers.get("From", "")
        from_name, from_email = _parse_email_header(from_header)

        labels = msg.get("labelIds", [])
        is_unread = "UNREAD" in labels

        # Use internalDate (epoch ms) for sortable ISO date, fall back to header
        internal_date = msg.get("internalDate")
        if internal_date:
            date_str = datetime.fromtimestamp(int(internal_date) / 1000, tz=timezone.utc).isoformat()
        else:
            date_str = headers.get("Date", "")

        rows.append(
            (
                msg["id"],
                msg.get("threadId", ""),
                headers.get("Subject", "(No subject)"),
                msg.get("snippet", ""),
                from_name,
                from_email,
                headers.get("To", ""),
                date_str,
                json.dumps(labels),
                int(is_unread),
                msg.get("snippet", "")[:500],
            )
        )

    # Phase 3: Write in batches
    with get_write_db() as db:
        batch_upsert(
            db,
            """INSERT OR REPLACE INTO emails
               (id, thread_id, subject, snippet, from_name, from_email, to_emails, date,
                labels_json, is_unread, body_preview)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )

    return len(rows)


def _parse_email_header(header: str) -> tuple[str, str]:
    """Parse 'Name <email>' format into (name, email)."""
    if "<" in header and ">" in header:
        name = header.split("<")[0].strip().strip('"')
        email = header.split("<")[1].split(">")[0].strip()
        return name, email
    return "", header.strip()
