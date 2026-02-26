import json
import logging
import re
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

from fastapi import APIRouter, HTTPException, Query

from database import get_db_connection, get_write_db, rebuild_fts_table
from models import IssueCreate, IssueUpdate
from utils.safe_sql import safe_update_query

ISSUE_ALLOWED_COLUMNS = {"title", "description", "priority", "tshirt_size", "status", "project_id", "due_date"}

router = APIRouter(prefix="/api/issues", tags=["issues"])

VALID_SIZES = {"s", "m", "l", "xl"}
VALID_STATUSES = {"open", "in_progress", "done"}

SORT_COLUMNS = {
    "priority": "i.priority",
    "size": "CASE i.tshirt_size WHEN 's' THEN 0 WHEN 'm' THEN 1 WHEN 'l' THEN 2 WHEN 'xl' THEN 3 END",
    "created_at": "i.created_at",
    "due_date": "i.due_date",
    "updated_at": "i.updated_at",
}


def _resolve_mentions(text: str, db) -> list[str]:
    """Find all @mentioned people in text. Returns list of person IDs."""
    rows = db.execute("SELECT id, name FROM people").fetchall()
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


def _get_issue_people(db, issue_id: int) -> list[dict]:
    rows = db.execute(
        "SELECT p.id, p.name FROM issue_people ip JOIN people p ON ip.person_id = p.id WHERE ip.issue_id = ?",
        (issue_id,),
    ).fetchall()
    return [{"id": r["id"], "name": r["name"]} for r in rows]


