"""CRUD endpoints for Claude chat session history."""

import base64
import json
import logging
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException

from config import DATABASE_PATH
from database import get_db_connection, get_write_db
from models import ClaudeSessionCreate, ClaudeSessionUpdate
from routers.changes import bump
from utils.safe_sql import safe_update_query

SESSION_ALLOWED_COLUMNS = {"title", "summary", "preview"}

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/claude/sessions", tags=["claude-sessions"])

SESSIONS_DIR = DATABASE_PATH.parent / "claude_sessions"

_SUMMARIZE_PROMPT = (
    "You are summarizing a Claude Code terminal session for a personal dashboard. "
    "Given the raw terminal text, produce a JSON object with two fields:\n"
    '  "title": a short (5-10 word) title for the session\n'
    '  "summary": a clean, readable markdown summary (3-10 bullet points) of what was discussed and done\n\n'
    "Strip all ANSI codes, terminal artifacts, and control characters. "
    "Focus on: questions asked, code written/modified, decisions made, and outcomes. "
    "Be concise. Return ONLY valid JSON, no markdown fences."
)


def _summarize_session(plain_text: str) -> dict:
    """Call AI to summarize session text. Returns {title, summary}."""
    if not plain_text.strip():
        return {}

    from ai_client import generate

    text_input = plain_text[-8000:] if len(plain_text) > 8000 else plain_text

    text = generate(
        system_prompt=_SUMMARIZE_PROMPT,
        user_message=f"Summarize this Claude Code session:\n\n{text_input}",
        json_mode=True,
    )
    if not text:
        return {}

    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except (json.JSONDecodeError, TypeError):
        pass
    return {}


def _summarize_in_background(session_id: int, plain_text: str):
    """Run summarization in a background thread, update DB when done."""

    def _run():
        result = _summarize_session(plain_text)
        if not result:
            return

        update_fields = {}
        if result.get("summary"):
            update_fields["summary"] = result["summary"]
            update_fields["preview"] = result["summary"].split("\n")[0][:200].lstrip("- *")
        if result.get("title"):
            update_fields["title"] = result["title"]

        if update_fields:
            set_clause, params = safe_update_query(
                "claude_sessions",
                update_fields,
                SESSION_ALLOWED_COLUMNS,
                extra_set_clauses=["updated_at = datetime('now')"],
            )
            with get_write_db() as db:
                params.append(session_id)
                db.execute(
                    f"UPDATE claude_sessions SET {set_clause} WHERE id = ?",
                    params,
                )
                db.commit()

        # Create a memory entry capturing what happened in this session
        try:
            from routers.memory import create_memory_entry

            create_memory_entry(trigger="claude_session", claude_session_id=session_id)
        except Exception as e:
            logger.warning(f"Memory entry creation failed for session {session_id}: {e}")

    threading.Thread(target=_run, daemon=True).start()


@router.get("")
def list_sessions():
    """List all saved Claude sessions, newest first."""
    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            "SELECT id, title, created_at, updated_at, preview, summary, size_bytes "
            "FROM claude_sessions ORDER BY created_at DESC"
        ).fetchall()
        result = [dict(r) for r in rows]
    return result


