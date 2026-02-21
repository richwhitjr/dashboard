"""CRUD endpoints for Claude chat session history."""

import base64
import json
import logging
import os
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException

from config import DATABASE_PATH
from database import get_db
from models import ClaudeSessionCreate, ClaudeSessionUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/claude/sessions", tags=["claude-sessions"])

SESSIONS_DIR = DATABASE_PATH.parent / "claude_sessions"

_SUMMARIZE_PROMPT = (
    "You are summarizing a Claude Code terminal session for a CTO's personal dashboard. "
    "Given the raw terminal text, produce a JSON object with two fields:\n"
    '  "title": a short (5-10 word) title for the session\n'
    '  "summary": a clean, readable markdown summary (3-10 bullet points) of what was discussed and done\n\n'
    "Strip all ANSI codes, terminal artifacts, and control characters. "
    "Focus on: questions asked, code written/modified, decisions made, and outcomes. "
    "Be concise. Return ONLY valid JSON, no markdown fences."
)


def _summarize_session(plain_text: str) -> dict:
    """Call Gemini to summarize session text. Returns {title, summary}."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key or not plain_text.strip():
        return {}

    try:
        from google import genai

        client = genai.Client(api_key=api_key)
        # Truncate to avoid token limits — last 8000 chars are most relevant
        text = plain_text[-8000:] if len(plain_text) > 8000 else plain_text

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=f"Summarize this Claude Code session:\n\n{text}",
            config={
                "system_instruction": _SUMMARIZE_PROMPT,
                "temperature": 0.2,
                "response_mime_type": "application/json",
            },
        )

        result = json.loads(response.text)
        if isinstance(result, dict):
            return result
    except Exception as e:
        logger.warning(f"Gemini summarization failed: {e}")

    return {}


def _summarize_in_background(session_id: int, plain_text: str):
    """Run summarization in a background thread, update DB when done."""

    def _run():
        result = _summarize_session(plain_text)
        if not result:
            return

        db = get_db()
        fields = ["updated_at = datetime('now')"]
        params = []

        if result.get("summary"):
            fields.append("summary = ?")
            params.append(result["summary"])
            # Also update preview with first line of summary
            preview = result["summary"].split("\n")[0][:200].lstrip("- *")
            fields.append("preview = ?")
            params.append(preview)

        if result.get("title"):
            fields.append("title = ?")
            params.append(result["title"])

        if len(params) > 0:
            params.append(session_id)
            db.execute(
                f"UPDATE claude_sessions SET {', '.join(fields)} WHERE id = ?",
                params,
            )
            db.commit()
        db.close()

    threading.Thread(target=_run, daemon=True).start()


@router.get("")
def list_sessions():
    """List all saved Claude sessions, newest first."""
    db = get_db()
    rows = db.execute(
        "SELECT id, title, created_at, updated_at, preview, summary, size_bytes "
        "FROM claude_sessions ORDER BY created_at DESC"
    ).fetchall()
    result = [dict(r) for r in rows]
    db.close()
    return result


@router.get("/{session_id}")
def get_session(session_id: int):
    """Get session metadata."""
    db = get_db()
    row = db.execute("SELECT * FROM claude_sessions WHERE id = ?", (session_id,)).fetchone()
    db.close()
    if not row:
        raise HTTPException(status_code=404, detail="Session not found")
    return dict(row)


@router.get("/{session_id}/content")
def get_session_content(session_id: int):
    """Read the full session content from the JSON file on disk."""
    db = get_db()
    row = db.execute("SELECT filepath, summary FROM claude_sessions WHERE id = ?", (session_id,)).fetchone()
    db.close()
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

    db = get_db()

    preview = session.plain_text[:200].strip() if session.plain_text else ""
    content_bytes = base64.b64decode(session.content)
    size_bytes = len(content_bytes)

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
    db.close()

    # Kick off Gemini summarization in background — updates title, preview, summary
    _summarize_in_background(session_id, session.plain_text)

    return result


@router.patch("/{session_id}")
def update_session(session_id: int, update: ClaudeSessionUpdate):
    """Update session title."""
    db = get_db()
    existing = db.execute("SELECT * FROM claude_sessions WHERE id = ?", (session_id,)).fetchone()
    if not existing:
        db.close()
        raise HTTPException(status_code=404, detail="Session not found")

    fields = ["updated_at = datetime('now')"]
    params = []
    if update.title is not None:
        fields.append("title = ?")
        params.append(update.title)

    params.append(session_id)
    db.execute(f"UPDATE claude_sessions SET {', '.join(fields)} WHERE id = ?", params)
    db.commit()

    row = db.execute("SELECT * FROM claude_sessions WHERE id = ?", (session_id,)).fetchone()
    result = dict(row)
    db.close()
    return result


@router.delete("/{session_id}")
def delete_session(session_id: int):
    """Delete a session and its file from disk."""
    db = get_db()
    row = db.execute("SELECT filepath FROM claude_sessions WHERE id = ?", (session_id,)).fetchone()
    if not row:
        db.close()
        raise HTTPException(status_code=404, detail="Session not found")

    # Delete file from disk
    filepath = Path(row["filepath"])
    if filepath.exists():
        filepath.unlink()

    db.execute("DELETE FROM claude_sessions WHERE id = ?", (session_id,))
    db.commit()
    db.close()
    return {"ok": True}


@router.post("/{session_id}/create_note")
def create_note_from_session(session_id: int):
    """Create a note summarizing this Claude session with bidirectional links."""
    db = get_db()

    # Get the session
    row = db.execute("SELECT * FROM claude_sessions WHERE id = ?", (session_id,)).fetchone()
    if not row:
        db.close()
        raise HTTPException(status_code=404, detail="Session not found")

    session = dict(row)

    # Check if a note already exists for this session
    existing = db.execute("SELECT id FROM notes WHERE claude_session_id = ?", (session_id,)).fetchone()

    if existing:
        db.close()
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
    db.close()

    return result
