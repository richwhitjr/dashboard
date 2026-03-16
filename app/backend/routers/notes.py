import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from database import get_db_connection, get_write_db, rebuild_fts_table
from models import NoteCreate, NoteUpdate
from routers.changes import bump
from utils.safe_sql import safe_update_query

NOTE_ALLOWED_COLUMNS = {"text", "priority", "status", "person_id", "is_one_on_one", "due_date"}

router = APIRouter(prefix="/api/notes", tags=["notes"])


def _resolve_mentions(text: str, db) -> list[str]:
    """Find all @mentioned people in text. Returns list of person IDs."""
    rows = db.execute("SELECT id, name FROM people").fetchall()
    # Find all @mentions (e.g. @Alice, @Bob Smith)
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


def _resolve_one_on_one(note: NoteCreate, db) -> NoteCreate:
    """If note starts with [1], find the mentioned people and mark as 1:1."""
    if not note.text.startswith("[1]"):
        return note
    text = note.text[3:].lstrip()
    # Resolve all @mentions in the text
    person_ids = _resolve_mentions(text, db)
    updates = {"text": text}
    if person_ids:
        updates["person_id"] = person_ids[0]
        updates["person_ids"] = person_ids
        updates["is_one_on_one"] = True
    elif not note.person_ids:
        # Fall back to fuzzy matching on first words (legacy behavior)
        text_for_match = re.sub(r"^@", "", text)
        rows = db.execute("SELECT id, name FROM people").fetchall()
        for row in rows:
            name = row["name"]
            first = name.split()[0].lower()
            last = name.split()[-1].lower() if len(name.split()) > 1 else ""
            lower_text = text_for_match.lower()
            name_match = name.lower() in lower_text
            first_match = first in lower_text.split()[:3]
            last_match = last and last in lower_text.split()[:3]
            if name_match or first_match or last_match:
                updates["person_id"] = row["id"]
                updates["person_ids"] = [row["id"]]
                updates["is_one_on_one"] = True
                break
    return note.model_copy(update=updates)


def _get_note_people(db, note_id: int) -> list[dict]:
    """Get all people linked to a note via junction table."""
    rows = db.execute(
        "SELECT p.id, p.name FROM note_people np JOIN people p ON np.person_id = p.id WHERE np.note_id = ?",
        (note_id,),
    ).fetchall()
    return [{"id": r["id"], "name": r["name"]} for r in rows]


def _set_note_people(db, note_id: int, person_ids: list[str]):
    """Replace all person links for a note."""
    db.execute("DELETE FROM note_people WHERE note_id = ?", (note_id,))
    for pid in person_ids:
        db.execute(
            "INSERT OR IGNORE INTO note_people (note_id, person_id) VALUES (?, ?)",
            (note_id, pid),
        )


def _note_to_dict(db, row) -> dict:
    """Convert a note row to dict with people array."""
    note = dict(row)
    people = _get_note_people(db, note["id"])
    note["people"] = people
    # Backward compat keys
    note["employees"] = people
    if people:
        note["person_id"] = people[0]["id"]
        note["person_name"] = people[0]["name"]
        note["employee_id"] = people[0]["id"]
        note["employee_name"] = people[0]["name"]
    else:
        note.setdefault("person_name", None)
        note.setdefault("employee_name", None)
    return note


@router.get("")
def list_notes(
    status: Optional[str] = Query(None),
    person_id: Optional[str] = Query(None, alias="person_id"),
    employee_id: Optional[str] = Query(None, alias="employee_id"),
    is_one_on_one: Optional[bool] = Query(None),
):
    # Support both person_id and employee_id as query params for compat
    pid = person_id or employee_id
    with get_db_connection(readonly=True) as db:
        if pid:
            query = "SELECT DISTINCT t.* FROM notes t JOIN note_people np ON t.id = np.note_id WHERE np.person_id = ?"
            params: list = [pid]
        else:
            query = "SELECT t.* FROM notes t WHERE 1=1"
            params = []

        if status:
            query += " AND t.status = ?"
            params.append(status)
        if is_one_on_one is not None:
            query += " AND t.is_one_on_one = ?"
            params.append(int(is_one_on_one))

        query += " ORDER BY t.status ASC, t.is_one_on_one DESC, t.priority DESC, t.created_at DESC"

        rows = db.execute(query, params).fetchall()
        result = [_note_to_dict(db, r) for r in rows]
    return result