@router.get("/{session_id}")
def get_session(session_id: int):
    """Get session metadata."""
    with get_db_connection(readonly=True) as db:
        row = db.execute("SELECT * FROM claude_sessions WHERE id = ?", (session_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    return dict(row)


@router.get("/{session_id}/content")
def get_session_content(session_id: int):
    """Read the full session content from the JSON file on disk."""
    with get_db_connection(readonly=True) as db:
        row = db.execute("SELECT filepath, summary FROM claude_sessions WHERE id = ?", (session_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")

    filepath = Path(row["filepath"])
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Session file not found")

    with open(filepath, "r") as f:
        data = json.load(f)

    # Include summary from DB in the response
    data["summary"] = row["summary"] or ""
    return data


@router.post("")
def create_session(session: ClaudeSessionCreate):
    """Save a new Claude session to disk + database."""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

    preview = session.plain_text[:200].strip() if session.plain_text else ""
    content_bytes = base64.b64decode(session.content)
    size_bytes = len(content_bytes)

    with get_write_db() as db:
        # Insert DB row first to get the auto-increment ID
        cursor = db.execute(
            "INSERT INTO claude_sessions (title, preview, size_bytes, filepath) VALUES (?, ?, ?, ?)",
            (session.title, preview, size_bytes, ""),
        )
        session_id = cursor.lastrowid

        # Write JSON file to disk
        filename = f"session_{session_id}.json"
        filepath = SESSIONS_DIR / filename
        file_data = {
            "id": session_id,
            "raw_output": session.content,
            "plain_text": session.plain_text,
            "metadata": {"rows": session.rows, "cols": session.cols},
        }
        with open(filepath, "w") as f:
            json.dump(file_data, f)

        # Update filepath in DB
        db.execute(
            "UPDATE claude_sessions SET filepath = ? WHERE id = ?",
            (str(filepath), session_id),
        )
        db.commit()

        row = db.execute("SELECT * FROM claude_sessions WHERE id = ?", (session_id,)).fetchone()
        result = dict(row)

    # Kick off Gemini summarization in background — updates title, preview, summary
    _summarize_in_background(session_id, session.plain_text)

    return result


@router.patch("/{session_id}")
def update_session(session_id: int, update: ClaudeSessionUpdate):
    """Update session title."""
    with get_write_db() as db:
        existing = db.execute("SELECT * FROM claude_sessions WHERE id = ?", (session_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Session not found")

        update_fields = {}
        if update.title is not None:
            update_fields["title"] = update.title

        set_clause, params = safe_update_query(
            "claude_sessions",
            update_fields,
            SESSION_ALLOWED_COLUMNS,
            extra_set_clauses=["updated_at = datetime('now')"],
        )
        params.append(session_id)
        db.execute(f"UPDATE claude_sessions SET {set_clause} WHERE id = ?", params)
        db.commit()

        row = db.execute("SELECT * FROM claude_sessions WHERE id = ?", (session_id,)).fetchone()
        result = dict(row)
    return result


@router.delete("/{session_id}")
def delete_session(session_id: int):
    """Delete a session and its file from disk."""
    with get_write_db() as db:
        row = db.execute("SELECT filepath FROM claude_sessions WHERE id = ?", (session_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Session not found")

        # Delete file from disk
        filepath = Path(row["filepath"])
        if filepath.exists():
            filepath.unlink()

        db.execute("DELETE FROM claude_sessions WHERE id = ?", (session_id,))
        db.commit()
    return {"ok": True}


@router.post("/{session_id}/create_note")
def create_note_from_session(session_id: int):
    """Create a note summarizing this Claude session with bidirectional links."""
    with get_write_db() as db:
        # Get the session
        row = db.execute("SELECT * FROM claude_sessions WHERE id = ?", (session_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Session not found")

        session = dict(row)

        # Check if a note already exists for this session
        existing = db.execute("SELECT id FROM notes WHERE claude_session_id = ?", (session_id,)).fetchone()

        if existing:
            raise HTTPException(status_code=400, detail="Note already exists for this session")

        # Build note text with summary and link back to session
        note_text = f"**Claude Session**: [{session['title']}](/claude?session={session_id})\n\n"

        if session.get("summary"):
            note_text += session["summary"]
        else:
            # Fallback to preview if no summary yet
            note_text += session.get("preview", "Session in progress...")

        # Insert the note
        cursor = db.execute(
            """
            INSERT INTO notes (text, priority, status, claude_session_id, created_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            """,
            (note_text, 1, "open", session_id),
        )
        note_id = cursor.lastrowid

        # Get the created note
        note_row = db.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        result = dict(note_row)

        db.commit()

    bump("notes")
    return result
