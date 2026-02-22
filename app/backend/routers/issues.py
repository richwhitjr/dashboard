import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from database import get_db_connection, get_write_db, rebuild_fts_table
from models import IssueCreate, IssueUpdate
from utils.safe_sql import safe_update_query

ISSUE_ALLOWED_COLUMNS = {"title", "description", "priority", "tshirt_size", "status"}

router = APIRouter(prefix="/api/issues", tags=["issues"])

VALID_SIZES = {"s", "m", "l", "xl"}
VALID_STATUSES = {"open", "in_progress", "done"}


def _resolve_mentions(text: str, db) -> list[str]:
    """Find all @mentioned employees in text. Returns list of employee IDs."""
    rows = db.execute("SELECT id, name FROM employees").fetchall()
    mentions = re.findall(r"@(\w+(?:\s+\w+)?)", text)
    matched_ids = []
    seen = set()
    for mention in mentions:
        mention_lower = mention.lower()
        for row in rows:
            if row["id"] in seen:
                continue
            name = row["name"]
            first = name.split()[0].lower()
            last = name.split()[-1].lower() if len(name.split()) > 1 else ""
            if (
                name.lower() == mention_lower
                or name.lower().startswith(mention_lower)
                or first == mention_lower.split()[0]
                or (last and last == mention_lower.split()[0])
            ):
                matched_ids.append(row["id"])
                seen.add(row["id"])
                break
    return matched_ids


def _get_issue_employees(db, issue_id: int) -> list[dict]:
    rows = db.execute(
        "SELECT e.id, e.name FROM issue_employees ie JOIN employees e ON ie.employee_id = e.id WHERE ie.issue_id = ?",
        (issue_id,),
    ).fetchall()
    return [{"id": r["id"], "name": r["name"]} for r in rows]


def _set_issue_employees(db, issue_id: int, employee_ids: list[str]):
    db.execute("DELETE FROM issue_employees WHERE issue_id = ?", (issue_id,))
    for eid in employee_ids:
        db.execute(
            "INSERT OR IGNORE INTO issue_employees (issue_id, employee_id) VALUES (?, ?)",
            (issue_id, eid),
        )


def _get_issue_meetings(db, issue_id: int) -> list[dict]:
    rows = db.execute(
        "SELECT meeting_ref_type, meeting_ref_id FROM issue_meetings WHERE issue_id = ?",
        (issue_id,),
    ).fetchall()
    meetings = []
    for r in rows:
        ref_type = r["meeting_ref_type"]
        ref_id = r["meeting_ref_id"]
        summary = ""
        start_time = None
        if ref_type == "calendar":
            ev = db.execute("SELECT summary, start_time FROM calendar_events WHERE id = ?", (ref_id,)).fetchone()
            if ev:
                summary = ev["summary"] or ""
                start_time = ev["start_time"]
        elif ref_type == "granola":
            gm = db.execute("SELECT title, created_at FROM granola_meetings WHERE id = ?", (ref_id,)).fetchone()
            if gm:
                summary = gm["title"] or ""
                start_time = gm["created_at"]
        meetings.append(
            {
                "ref_type": ref_type,
                "ref_id": ref_id,
                "summary": summary,
                "start_time": start_time,
            }
        )
    return meetings


def _set_issue_meetings(db, issue_id: int, meeting_ids: list[dict]):
    db.execute("DELETE FROM issue_meetings WHERE issue_id = ?", (issue_id,))
    for m in meeting_ids:
        ref_type = m.get("ref_type", "calendar")
        ref_id = m.get("ref_id", "")
        if ref_type and ref_id:
            db.execute(
                "INSERT OR IGNORE INTO issue_meetings (issue_id, meeting_ref_type, meeting_ref_id) VALUES (?, ?, ?)",
                (issue_id, ref_type, ref_id),
            )


def _issue_to_dict(db, row) -> dict:
    issue = dict(row)
    issue["employees"] = _get_issue_employees(db, issue["id"])
    issue["meetings"] = _get_issue_meetings(db, issue["id"])
    return issue


@router.get("")
def list_issues(
    status: Optional[str] = Query(None),
    employee_id: Optional[str] = Query(None),
    priority: Optional[int] = Query(None),
    tshirt_size: Optional[str] = Query(None),
):
    with get_db_connection(readonly=True) as db:
        if employee_id:
            query = (
                "SELECT DISTINCT i.* FROM issues i"
                " JOIN issue_employees ie ON i.id = ie.issue_id"
                " WHERE ie.employee_id = ?"
            )
            params: list = [employee_id]
        else:
            query = "SELECT i.* FROM issues i WHERE 1=1"
            params = []

        if status:
            query += " AND i.status = ?"
            params.append(status)
        if priority is not None:
            query += " AND i.priority = ?"
            params.append(priority)
        if tshirt_size:
            query += " AND i.tshirt_size = ?"
            params.append(tshirt_size)

        query += (
            " ORDER BY CASE i.status WHEN 'open' THEN 0 WHEN 'in_progress' THEN 1 ELSE 2 END,"
            " i.priority ASC, i.updated_at DESC"
        )

        rows = db.execute(query, params).fetchall()
        result = [_issue_to_dict(db, r) for r in rows]
    return result


