"""Google Sheets API connector — enriches synced Drive spreadsheets with tab metadata."""

import json
import logging

import google_auth_httplib2
import httplib2
from googleapiclient.discovery import build

from config import SHEETS_SYNC_LIMIT
from connectors.google_auth import get_google_credentials
from database import batch_upsert, get_db_connection, get_write_db

logger = logging.getLogger(__name__)

API_TIMEOUT = 30  # seconds per HTTP request


def sync_sheets_data() -> int:
    """Enrich Google Sheets with tab metadata from Sheets API v4.

    Depends on drive.sync_drive_files() having already populated drive_files.
    """
    creds = get_google_credentials()
    authed_http = google_auth_httplib2.AuthorizedHttp(creds, http=httplib2.Http(timeout=API_TIMEOUT))
    sheets_service = build("sheets", "v4", http=authed_http)

    # Phase 1: Get Sheet IDs from drive_files (already synced) and skip unchanged ones
    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            "SELECT id, web_view_link, owner_email, owner_name, modified_time "
            "FROM drive_files "
            "WHERE mime_type = 'application/vnd.google-apps.spreadsheet' "
            "ORDER BY modified_time DESC LIMIT ?",
            (SHEETS_SYNC_LIMIT,),
        ).fetchall()

        # Build lookup of already-synced sheets to skip unchanged ones
        existing = {
            r["id"]: r["modified_time"]
            for r in db.execute("SELECT id, modified_time FROM google_sheets").fetchall()
        }

    if not rows:
        return 0

    drive_lookup = {r["id"]: dict(r) for r in rows}

    # Filter to only sheets that are new or have a newer modified_time
    to_fetch = {
        sid: df for sid, df in drive_lookup.items()
        if sid not in existing or existing[sid] != df["modified_time"]
    }
    skipped = len(drive_lookup) - len(to_fetch)
    if skipped:
        logger.info("Sheets sync: skipping %d unchanged sheets", skipped)

    # Phase 2: Fetch detailed metadata for changed sheets only
    enriched = []
    for i, (sid, df) in enumerate(to_fetch.items(), 1):
        try:
            logger.info("Sheets sync: %d/%d — %s", i, len(to_fetch), sid)
            meta = sheets_service.spreadsheets().get(spreadsheetId=sid, fields="properties,sheets.properties").execute()

            props = meta.get("properties", {})
            tabs = []
            for sheet in meta.get("sheets", []):
                sp = sheet.get("properties", {})
                grid = sp.get("gridProperties", {})
                tabs.append(
                    {
                        "name": sp.get("title", ""),
                        "rowCount": grid.get("rowCount", 0),
                        "colCount": grid.get("columnCount", 0),
                    }
                )

            enriched.append(
                (
                    sid,
                    props.get("title", "Untitled"),
                    df.get("web_view_link", ""),
                    df.get("owner_email", ""),
                    df.get("owner_name", ""),
                    df.get("modified_time", ""),
                    json.dumps(tabs),
                    props.get("locale", ""),
                    props.get("timeZone", ""),
                )
            )
        except Exception:
            continue

    # Phase 3: Batch upsert
    with get_write_db() as db:
        batch_upsert(
            db,
            """INSERT OR REPLACE INTO google_sheets
               (id, title, web_view_link, owner_email, owner_name,
                modified_time, sheet_tabs_json, locale, time_zone)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            enriched,
        )

    return len(enriched)
