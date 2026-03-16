"""Microsoft OneDrive connector via Graph API — syncs recent files to drive_files table.

Parallels drive.py but uses Microsoft Graph instead of Google Drive API.
Reuses the same drive_files table since the schema is provider-agnostic.
"""

from datetime import datetime, timedelta, timezone

import httpx

from config import DRIVE_SYNC_DAYS, DRIVE_SYNC_LIMIT
from connectors.microsoft_auth import get_microsoft_token
from database import batch_upsert, get_write_db

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

# Map common Microsoft MIME types to readable forms
_MIME_MAP = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "application/vnd.ms-word",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "application/vnd.ms-powerpoint",
}


def sync_onedrive_files() -> int:
    """Sync recently modified OneDrive files to local database."""
    token = get_microsoft_token()
    headers = {"Authorization": f"Bearer {token}"}

    cutoff = (datetime.now(timezone.utc) - timedelta(days=DRIVE_SYNC_DAYS)).isoformat() + "Z"

    # Phase 1: Fetch from Graph API (no DB connection held)
    all_files: list[dict] = []
    # /me/drive/recent doesn't support $filter, so we fetch and filter client-side
    # Also fetch from /me/drive/root/search to catch shared items
    for endpoint in [
        f"{GRAPH_BASE}/me/drive/recent",
        f"{GRAPH_BASE}/me/drive/root/search(q='')?$top=200&$orderby=lastModifiedDateTime desc",
    ]:
        try:
            resp = httpx.get(
                endpoint,
                headers=headers,
                params={"$top": 200} if "recent" in endpoint else None,
                timeout=30,
            )
            if resp.status_code == 200:
                items = resp.json().get("value", [])
                all_files.extend(items)
        except httpx.HTTPError:
            continue

    if not all_files:
        return 0

    # Deduplicate by id and filter by date
    seen: set[str] = set()
    unique: list[dict] = []
    for f in all_files:
        fid = f.get("id", "")
        if fid in seen:
            continue
        seen.add(fid)
        mod_time = f.get("lastModifiedDateTime", "")
        if mod_time and mod_time >= cutoff:
            unique.append(f)

    unique.sort(key=lambda f: f.get("lastModifiedDateTime", ""), reverse=True)
    unique = unique[:DRIVE_SYNC_LIMIT]

    # Phase 2: Build rows matching drive_files schema
    rows = []
    for f in unique:
        last_mod_by = f.get("lastModifiedBy", {}).get("user", {})
        created_by = f.get("createdBy", {}).get("user", {})
        file_info = f.get("file", {})
        mime = file_info.get("mimeType", f.get("file", {}).get("mimeType", ""))
        mime = _MIME_MAP.get(mime, mime)

        # Folder detection
        if "folder" in f:
            continue  # Skip folders, only sync files

        web_url = f.get("webUrl", "")

        rows.append(
            (
                f"ms_{f['id']}",  # Prefix to avoid ID collisions with Google Drive
                f.get("name", ""),
                mime,
                web_url,
                "",  # icon_link — not provided by Graph
                f.get("createdDateTime", ""),
                f.get("lastModifiedDateTime", ""),
                last_mod_by.get("email", ""),
                last_mod_by.get("displayName", ""),
                created_by.get("email", ""),
                created_by.get("displayName", ""),
                int(bool(f.get("shared"))),  # shared
                0,  # starred — not a OneDrive concept
                0,  # trashed — we only fetch non-deleted
                f.get("parentReference", {}).get("id", ""),
                f.get("parentReference", {}).get("name", ""),
                int(f.get("size", 0) or 0),
                f.get("description", ""),
                "",  # content_preview
                "",  # thumbnail_link
            )
        )

    # Phase 3: Batch upsert
    with get_write_db() as db:
        batch_upsert(
            db,
            """INSERT OR REPLACE INTO drive_files
               (id, name, mime_type, web_view_link, icon_link,
                created_time, modified_time, modified_by_email, modified_by_name,
                owner_email, owner_name, shared, starred, trashed,
                parent_id, parent_name, size_bytes, description,
                content_preview, thumbnail_link)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )

    return len(rows)
