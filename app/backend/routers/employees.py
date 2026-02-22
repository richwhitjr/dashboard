import json
from datetime import datetime

from fastapi import APIRouter, HTTPException

from config import EXECUTIVES_DIR, HIDDEN_TEAMS_DIR, TEAMS_DIR
from database import get_db_connection, get_write_db
from models import (
    EmployeeCreate,
    EmployeeUpdate,
    OneOnOneNoteCreate,
    OneOnOneNoteUpdate,
)
from utils.employee_matching import get_employee_email_patterns, rebuild_from_db
from utils.safe_sql import safe_update_query

EMPLOYEE_ALLOWED_COLUMNS = {"name", "title", "reports_to", "group_name", "email", "role_content"}
ONE_ON_ONE_NOTE_ALLOWED_COLUMNS = {"meeting_date", "title", "content"}

router = APIRouter(prefix="/api/employees", tags=["employees"])


@router.get("")
def list_employees():
    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            "SELECT id, name, title, reports_to, depth, has_meetings_dir, is_executive, group_name, email "
            "FROM employees ORDER BY name"
        ).fetchall()
    return [dict(r) for r in rows]


@router.get("/groups")
def list_groups():
    """Return distinct group_name values, 'team' always first."""
    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            "SELECT DISTINCT group_name FROM employees WHERE group_name IS NOT NULL ORDER BY group_name"
        ).fetchall()
    groups = [r["group_name"] for r in rows]
    if "team" in groups:
        groups.remove("team")
    return ["team"] + groups


@router.post("")
def create_employee(emp: EmployeeCreate):
    # Auto-generate ID from name if not provided
    emp_id = emp.id or emp.name.strip().replace(" ", "_")

    if not emp.group_name or not emp.group_name.strip():
        raise HTTPException(status_code=400, detail="group_name must not be empty")

    with get_write_db() as db:
        # Validate reports_to exists if provided
        if emp.reports_to:
            exists = db.execute("SELECT 1 FROM employees WHERE id = ?", (emp.reports_to,)).fetchone()
            if not exists:
                raise HTTPException(status_code=400, detail=f"reports_to employee '{emp.reports_to}' not found")

        # Check for duplicate ID
        existing = db.execute("SELECT 1 FROM employees WHERE id = ?", (emp_id,)).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail=f"Employee '{emp_id}' already exists")

        db.execute(
            """INSERT INTO employees
               (id, name, title, reports_to, group_name, email, dir_path, is_executive, created_at)
               VALUES (?, ?, ?, ?, ?, ?, '', ?, ?)""",
            (
                emp_id,
                emp.name.strip(),
                emp.title,
                emp.reports_to,
                emp.group_name,
                emp.email,
                0,
                datetime.now().isoformat(),
            ),
        )
        db.commit()
        row = db.execute("SELECT * FROM employees WHERE id = ?", (emp_id,)).fetchone()
    rebuild_from_db()
    return dict(row)


@router.patch("/{employee_id}")
def update_employee(employee_id: str, update: EmployeeUpdate):
    with get_write_db() as db:
        row = db.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Employee not found")

        update_fields = {}
        for field, value in update.model_dump(exclude_unset=True).items():
            if field == "group_name" and (not value or not value.strip()):
                raise HTTPException(status_code=400, detail="group_name must not be empty")
            if field == "reports_to" and value is not None:
                # Validate no circular reference
                if value == employee_id:
                    raise HTTPException(status_code=400, detail="Employee cannot report to themselves")
                exists = db.execute("SELECT 1 FROM employees WHERE id = ?", (value,)).fetchone()
                if not exists:
                    raise HTTPException(status_code=400, detail=f"reports_to employee '{value}' not found")
                # Walk chain to detect cycles
                current = value
                while current:
                    parent = db.execute("SELECT reports_to FROM employees WHERE id = ?", (current,)).fetchone()
                    if not parent or not parent["reports_to"]:
                        break
                    if parent["reports_to"] == employee_id:
                        raise HTTPException(status_code=400, detail="Circular reporting chain detected")
                    current = parent["reports_to"]
            update_fields[field] = value

        if not update_fields:
            return dict(row)

        set_clause, params = safe_update_query("employees", update_fields, EMPLOYEE_ALLOWED_COLUMNS)
        params.append(employee_id)
        db.execute(f"UPDATE employees SET {set_clause} WHERE id = ?", params)
        db.commit()
        updated = db.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
    rebuild_from_db()
    return dict(updated)


