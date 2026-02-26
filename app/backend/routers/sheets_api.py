"""Google Sheets API endpoints — synced sheets listing and live value reading."""

import json
import logging

from fastapi import APIRouter, HTTPException, Query
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

from connectors.google_auth import get_google_credentials
from database import get_db_connection

router = APIRouter(prefix="/api/sheets", tags=["sheets"])


@router.get("")
def get_sheets(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(50, ge=1, le=200),
):
    """Get synced Google Sheets from local DB."""
    cutoff = f"-{days} days"
    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            "SELECT * FROM google_sheets WHERE modified_time >= datetime('now', ?) ORDER BY modified_time DESC LIMIT ?",
            (cutoff, limit),
        ).fetchall()

    sheets = []
    for r in rows:
        d = dict(r)
        # Parse sheet_tabs_json for frontend
        try:
            d["sheet_tabs"] = json.loads(d.get("sheet_tabs_json", "[]"))
        except (json.JSONDecodeError, TypeError):
            d["sheet_tabs"] = []
        sheets.append(d)

    return {"sheets": sheets, "count": len(sheets)}


@router.get("/search")
def search_sheets(
    q: str = Query(..., description="Search query"),
    limit: int = Query(20, ge=1, le=100),
):
    """Search sheets by title from synced data using FTS."""
    with get_db_connection(readonly=True) as db:
        try:
            rows = db.execute(
                """SELECT gs.*, highlight(fts_google_sheets, 0, '<mark>', '</mark>') as title_hl
                   FROM fts_google_sheets
                   JOIN google_sheets gs ON gs.rowid = fts_google_sheets.rowid
                   WHERE fts_google_sheets MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (q, limit),
            ).fetchall()
        except Exception:
            # Fallback to LIKE search if FTS fails
            rows = db.execute(
                "SELECT * FROM google_sheets WHERE title LIKE ? ORDER BY modified_time DESC LIMIT ?",
                (f"%{q}%", limit),
            ).fetchall()

    sheets = []
    for r in rows:
        d = dict(r)
        try:
            d["sheet_tabs"] = json.loads(d.get("sheet_tabs_json", "[]"))
        except (json.JSONDecodeError, TypeError):
            d["sheet_tabs"] = []
        sheets.append(d)

    return {"query": q, "sheets": sheets, "count": len(sheets)}


@router.get("/{sheet_id}")
def get_sheet_detail(sheet_id: str):
    """Get sheet detail with tab info."""
    with get_db_connection(readonly=True) as db:
        row = db.execute("SELECT * FROM google_sheets WHERE id = ?", (sheet_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Sheet not found")
    d = dict(row)
    try:
        d["sheet_tabs"] = json.loads(d.get("sheet_tabs_json", "[]"))
    except (json.JSONDecodeError, TypeError):
        d["sheet_tabs"] = []
    return d


@router.get("/{sheet_id}/values")
def get_sheet_values(
    sheet_id: str,
    range: str = Query("A1:Z20", description="Cell range to read"),
    tab: str | None = Query(None, description="Tab name"),
):
    """Read values from a specific sheet range (live API call)."""
    try:
        creds = get_google_credentials()
        service = build("sheets", "v4", credentials=creds)
    except Exception as e:
        logger.error("Sheets not authenticated: %s", e)
        raise HTTPException(status_code=503, detail="Sheets not authenticated")

    sheet_range = f"'{tab}'!{range}" if tab else range
    try:
        result = service.spreadsheets().values().get(spreadsheetId=sheet_id, range=sheet_range).execute()
    except Exception as e:
        logger.error("Failed to read sheet values: %s", e)
        raise HTTPException(status_code=500, detail="Failed to read sheet values")

    return {"values": result.get("values", []), "range": result.get("range", "")}
