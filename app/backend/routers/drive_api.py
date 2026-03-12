"""Google Drive API endpoints — synced files, live search, Docs listing, and LLM prioritization."""

import json
import logging
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from googleapiclient.discovery import build

from app_config import get_prompt_context
from connectors.google_auth import get_google_credentials
from database import get_db_connection, get_write_db
from models import GoogleDocAppend, GoogleDocCreate
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
            "SELECT * FROM drive_files WHERE trashed = 0 ORDER BY modified_time DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        total = db.execute("SELECT COUNT(*) as c FROM drive_files WHERE trashed = 0").fetchone()["c"]
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


# --- Docs write endpoints ---


@router.post("/docs")
def create_doc(doc: GoogleDocCreate):
    """Create a new Google Doc."""
    try:
        creds = get_google_credentials()
        docs_service = build("docs", "v1", credentials=creds)
    except Exception as e:
        logger.error("Google Docs not authenticated: %s", e)
        raise HTTPException(status_code=503, detail="Google Docs not authenticated")

    try:
        result = docs_service.documents().create(body={"title": doc.title}).execute()
        doc_id = result["documentId"]

        if doc.body:
            docs_service.documents().batchUpdate(
                documentId=doc_id,
                body={"requests": [{"insertText": {"location": {"index": 1}, "text": doc.body}}]},
            ).execute()

        if doc.folder_id:
            drive_service = _get_service()
            drive_service.files().update(
                fileId=doc_id,
                addParents=doc.folder_id,
                fields="id, parents",
            ).execute()
    except Exception as e:
        logger.error("Failed to create Google Doc: %s", e)
        raise HTTPException(status_code=500, detail="Failed to create Google Doc")

    return {
        "id": doc_id,
        "title": doc.title,
        "url": f"https://docs.google.com/document/d/{doc_id}/edit",
    }


@router.post("/docs/{doc_id}/append")
def append_to_doc(doc_id: str, body: GoogleDocAppend):
    """Append text to the end of a Google Doc."""
    try:
        creds = get_google_credentials()
        docs_service = build("docs", "v1", credentials=creds)
    except Exception as e:
        logger.error("Google Docs not authenticated: %s", e)
        raise HTTPException(status_code=503, detail="Google Docs not authenticated")

    try:
        doc = docs_service.documents().get(documentId=doc_id).execute()
        end_index = doc["body"]["content"][-1]["endIndex"] - 1

        docs_service.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": [{"insertText": {"location": {"index": end_index}, "text": "\n" + body.text}}]},
        ).execute()
    except Exception as e:
        logger.error("Failed to append to doc: %s", e)
        raise HTTPException(status_code=500, detail="Failed to append to document")

    return {"ok": True, "doc_id": doc_id}


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
    """Rank Drive files by priority using the configured AI provider."""
    from ai_client import generate

    now = datetime.now().strftime("%A, %B %d %Y, %I:%M %p")
    user_message = f"Current time: {now}\n\nDrive files to rank:\n{json.dumps(files, default=str)}"

    text = generate(system_prompt=_build_drive_rank_prompt(), user_message=user_message, json_mode=True)
    if not text:
        return []

    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def _dismissed_drive_ids(db) -> set[str]:
    rows = db.execute("SELECT item_id FROM dismissed_dashboard_items WHERE source = 'drive'").fetchall()
    return {r["item_id"] for r in rows}


def rerank_drive(days: int = 30) -> bool:
    """Rerank Drive items — updates cache if data changed. Returns True if cache was updated."""
    from routers._ranking_cache import finish_reranking, start_reranking

    if not start_reranking("drive"):
        return False
    try:
        return _do_rerank_drive(days)
    finally:
        finish_reranking("drive")


def _do_rerank_drive(days: int = 30) -> bool:
    cutoff = f"-{days} days"
    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            "SELECT id, name, mime_type, web_view_link, modified_time, "
            "modified_by_name, owner_name, shared, starred, description, content_preview "
            "FROM drive_files "
            "WHERE modified_time >= datetime('now', ?) AND trashed = 0 "
            "ORDER BY modified_time DESC LIMIT 100",
            (cutoff,),
        ).fetchall()

    if not rows:
        return False

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

    items_hash = compute_items_hash(files_for_llm)
    with get_db_connection(readonly=True) as db:
        cached = db.execute("SELECT data_hash FROM cached_drive_priorities ORDER BY id DESC LIMIT 1").fetchone()
        if cached and cached["data_hash"] == items_hash:
            return False

    logger.info("Drive rerank — calling AI (%d files)", len(files_for_llm))
    try:
        ranked = _rank_drive_with_gemini(files_for_llm)
    except Exception as e:
        logger.error("Drive rerank failed: %s", e)
        return False

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

    items.sort(key=lambda x: x["priority_score"], reverse=True)
    items = items[:50]

    if not items:
        logger.warning("Drive rerank produced 0 items — not caching empty result")
        return False

    result = {"items": items}

    with get_write_db() as db:
        db.execute("DELETE FROM cached_drive_priorities")
        db.execute(
            "INSERT INTO cached_drive_priorities (data_json, data_hash) VALUES (?, ?)",
            (json.dumps(result, default=str), items_hash),
        )
        db.commit()

    logger.info("Drive rerank complete — %d items cached", len(items))
    return True


@router.get("/prioritized")
def get_prioritized_drive(
    refresh: bool = Query(False),
    days: int = Query(30, ge=1, le=365),
    background_tasks: BackgroundTasks = None,
):
    """Return Drive files ranked by Gemini priority score."""
    from routers._ranking_cache import is_reranking

    with get_db_connection(readonly=True) as db:
        dismissed = _dismissed_drive_ids(db)
        cached = db.execute(
            "SELECT data_json, generated_at FROM cached_drive_priorities ORDER BY id DESC LIMIT 1"
        ).fetchone()

    if cached:
        data = json.loads(cached["data_json"])
        data["items"] = [item for item in data.get("items", []) if item["id"] not in dismissed]

        if not refresh:
            return data

        if background_tasks and not is_reranking("drive"):
            background_tasks.add_task(rerank_drive, days)
        data["stale"] = True
        return data

    # No cache — synchronous first-time ranking
    result = _do_rerank_drive(days)
    if not result:
        return {"items": [], "error": "No Drive files synced yet"}

    with get_db_connection(readonly=True) as db:
        cached = db.execute("SELECT data_json FROM cached_drive_priorities ORDER BY id DESC LIMIT 1").fetchone()
        if cached:
            data = json.loads(cached["data_json"])
            data["items"] = [item for item in data.get("items", []) if item["id"] not in dismissed]
            return data

    return {"items": []}