@router.post("")
def create_issue(issue: IssueCreate):
    size = issue.tshirt_size.lower()
    if size not in VALID_SIZES:
        size = "m"
    priority = max(0, min(3, issue.priority))

    with get_write_db() as db:
        # Resolve @mentions from title
        employee_ids = issue.employee_ids or []
        if not employee_ids:
            detected = _resolve_mentions(issue.title, db)
            if detected:
                employee_ids = detected

        cursor = db.execute(
            "INSERT INTO issues (title, description, priority, tshirt_size, status) VALUES (?, ?, ?, ?, ?)",
            (issue.title, issue.description, priority, size, "open"),
        )
        issue_id = cursor.lastrowid

        for eid in employee_ids:
            db.execute(
                "INSERT OR IGNORE INTO issue_employees (issue_id, employee_id) VALUES (?, ?)",
                (issue_id, eid),
            )

        if issue.meeting_ids:
            for m in issue.meeting_ids:
                ref_type = m.get("ref_type", "calendar")
                ref_id = m.get("ref_id", "")
                if ref_type and ref_id:
                    db.execute(
                        "INSERT OR IGNORE INTO issue_meetings "
                        "(issue_id, meeting_ref_type, meeting_ref_id) VALUES (?, ?, ?)",
                        (issue_id, ref_type, ref_id),
                    )

        db.commit()
        row = db.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
        result = _issue_to_dict(db, row)
    rebuild_fts_table("fts_issues")
    return result


@router.get("/search-meetings")
def search_meetings(
    q: str = Query("", description="Search query for meeting titles"),
    limit: int = Query(10, ge=1, le=50),
):
    pattern = f"%{q}%"
    results = []

    with get_db_connection(readonly=True) as db:
        # Search calendar events
        cal_rows = db.execute(
            "SELECT id, summary, start_time FROM calendar_events WHERE summary LIKE ? ORDER BY start_time DESC LIMIT ?",
            (pattern, limit),
        ).fetchall()
        for r in cal_rows:
            results.append(
                {
                    "ref_type": "calendar",
                    "ref_id": r["id"],
                    "summary": r["summary"] or "",
                    "start_time": r["start_time"],
                }
            )

        # Search granola meetings
        gran_rows = db.execute(
            "SELECT id, title, created_at FROM granola_meetings "
            "WHERE title LIKE ? AND valid_meeting = 1 ORDER BY created_at DESC LIMIT ?",
            (pattern, limit),
        ).fetchall()
        for r in gran_rows:
            results.append(
                {
                    "ref_type": "granola",
                    "ref_id": r["id"],
                    "summary": r["title"] or "",
                    "start_time": r["created_at"],
                }
            )

    return results


@router.get("/{issue_id}")
def get_issue(issue_id: int):
    with get_db_connection(readonly=True) as db:
        row = db.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Issue not found")
        result = _issue_to_dict(db, row)
    return result


@router.patch("/{issue_id}")
def update_issue(issue_id: int, update: IssueUpdate):
    with get_write_db() as db:
        existing = db.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Issue not found")

        new_employee_ids = update.employee_ids
        new_meeting_ids = update.meeting_ids

        update_fields = {}
        for field, value in update.model_dump(exclude_unset=True).items():
            if field in ("employee_ids", "meeting_ids"):
                continue
            if field == "tshirt_size" and value is not None:
                value = value.lower()
                if value not in VALID_SIZES:
                    continue
            if field == "priority" and value is not None:
                value = max(0, min(3, value))
            if field == "status" and value is not None:
                if value not in VALID_STATUSES:
                    continue
            update_fields[field] = value

        # Auto-set completed_at
        extra = ["updated_at = ?"]
        extra_params = [datetime.now().isoformat()]
        if update.status == "done" and existing["status"] != "done":
            extra.append("completed_at = ?")
            extra_params.append(datetime.now().isoformat())
        elif update.status and update.status != "done":
            extra.append("completed_at = ?")
            extra_params.append(None)

        set_clause, params = safe_update_query("issues", update_fields, ISSUE_ALLOWED_COLUMNS, extra)
        params.extend(extra_params)
        params.append(issue_id)
        db.execute(f"UPDATE issues SET {set_clause} WHERE id = ?", params)

        if new_employee_ids is not None:
            _set_issue_employees(db, issue_id, new_employee_ids)

        if new_meeting_ids is not None:
            _set_issue_meetings(db, issue_id, new_meeting_ids)

        db.commit()
        row = db.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
        result = _issue_to_dict(db, row)
    rebuild_fts_table("fts_issues")
    return result


@router.delete("/{issue_id}")
def delete_issue(issue_id: int):
    with get_write_db() as db:
        db.execute("DELETE FROM issues WHERE id = ?", (issue_id,))
        db.commit()
    rebuild_fts_table("fts_issues")
    return {"ok": True}
