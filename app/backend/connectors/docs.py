"""Google Docs connector — enriches synced Drive documents with content previews.

Uses Drive API files().export() (drive.readonly scope) instead of Docs API,
so no additional OAuth scope is needed.
"""

import logging

import google_auth_httplib2
import httplib2
from googleapiclient.discovery import build

from config import DOCS_SYNC_LIMIT
from connectors.google_auth import get_google_credentials
from database import batch_upsert, get_db_connection, get_write_db

logger = logging.getLogger(__name__)

API_TIMEOUT = 30  # seconds per HTTP request


def sync_docs_data() -> int:
    """Enrich Google Docs with content previews via Drive export.

    Depends on drive.sync_drive_files() having already populated drive_files.
    """
    creds = get_google_credentials()
    authed_http = google_auth_httplib2.AuthorizedHttp(creds, http=httplib2.Http(timeout=API_TIMEOUT))
    drive_service = build("drive", "v3", http=authed_http)

    # Phase 1: Get Doc IDs from drive_files (already synced) and skip unchanged ones
    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            "SELECT id, name, web_view_link, owner_email, owner_name, modified_time "
            "FROM drive_files "
            "WHERE mime_type = 'application/vnd.google-apps.document' "
            "ORDER BY modified_time DESC LIMIT ?",
            (DOCS_SYNC_LIMIT,),
        ).fetchall()

        # Build lookup of already-synced docs to skip unchanged ones
        existing = {
            r["id"]: r["modified_time"]
            for r in db.execute("SELECT id, modified_time FROM google_docs").fetchall()
        }

    if not rows:
        return 0

    drive_lookup = {r["id"]: dict(r) for r in rows}

    # Filter to only docs that are new or have a newer modified_time
    to_fetch = {
        did: df for did, df in drive_lookup.items()
        if did not in existing or existing[did] != df["modified_time"]
    }
    skipped = len(drive_lookup) - len(to_fetch)
    if skipped:
        logger.info("Docs sync: skipping %d unchanged docs", skipped)

    # Phase 2: Export document content as plain text via Drive API
    enriched = []
    preview_updates = []
    for i, (did, df) in enumerate(to_fetch.items(), 1):
        try:
            logger.info("Docs sync: %d/%d — %s", i, len(to_fetch), did)
            content = drive_service.files().export(fileId=did, mimeType="text/plain").execute()
            if isinstance(content, bytes):
                content = content.decode("utf-8", errors="replace")
            content_preview = content[:1000].strip()
            word_count = len(content_preview.split())

            # Title is already in drive_files — no extra API call needed
            title = df.get("name", "Untitled")

            enriched.append(
                (
                    did,
                    title,
                    df.get("web_view_link", ""),
                    df.get("owner_email", ""),
                    df.get("owner_name", ""),
                    df.get("modified_time", ""),
                    content_preview,
                    word_count,
                )
            )

            # Also update drive_files content_preview
            preview_updates.append((content_preview[:500], did))
        except Exception:
            continue

    # Phase 3: Batch upsert docs
    with get_write_db() as db:
        batch_upsert(
            db,
            """INSERT OR REPLACE INTO google_docs
               (id, title, web_view_link, owner_email, owner_name,
                modified_time, content_preview, word_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            enriched,
        )

    # Update drive_files content_preview for Docs
    if preview_updates:
        with get_write_db() as db:
            for preview, did in preview_updates:
                db.execute(
                    "UPDATE drive_files SET content_preview = ? WHERE id = ?",
                    (preview, did),
                )
            db.commit()

    return len(enriched)
