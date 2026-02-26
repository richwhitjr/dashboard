"""Google Drive API endpoints — synced files, live search, Docs listing, and LLM prioritization."""

import json
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from googleapiclient.discovery import build

from app_config import get_prompt_context, get_secret
from connectors.google_auth import get_google_credentials
from database import get_db_connection, get_write_db
from routers._ranking_cache import compute_items_hash

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/drive", tags=["drive"])


def _get_service():
    try:
        creds = get_google_credentials()
        return build("drive", "v3", credentials=creds)
    except Exception as e:
        logger.error("Drive not authenticated: %s", e)
        raise HTTPException(status_code=503, detail="Drive not authenticated")


# --- Synced data endpoints ---


@router.get("/all")
def get_all_drive_files(
    offset: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
):
    """Return all synced Drive files, newest first, with pagination."""
    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            "SELECT * FROM drive_files WHERE trashed = 0 "
            "ORDER BY modified_time DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        total = db.execute(
            "SELECT COUNT(*) as c FROM drive_files WHERE trashed = 0"
        ).fetchone()["c"]
    return {
        "items": [dict(r) for r in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < total,
    }


@router.get("/files")
def get_drive_files(
    mime_type: str | None = Query(None, description="Filter by MIME type"),
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(50, ge=1, le=200),
):
    """Get synced Drive files from local DB."""
    cutoff = f"-{days} days"
    with get_db_connection(readonly=True) as db:
        if mime_type:
            rows = db.execute(
                "SELECT * FROM drive_files "
                "WHERE mime_type = ? AND modified_time >= datetime('now', ?) AND trashed = 0 "
                "ORDER BY modified_time DESC LIMIT ?",
                (mime_type, cutoff, limit),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM drive_files "
                "WHERE modified_time >= datetime('now', ?) AND trashed = 0 "
                "ORDER BY modified_time DESC LIMIT ?",
                (cutoff, limit),
            ).fetchall()
    return {"files": [dict(r) for r in rows], "count": len(rows)}


@router.get("/files/{file_id}")
def get_drive_file(file_id: str):
    """Get details for a single Drive file, joining enrichment tables if applicable."""
    with get_db_connection(readonly=True) as db:
        row = db.execute("SELECT * FROM drive_files WHERE id = ?", (file_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="File not found")
        result = dict(row)

        # Enrich with Sheets metadata if applicable
        if result.get("mime_type") == "application/vnd.google-apps.spreadsheet":
            sheet = db.execute("SELECT * FROM google_sheets WHERE id = ?", (file_id,)).fetchone()
            if sheet:
                result["sheet_detail"] = dict(sheet)

        # Enrich with Docs metadata if applicable
        if result.get("mime_type") == "application/vnd.google-apps.document":
            doc = db.execute("SELECT * FROM google_docs WHERE id = ?", (file_id,)).fetchone()
            if doc:
                result["doc_detail"] = dict(doc)

    return result


@router.get("/docs")
def get_docs(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(50, ge=1, le=200),
):
    """Get synced Google Docs from local DB."""
    cutoff = f"-{days} days"
    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            "SELECT * FROM google_docs WHERE modified_time >= datetime('now', ?) ORDER BY modified_time DESC LIMIT ?",
            (cutoff, limit),
        ).fetchall()
    return {"docs": [dict(r) for r in rows], "count": len(rows)}


@router.get("/docs/{doc_id}")
def get_doc_detail(doc_id: str):
    """Get doc detail with content preview."""
    with get_db_connection(readonly=True) as db:
        row = db.execute("SELECT * FROM google_docs WHERE id = ?", (doc_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Doc not found")
    return dict(row)


# --- Live search endpoint ---


@router.get("/search")
def search_drive(
    q: str = Query(..., description="Search query"),
    max_results: int = Query(20, ge=1, le=100),
):
    """Search Drive using Google API directly."""
    service = _get_service()
    try:
        # Escape backslashes first, then single quotes for Drive API query language
        safe_q = q.replace("\\", "\\\\").replace("'", "\\'")
        results = (
            service.files()
            .list(
                q=f"fullText contains '{safe_q}' and trashed = false",
                fields="files(id, name, mimeType, webViewLink, modifiedTime, owners, lastModifyingUser)",
                orderBy="modifiedTime desc",
                pageSize=max_results,
            )
            .execute()
        )
    except Exception as e:
        logger.error("Drive search failed: %s", e)
        raise HTTPException(status_code=500, detail="Drive search failed")

    files = []
    for f in results.get("files", []):
        owners = f.get("owners", [{}])
        owner = owners[0] if owners else {}
        last_mod = f.get("lastModifyingUser", {})
        files.append(
            {
                "id": f["id"],
                "name": f.get("name", ""),
                "mime_type": f.get("mimeType", ""),
                "web_view_link": f.get("webViewLink", ""),
                "modified_time": f.get("modifiedTime", ""),
                "owner_name": owner.get("displayName", ""),
                "owner_email": owner.get("emailAddress", ""),
                "modified_by_name": last_mod.get("displayName", ""),
            }
        )

    return {"query": q, "count": len(files), "files": files}


# --- LLM Prioritized endpoint ---


def _build_drive_rank_prompt() -> str:
    ctx = get_prompt_context()
    return f"""\
You are a priority-ranking assistant {ctx}. You will receive a list of \
recently modified Google Drive files. Rank them by importance/relevance.

For each file, assign a priority_score from 1-10 where:
- 10: Critical docs needing immediate attention (active project specs, shared with execs)
- 7-9: High priority (recent collaborations, docs you own being edited by others)
- 4-6: Medium (reference material, older edits)
- 1-3: Low (auto-generated files, templates, old drafts)

Consider:
1. Files modified very recently are more relevant
2. Files shared/edited by the user's team or reports are high priority
3. Google Docs and Sheets actively being collaborated on score higher
4. Large files recently shared with the user indicate important content
5. Presentations and specs for upcoming meetings are high priority

Return ONLY valid JSON — an array of objects with keys: id, priority_score, reason (one short sentence).
Order by priority_score descending. Return ALL files provided, scored."""


def _rank_drive_with_gemini(files: list[dict]) -> list[dict]:
    """Call Gemini to rank Drive files by priority."""
    api_key = get_secret("GEMINI_API_KEY") or ""
    if not api_key:
        return []

    from google import genai

    client = genai.Client(api_key=api_key)
    now = datetime.now().strftime("%A, %B %d %Y, %I:%M %p")
    user_message = f"Current time: {now}\n\nDrive files to rank:\n{json.dumps(files, default=str)}"

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=user_message,
        config={
            "system_instruction": _build_drive_rank_prompt(),
            "temperature": 0.2,
            "response_mime_type": "application/json",
        },
    )

    try:
        items = json.loads(response.text)
        if isinstance(items, list):
            return items
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def _dismissed_drive_ids(db) -> set[str]:
    rows = db.execute("SELECT item_id FROM dismissed_dashboard_items WHERE source = 'drive'").fetchall()
    return {r["item_id"] for r in rows}


@router.get("/prioritized")
def get_prioritized_drive(refresh: bool = Query(False), days: int = Query(30, ge=1, le=365)):
    """Return Drive files ranked by Gemini priority score."""
    with get_db_connection(readonly=True) as db:
        dismissed = _dismissed_drive_ids(db)
        cutoff = f"-{days} days"

        # Check cache first
        if not refresh:
            cached = db.execute(
                "SELECT data_json, generated_at FROM cached_drive_priorities ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if cached:
                data = json.loads(cached["data_json"])
                data["items"] = [item for item in data.get("items", []) if item["id"] not in dismissed]
                return data

        # Fetch recent files from DB
        rows = db.execute(
            "SELECT id, name, mime_type, web_view_link, modified_time, "
            "modified_by_name, owner_name, shared, starred, description, content_preview "
            "FROM drive_files "
            "WHERE modified_time >= datetime('now', ?) AND trashed = 0 "
            "ORDER BY modified_time DESC LIMIT 100",
            (cutoff,),
        ).fetchall()

    if not rows:
        return {"items": [], "error": "No Drive files synced yet"}

    files_for_llm = []
    file_lookup = {}
    for r in rows:
        rd = dict(r)
        files_for_llm.append(
            {
                "id": rd["id"],
                "name": rd["name"],
                "mime_type": rd["mime_type"],
                "modified_time": rd["modified_time"],
                "modified_by_name": rd["modified_by_name"],
                "owner_name": rd["owner_name"],
                "shared": bool(rd["shared"]),
                "description": (rd["description"] or "")[:200],
                "content_preview": (rd["content_preview"] or "")[:200],
            }
        )
        file_lookup[rd["id"]] = rd

    # Check if input data has changed since last ranking
    items_hash = compute_items_hash(files_for_llm)
    with get_db_connection(readonly=True) as db:
        cached = db.execute(
            "SELECT data_json, data_hash FROM cached_drive_priorities ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if cached and cached["data_hash"] == items_hash:
            logger.info("Drive ranking cache hit (hash match)")
            data = json.loads(cached["data_json"])
            data["items"] = [item for item in data.get("items", []) if item["id"] not in dismissed]
            return data

    logger.info("Drive ranking cache miss — calling Gemini (%d files)", len(files_for_llm))
    try:
        ranked = _rank_drive_with_gemini(files_for_llm)
    except Exception as e:
        logger.error("Drive ranking failed: %s", e)
        return {"items": [], "error": "Ranking service unavailable"}

    # Merge rankings with file data
    items = []
    for rank in ranked:
        fid = rank.get("id", "")
        file_data = file_lookup.get(fid)
        if not file_data:
            continue
        items.append(
            {
                **file_data,
                "priority_score": rank.get("priority_score", 5),
                "priority_reason": rank.get("reason", ""),
            }
        )

    # Sort by score desc, filter dismissed, take top 50
    items.sort(key=lambda x: x["priority_score"], reverse=True)
    items = [i for i in items if i["id"] not in dismissed][:50]

    result = {"items": items}

    # Cache result with hash
    with get_write_db() as db:
        db.execute("DELETE FROM cached_drive_priorities")
        db.execute(
            "INSERT INTO cached_drive_priorities (data_json, data_hash) VALUES (?, ?)",
            (json.dumps(result, default=str), items_hash),
        )
        db.commit()

    return result