def _set_issue_people(db, issue_id: int, person_ids: list[str]):
    db.execute("DELETE FROM issue_people WHERE issue_id = ?", (issue_id,))
    for pid in person_ids:
        db.execute(
            "INSERT OR IGNORE INTO issue_people (issue_id, person_id) VALUES (?, ?)",
            (issue_id, pid),
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


def _get_issue_tags(db, issue_id: int) -> list[str]:
    rows = db.execute("SELECT tag FROM issue_tags WHERE issue_id = ? ORDER BY tag", (issue_id,)).fetchall()
    return [r["tag"] for r in rows]


def _set_issue_tags(db, issue_id: int, tags: list[str]):
    db.execute("DELETE FROM issue_tags WHERE issue_id = ?", (issue_id,))
    for tag in tags:
        tag = tag.strip().lower()
        if tag:
            db.execute("INSERT OR IGNORE INTO issue_tags (issue_id, tag) VALUES (?, ?)", (issue_id, tag))


def _issue_to_dict(db, row) -> dict:
    issue = dict(row)
    people = _get_issue_people(db, issue["id"])
    issue["people"] = people
    issue["employees"] = people  # backward compat
    issue["meetings"] = _get_issue_meetings(db, issue["id"])
    issue["tags"] = _get_issue_tags(db, issue["id"])
    # Resolve project name
    if issue.get("project_id"):
        proj = db.execute("SELECT name FROM projects WHERE id = ?", (issue["project_id"],)).fetchone()
        issue["project_name"] = proj["name"] if proj else None
    else:
        issue["project_name"] = None
    return issue


@router.get("/tags")
def list_tags():
    """Return all distinct tags for autocomplete."""
    with get_db_connection(readonly=True) as db:
        rows = db.execute("SELECT DISTINCT tag FROM issue_tags ORDER BY tag").fetchall()
    return [r["tag"] for r in rows]


@router.get("")
def list_issues(
    status: Optional[str] = Query(None),
    person_id: Optional[str] = Query(None, alias="person_id"),
    employee_id: Optional[str] = Query(None, alias="employee_id"),
    priority: Optional[int] = Query(None),
    tshirt_size: Optional[str] = Query(None),
    project_id: Optional[int] = Query(None),
    tag: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    sort_by: Optional[str] = Query(None),
    sort_dir: Optional[str] = Query("asc"),
):
    pid = person_id or employee_id
    with get_db_connection(readonly=True) as db:
        need_distinct = False

        if pid:
            query = (
                "SELECT DISTINCT i.* FROM issues i JOIN issue_people ip ON i.id = ip.issue_id WHERE ip.person_id = ?"
            )
            params: list = [pid]
            need_distinct = True
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
        if project_id is not None:
            query += " AND i.project_id = ?"
            params.append(project_id)

        # Tag filter (requires JOIN)
        if tag:
            if not need_distinct:
                query = query.replace("SELECT i.* FROM issues i", "SELECT DISTINCT i.* FROM issues i")
            query = query.replace(" WHERE ", " JOIN issue_tags it ON i.id = it.issue_id WHERE ")
            query += " AND it.tag = ?"
            params.append(tag.lower())

        # FTS search
        if search:
            fts_rows = db.execute("SELECT rowid FROM fts_issues WHERE fts_issues MATCH ?", (search,)).fetchall()
            fts_ids = [r["rowid"] for r in fts_rows]
            if not fts_ids:
                return []
            placeholders = ",".join("?" * len(fts_ids))
            query += f" AND i.id IN ({placeholders})"
            params.extend(fts_ids)

        # Sorting
        if sort_by and sort_by in SORT_COLUMNS:
            direction = "DESC" if sort_dir == "desc" else "ASC"
            # For due_date, put NULLs last
            if sort_by == "due_date":
                col = SORT_COLUMNS[sort_by]
                query += f" ORDER BY CASE WHEN i.due_date IS NULL THEN 1 ELSE 0 END, {col} {direction}"
            else:
                query += f" ORDER BY {SORT_COLUMNS[sort_by]} {direction}"
        else:
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
        person_ids = issue.person_ids or []
        if not person_ids:
            detected = _resolve_mentions(issue.title, db)
            if detected:
                person_ids = detected

        cursor = db.execute(
            "INSERT INTO issues (title, description, priority, tshirt_size, status, project_id, due_date)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (issue.title, issue.description, priority, size, "open", issue.project_id, issue.due_date),
        )
        issue_id = cursor.lastrowid

        for pid in person_ids:
            db.execute(
                "INSERT OR IGNORE INTO issue_people (issue_id, person_id) VALUES (?, ?)",
                (issue_id, pid),
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

        if issue.tags:
            _set_issue_tags(db, issue_id, issue.tags)

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


@router.post("/group")
def group_issues():
    """Use Gemini to suggest groupings for open/in-progress issues."""
    from app_config import get_prompt_context, get_secret

    api_key = get_secret("GEMINI_API_KEY") or ""
    if not api_key:
        return {"groups": [], "error": "Gemini API key not configured"}

    with get_db_connection(readonly=True) as db:
        rows = db.execute("SELECT * FROM issues WHERE status != 'done' ORDER BY priority ASC").fetchall()
        issues = [_issue_to_dict(db, r) for r in rows]

    if not issues:
        return {"groups": []}

    from google import genai

    client = genai.Client(api_key=api_key)
    ctx = get_prompt_context()

    system_prompt = f"""You are a project management assistant for {ctx}.
Given a list of issues/tasks, group them into logical categories based on theme, project area, or urgency.

Respond with a JSON array of groups. Each group has:
- "name": short group name (2-4 words)
- "description": one sentence about the theme
- "issue_ids": array of issue IDs belonging to this group

Every issue must appear in exactly one group. Create 2-6 groups."""

    issues_data = [
        {
            "id": i["id"],
            "title": i["title"],
            "description": i["description"],
            "priority": i["priority"],
            "size": i["tshirt_size"],
            "tags": i.get("tags", []),
            "people": [p["name"] for p in i.get("people", [])],
        }
        for i in issues
    ]

    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=json.dumps(issues_data, default=str),
            config={
                "system_instruction": system_prompt,
                "temperature": 0.3,
                "response_mime_type": "application/json",
            },
        )
        groups = json.loads(response.text)
        return {"groups": groups}
    except Exception as e:
        logger.error("Issue grouping failed: %s", e)
        return {"groups": [], "error": "Grouping service unavailable"}


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

        new_person_ids = update.person_ids
        new_meeting_ids = update.meeting_ids
        new_tags = update.tags

        update_fields = {}
        for field, value in update.model_dump(exclude_unset=True).items():
            if field in ("person_ids", "meeting_ids", "tags"):
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

        if new_person_ids is not None:
            _set_issue_people(db, issue_id, new_person_ids)

        if new_meeting_ids is not None:
            _set_issue_meetings(db, issue_id, new_meeting_ids)

        if new_tags is not None:
            _set_issue_tags(db, issue_id, new_tags)

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
