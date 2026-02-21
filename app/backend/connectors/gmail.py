"""Google Gmail API connector."""

import json

from googleapiclient.discovery import build

from config import GMAIL_MAX_RESULTS
from connectors.google_auth import get_google_credentials
from database import get_db


def sync_gmail_messages() -> int:
    creds = get_google_credentials()
    service = build("gmail", "v1", credentials=creds)

    # Get recent inbox message IDs
    results = service.users().messages().list(userId="me", maxResults=GMAIL_MAX_RESULTS, labelIds=["INBOX"]).execute()
    messages = results.get("messages", [])
    if not messages:
        return 0

    db = get_db()

    # Batch fetch all messages in a single HTTP request instead of N sequential calls
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

    count = 0
    for msg in fetched:
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}

        from_header = headers.get("From", "")
        from_name, from_email = _parse_email_header(from_header)

        labels = msg.get("labelIds", [])
        is_unread = "UNREAD" in labels

        db.execute(
            """INSERT OR REPLACE INTO emails
               (id, thread_id, subject, snippet, from_name, from_email, to_emails, date,
                labels_json, is_unread, body_preview)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                msg["id"],
                msg.get("threadId", ""),
                headers.get("Subject", "(No subject)"),
                msg.get("snippet", ""),
                from_name,
                from_email,
                headers.get("To", ""),
                headers.get("Date", ""),
                json.dumps(labels),
                int(is_unread),
                msg.get("snippet", "")[:500],
            ),
        )
        count += 1

    db.commit()
    db.close()
    return count


def _parse_email_header(header: str) -> tuple[str, str]:
    """Parse 'Name <email>' format into (name, email)."""
    if "<" in header and ">" in header:
        name = header.split("<")[0].strip().strip('"')
        email = header.split("<")[1].split(">")[0].strip()
        return name, email
    return "", header.strip()