def _parse_issue_prefix(text: str) -> dict | None:
    """Parse [i][size][priority] prefix. Returns parsed fields or None if not an issue."""
    if not text.lower().startswith("[i]"):
        return None
    remaining = text
    tshirt_size = "m"
    priority = 1
    prefix_re = re.compile(r"^\[(i|s|m|l|xl|p0|p1|p2|p3)\]\s*", re.IGNORECASE)
    while prefix_re.match(remaining):
        match = prefix_re.match(remaining)
        tag = match.group(1).lower()
        if tag in ("s", "m", "l", "xl"):
            tshirt_size = tag
        elif tag.startswith("p"):
            priority = int(tag[1])
        remaining = remaining[match.end() :]
    return {"title": remaining.strip(), "tshirt_size": tshirt_size, "priority": priority}


@router.post("")
def create_note(note: NoteCreate):
    # Intercept [i] prefix → create an issue instead
    parsed = _parse_issue_prefix(note.text)
    if parsed:
        from models import IssueCreate
        from routers.issues import create_issue as _create_issue

        person_ids = note.person_ids or []
        if not person_ids:
            with get_db_connection(readonly=True) as db:
                detected = _resolve_mentions(parsed["title"], db)
            if detected:
                person_ids = detected
        issue = IssueCreate(
            title=parsed["title"],
            priority=parsed["priority"],
            tshirt_size=parsed["tshirt_size"],
            person_ids=person_ids or None,
        )
        result = _create_issue(issue)
        result["_type"] = "issue"
        return result

    with get_write_db() as db:
        note = _resolve_one_on_one(note, db)

        # Resolve person_ids: explicit list > @mention detection > single person_id
        person_ids = note.person_ids or []
        if not person_ids and not note.text.startswith("[1]"):
            detected = _resolve_mentions(note.text, db)
            if detected:
                person_ids = detected
        if not person_ids and note.person_id:
            person_ids = [note.person_id]

        primary_id = person_ids[0] if person_ids else note.person_id

        cursor = db.execute(
            "INSERT INTO notes (text, priority, person_id, is_one_on_one, due_date) VALUES (?, ?, ?, ?, ?)",
            (note.text, note.priority, primary_id, int(note.is_one_on_one), note.due_date),
        )
        note_id = cursor.lastrowid

        for pid in person_ids:
            db.execute(
                "INSERT OR IGNORE INTO note_people (note_id, person_id) VALUES (?, ?)",
                (note_id, pid),
            )

        db.commit()
        row = db.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        result = _note_to_dict(db, row)
    rebuild_fts_table("fts_notes")
    bump("notes")
    return result


@router.patch("/{note_id}")
def update_note(note_id: int, update: NoteUpdate):
    with get_write_db() as db:
        existing = db.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Note not found")

        new_person_ids = update.person_ids

        update_fields = {}
        for field, value in update.model_dump(exclude_unset=True).items():
            if field == "person_ids":
                continue  # Handled separately via junction table
            if field == "is_one_on_one" and value is not None:
                value = int(value)
            update_fields[field] = value

        # Auto-set completed_at when marking done
        extra = []
        extra_params = []
        if update.status == "done" and existing["status"] != "done":
            extra.append("completed_at = ?")
            extra_params.append(datetime.now().isoformat())
        elif update.status and update.status != "done":
            extra.append("completed_at = ?")
            extra_params.append(None)

        if update_fields:
            set_clause, params = safe_update_query("notes", update_fields, NOTE_ALLOWED_COLUMNS, extra)
            params.extend(extra_params)
            params.append(note_id)
            db.execute(f"UPDATE notes SET {set_clause} WHERE id = ?", params)

        if new_person_ids is not None:
            _set_note_people(db, note_id, new_person_ids)
            primary = new_person_ids[0] if new_person_ids else None
            db.execute("UPDATE notes SET person_id = ? WHERE id = ?", (primary, note_id))

        db.commit()

        row = db.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        result = _note_to_dict(db, row)
    rebuild_fts_table("fts_notes")
    bump("notes")
    return result


@router.delete("/{note_id}")
def delete_note(note_id: int):
    with get_write_db() as db:
        db.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        db.commit()
    rebuild_fts_table("fts_notes")
    bump("notes")
    return {"ok": True}