@router.delete("/{employee_id}")
def delete_employee(employee_id: str):
    with get_write_db() as db:
        row = db.execute("SELECT 1 FROM employees WHERE id = ?", (employee_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Employee not found")

        # Nullify reports_to for direct reports
        db.execute("UPDATE employees SET reports_to = NULL WHERE reports_to = ?", (employee_id,))
        # Nullify notes linkage
        db.execute("UPDATE notes SET employee_id = NULL WHERE employee_id = ?", (employee_id,))
        db.execute("DELETE FROM note_employees WHERE employee_id = ?", (employee_id,))
        db.execute("DELETE FROM issue_employees WHERE employee_id = ?", (employee_id,))
        # Delete related records
        db.execute("DELETE FROM meeting_files WHERE employee_id = ?", (employee_id,))
        db.execute("DELETE FROM one_on_one_notes WHERE employee_id = ?", (employee_id,))
        db.execute("UPDATE granola_meetings SET employee_id = NULL WHERE employee_id = ?", (employee_id,))
        # Delete employee
        db.execute("DELETE FROM employees WHERE id = ?", (employee_id,))
        db.commit()
    rebuild_from_db()
    return {"status": "deleted", "id": employee_id}


@router.get("/{employee_id}")
def get_employee(employee_id: str):
    with get_db_connection(readonly=True) as db:
        row = db.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Employee not found")

        emp = dict(row)

        # Direct reports from DB
        dr_rows = db.execute(
            "SELECT id, name, title FROM employees WHERE reports_to = ? ORDER BY name",
            (employee_id,),
        ).fetchall()
        emp["direct_reports"] = [dict(r) for r in dr_rows]

        # Role content: from DB field (may have been imported from markdown)
        emp["role_content"] = emp.get("role_content") or ""

        # Get meeting files from DB
        meeting_rows = db.execute(
            "SELECT * FROM meeting_files WHERE employee_id = ? ORDER BY meeting_date DESC",
            (employee_id,),
        ).fetchall()
        emp["meeting_files"] = [dict(r) for r in meeting_rows]

        # Get granola meetings
        granola_rows = db.execute(
            "SELECT * FROM granola_meetings WHERE employee_id = ? ORDER BY created_at DESC",
            (employee_id,),
        ).fetchall()
        emp["granola_meetings"] = [dict(r) for r in granola_rows]

        # Get linked notes via junction table
        note_rows = db.execute(
            "SELECT DISTINCT n.* FROM notes n "
            "JOIN note_employees ne ON n.id = ne.note_id "
            "WHERE ne.employee_id = ? AND n.status = 'open' "
            "ORDER BY n.is_one_on_one DESC, n.created_at DESC",
            (employee_id,),
        ).fetchall()
        emp["linked_notes"] = [dict(r) for r in note_rows]

        # Get linked issues via junction table
        issue_rows = db.execute(
            "SELECT DISTINCT i.* FROM issues i "
            "JOIN issue_employees ie ON i.id = ie.issue_id "
            "WHERE ie.employee_id = ? AND i.status != 'done' "
            "ORDER BY i.priority ASC, i.updated_at DESC",
            (employee_id,),
        ).fetchall()
        linked_issues = []
        for ir in issue_rows:
            iss = dict(ir)
            # Enrich with employees list
            ie_rows = db.execute(
                "SELECT e.id, e.name FROM issue_employees ie "
                "JOIN employees e ON ie.employee_id = e.id WHERE ie.issue_id = ?",
                (iss["id"],),
            ).fetchall()
            iss["employees"] = [{"id": r["id"], "name": r["name"]} for r in ie_rows]
            iss["meetings"] = []
            linked_issues.append(iss)
        emp["linked_issues"] = linked_issues

        # Get 1:1 notes
        oon_rows = db.execute(
            "SELECT * FROM one_on_one_notes WHERE employee_id = ? ORDER BY meeting_date DESC",
            (employee_id,),
        ).fetchall()
        emp["one_on_one_notes"] = [dict(r) for r in oon_rows]

        # Next meeting: find upcoming calendar event with this employee as attendee
        emp["next_meeting"] = None
        email_patterns = get_employee_email_patterns(employee_id)
        if email_patterns:
            future_events = db.execute(
                "SELECT id, summary, start_time, end_time, html_link, attendees_json "
                "FROM calendar_events WHERE start_time > datetime('now') ORDER BY start_time"
            ).fetchall()
            for event in future_events:
                attendees_raw = event["attendees_json"] or "[]"
                try:
                    attendees = json.loads(attendees_raw) if isinstance(attendees_raw, str) else attendees_raw
                except (json.JSONDecodeError, TypeError):
                    continue
                attendee_emails = [a.get("email", "").lower() for a in attendees]
                if any(pat in attendee_emails for pat in email_patterns):
                    emp["next_meeting"] = {
                        "summary": event["summary"],
                        "start_time": event["start_time"],
                        "end_time": event["end_time"],
                        "html_link": event["html_link"],
                    }
                    break

    # Recent meeting summaries: unified from meeting_files + granola_meetings, top 3
    summaries = []
    for mf in emp["meeting_files"][:5]:
        summaries.append(
            {
                "date": mf.get("meeting_date", ""),
                "title": mf.get("title", ""),
                "summary": (mf.get("summary") or "")[:200],
                "source": "file",
            }
        )
    file_dates = {s["date"] for s in summaries}
    for gm in emp["granola_meetings"][:5]:
        g_date = (gm.get("created_at") or "")[:10]
        if g_date and g_date not in file_dates:
            summaries.append(
                {
                    "date": g_date,
                    "title": gm.get("title", ""),
                    "summary": (gm.get("panel_summary_plain") or "")[:200],
                    "source": "granola",
                }
            )
    summaries.sort(key=lambda s: s["date"] or "", reverse=True)
    emp["recent_meeting_summaries"] = summaries[:3]

    return emp


# --- 1:1 Notes CRUD ---


@router.get("/{employee_id}/one-on-one-notes")
def list_one_on_one_notes(employee_id: str):
    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            "SELECT * FROM one_on_one_notes WHERE employee_id = ? ORDER BY meeting_date DESC",
            (employee_id,),
        ).fetchall()
    return [dict(r) for r in rows]


@router.post("/{employee_id}/one-on-one-notes")
def create_one_on_one_note(employee_id: str, note: OneOnOneNoteCreate):
    with get_write_db() as db:
        # Validate employee exists
        emp = db.execute("SELECT 1 FROM employees WHERE id = ?", (employee_id,)).fetchone()
        if not emp:
            raise HTTPException(status_code=404, detail="Employee not found")

        now = datetime.now().isoformat()
        cursor = db.execute(
            """INSERT INTO one_on_one_notes (employee_id, meeting_date, title, content, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (employee_id, note.meeting_date, note.title, note.content, now, now),
        )
        db.commit()
        row = db.execute("SELECT * FROM one_on_one_notes WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return dict(row)


@router.patch("/{employee_id}/one-on-one-notes/{note_id}")
def update_one_on_one_note(employee_id: str, note_id: int, update: OneOnOneNoteUpdate):
    with get_write_db() as db:
        row = db.execute(
            "SELECT * FROM one_on_one_notes WHERE id = ? AND employee_id = ?",
            (note_id, employee_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Note not found")

        update_fields = dict(update.model_dump(exclude_unset=True))

        if update_fields:
            set_clause, params = safe_update_query(
                "one_on_one_notes",
                update_fields,
                ONE_ON_ONE_NOTE_ALLOWED_COLUMNS,
                extra_set_clauses=["updated_at = ?"],
            )
            params.append(datetime.now().isoformat())
            params.append(note_id)
            db.execute(f"UPDATE one_on_one_notes SET {set_clause} WHERE id = ?", params)
            db.commit()

        updated = db.execute("SELECT * FROM one_on_one_notes WHERE id = ?", (note_id,)).fetchone()
    return dict(updated)


@router.delete("/{employee_id}/one-on-one-notes/{note_id}")
def delete_one_on_one_note(employee_id: str, note_id: int):
    with get_write_db() as db:
        row = db.execute(
            "SELECT 1 FROM one_on_one_notes WHERE id = ? AND employee_id = ?",
            (note_id, employee_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Note not found")

        db.execute("DELETE FROM one_on_one_notes WHERE id = ?", (note_id,))
        db.commit()
    return {"status": "deleted", "id": note_id}


# --- One-Time Markdown Import ---


@router.post("/import-markdown")
def import_from_markdown():
    """One-time import of employee data from markdown files into SQLite."""
    from pathlib import Path

    from connectors.markdown import parse_org_tree

    imported = 0

    with get_write_db() as db:
        for source_dir, is_exec in [
            (TEAMS_DIR, False),
            (EXECUTIVES_DIR, True),
            (HIDDEN_TEAMS_DIR, False),
        ]:
            if not source_dir or not Path(source_dir).exists():
                continue
            employees = parse_org_tree(source_dir, is_executive=is_exec)
            for emp in employees:
                group = "exec" if emp.get("is_executive") else "team"
                # Read role.md content if available
                role_content = ""
                role_path = Path(emp["dir_path"]) / "role.md"
                if role_path.exists():
                    role_content = role_path.read_text(encoding="utf-8")

                existing = db.execute("SELECT 1 FROM employees WHERE id = ?", (emp["id"],)).fetchone()
                if existing:
                    # Update fields that may have been missing
                    db.execute(
                        """UPDATE employees SET
                            dir_path = COALESCE(NULLIF(dir_path, ''), ?),
                            group_name = ?,
                            is_executive = ?,
                            role_content = COALESCE(role_content, ?),
                            has_meetings_dir = ?
                        WHERE id = ?""",
                        (
                            emp["dir_path"],
                            group,
                            int(emp.get("is_executive", False)),
                            role_content,
                            int(emp["has_meetings_dir"]),
                            emp["id"],
                        ),
                    )
                else:
                    db.execute(
                        """INSERT INTO employees
                           (id, name, title, reports_to, depth, dir_path, has_meetings_dir,
                            is_executive, group_name, role_content, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            emp["id"],
                            emp["name"],
                            emp["title"],
                            emp["reports_to"],
                            emp["depth"],
                            emp["dir_path"],
                            int(emp["has_meetings_dir"]),
                            int(emp.get("is_executive", False)),
                            group,
                            role_content,
                            datetime.now().isoformat(),
                        ),
                    )
                    imported += 1

        db.commit()
    rebuild_from_db()
    return {"status": "success", "imported": imported}
