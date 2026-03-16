"""Microsoft Outlook Email connector via Graph API.

Follows the same 3-phase sync pattern as gmail.py:
  Phase 1: Fetch messages from Graph API (no DB lock)
  Phase 2: Normalize into emails table schema
  Phase 3: Batch upsert into DB
"""

import json

import httpx

from config import GMAIL_MAX_RESULTS
from connectors.microsoft_auth import get_microsoft_token
from database import batch_upsert, get_write_db

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def sync_outlook_messages() -> int:
    token = get_microsoft_token()
    headers = {"Authorization": f"Bearer {token}"}

    # Phase 1: Fetch recent inbox messages
    resp = httpx.get(
        f"{GRAPH_BASE}/me/mailFolders/inbox/messages",
        headers=headers,
        params={
            "$top": GMAIL_MAX_RESULTS,
            "$orderby": "receivedDateTime desc",
            "$select": "id,conversationId,subject,bodyPreview,from,toRecipients,receivedDateTime,isRead",
        },
        timeout=30,
    )
    resp.raise_for_status()
    messages = resp.json().get("value", [])
    if not messages:
        return 0

    # Phase 2: Build rows (same schema as Gmail)
    rows = []
    for msg in messages:
        from_info = msg.get("from", {}).get("emailAddress", {})
        to_list = ", ".join(r.get("emailAddress", {}).get("address", "") for r in msg.get("toRecipients", []))

        rows.append(
            (
                msg["id"],
                msg.get("conversationId", ""),  # Maps to thread_id
                msg.get("subject", "(No subject)"),
                msg.get("bodyPreview", ""),
                from_info.get("name", ""),
                from_info.get("address", ""),
                to_list,
                msg.get("receivedDateTime", ""),
                json.dumps([]),  # labels_json — Outlook doesn't use labels
                int(not msg.get("isRead", True)),  # is_unread
                msg.get("bodyPreview", "")[:500],
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


def search_outlook_messages(query: str, max_results: int = 20) -> list[dict]:
    """Live search via Graph API $search."""
    token = get_microsoft_token()
    headers = {"Authorization": f"Bearer {token}"}

    resp = httpx.get(
        f"{GRAPH_BASE}/me/messages",
        headers=headers,
        params={
            "$search": f'"{query}"',
            "$top": max_results,
            "$orderby": "receivedDateTime desc",
            "$select": "id,conversationId,subject,bodyPreview,from,toRecipients,receivedDateTime,isRead,hasAttachments",
        },
        timeout=30,
    )
    resp.raise_for_status()
    messages = resp.json().get("value", [])

    results = []
    for msg in messages:
        from_info = msg.get("from", {}).get("emailAddress", {})
        results.append(
            {
                "id": msg["id"],
                "threadId": msg.get("conversationId", ""),
                "subject": msg.get("subject", "(No subject)"),
                "snippet": msg.get("bodyPreview", ""),
                "from": from_info.get("name", from_info.get("address", "")),
                "from_email": from_info.get("address", ""),
                "date": msg.get("receivedDateTime", ""),
                "isUnread": not msg.get("isRead", True),
                "hasAttachment": msg.get("hasAttachments", False),
            }
        )
    return results


def get_outlook_thread(conversation_id: str) -> list[dict]:
    """Fetch all messages in a conversation (equivalent to Gmail thread)."""
    token = get_microsoft_token()
    headers = {"Authorization": f"Bearer {token}"}

    resp = httpx.get(
        f"{GRAPH_BASE}/me/messages",
        headers=headers,
        params={
            "$filter": f"conversationId eq '{conversation_id}'",
            "$orderby": "receivedDateTime asc",
            "$select": "id,conversationId,subject,body,from,toRecipients,receivedDateTime,isRead",
            "$top": 50,
        },
        timeout=30,
    )
    resp.raise_for_status()
    messages = resp.json().get("value", [])

    results = []
    for msg in messages:
        from_info = msg.get("from", {}).get("emailAddress", {})
        body = msg.get("body", {})
        results.append(
            {
                "id": msg["id"],
                "subject": msg.get("subject", ""),
                "from": from_info.get("name", from_info.get("address", "")),
                "from_email": from_info.get("address", ""),
                "date": msg.get("receivedDateTime", ""),
                "body": body.get("content", ""),
                "contentType": body.get("contentType", "text"),
            }
        )
    return results


def send_outlook_email(to: str, subject: str, body: str, reply_to_message_id: str | None = None) -> dict:
    """Send an email via Graph API."""
    token = get_microsoft_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    if reply_to_message_id:
        # Reply to existing message
        resp = httpx.post(
            f"{GRAPH_BASE}/me/messages/{reply_to_message_id}/reply",
            headers=headers,
            json={"comment": body},
            timeout=30,
        )
    else:
        # New message
        resp = httpx.post(
            f"{GRAPH_BASE}/me/sendMail",
            headers=headers,
            json={
                "message": {
                    "subject": subject,
                    "body": {"contentType": "Text", "content": body},
                    "toRecipients": [{"emailAddress": {"address": to}}],
                },
                "saveToSentItems": True,
            },
            timeout=30,
        )
    resp.raise_for_status()
    return {"status": "sent"}


def get_outlook_drafts() -> list[dict]:
    """List drafts from Outlook."""
    token = get_microsoft_token()
    headers = {"Authorization": f"Bearer {token}"}

    resp = httpx.get(
        f"{GRAPH_BASE}/me/mailFolders/drafts/messages",
        headers=headers,
        params={
            "$top": 20,
            "$orderby": "lastModifiedDateTime desc",
            "$select": "id,subject,bodyPreview,toRecipients,lastModifiedDateTime",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("value", [])


def create_outlook_draft(to: str, subject: str, body: str) -> dict:
    """Create a draft email."""
    token = get_microsoft_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    resp = httpx.post(
        f"{GRAPH_BASE}/me/messages",
        headers=headers,
        json={
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": to}}],
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def archive_outlook_messages(message_ids: list[str]) -> int:
    """Move messages to Archive folder."""
    token = get_microsoft_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    count = 0
    for msg_id in message_ids:
        resp = httpx.post(
            f"{GRAPH_BASE}/me/messages/{msg_id}/move",
            headers=headers,
            json={"destinationId": "archive"},
            timeout=30,
        )
        if resp.status_code < 400:
            count += 1
    return count


def trash_outlook_messages(message_ids: list[str]) -> int:
    """Move messages to Deleted Items."""
    token = get_microsoft_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    count = 0
    for msg_id in message_ids:
        resp = httpx.post(
            f"{GRAPH_BASE}/me/messages/{msg_id}/move",
            headers=headers,
            json={"destinationId": "deleteditems"},
            timeout=30,
        )
        if resp.status_code < 400:
            count += 1
    return count


def get_outlook_all_messages(max_results: int = 50) -> list[dict]:
    """Fetch recent inbox messages (live, for /api/gmail/all equivalent)."""
    token = get_microsoft_token()
    headers = {"Authorization": f"Bearer {token}"}

    resp = httpx.get(
        f"{GRAPH_BASE}/me/mailFolders/inbox/messages",
        headers=headers,
        params={
            "$top": max_results,
            "$orderby": "receivedDateTime desc",
            "$select": "id,conversationId,subject,bodyPreview,from,toRecipients,receivedDateTime,isRead,hasAttachments",
        },
        timeout=30,
    )
    resp.raise_for_status()
    messages = resp.json().get("value", [])

    results = []
    for msg in messages:
        from_info = msg.get("from", {}).get("emailAddress", {})
        results.append(
            {
                "id": msg["id"],
                "threadId": msg.get("conversationId", ""),
                "subject": msg.get("subject", "(No subject)"),
                "snippet": msg.get("bodyPreview", ""),
                "from": from_info.get("name", from_info.get("address", "")),
                "from_email": from_info.get("address", ""),
                "date": msg.get("receivedDateTime", ""),
                "isUnread": not msg.get("isRead", True),
                "labelIds": [],
                "hasAttachment": msg.get("hasAttachments", False),
            }
        )
    return results
