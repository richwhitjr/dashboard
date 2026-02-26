"""CRUD endpoints for longform posts with tags, comments, thoughts, and Claude session import."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from database import get_db_connection, get_write_db, rebuild_fts_table
from models import LongformCommentCreate, LongformCreate, LongformUpdate
from utils.safe_sql import safe_update_query

logger = logging.getLogger(__name__)

LONGFORM_ALLOWED_COLUMNS = {"title", "body", "status"}
VALID_STATUSES = {"draft", "published"}

SORT_COLUMNS = {
    "created_at": "lp.created_at",
    "updated_at": "lp.updated_at",
    "title": "lp.title",
    "word_count": "lp.word_count",
}

router = APIRouter(prefix="/api/longform", tags=["longform"])


# --- Helpers ---


def _get_post_tags(db, post_id: int) -> list[str]:
    rows = db.execute("SELECT tag FROM longform_tags WHERE post_id = ? ORDER BY tag", (post_id,)).fetchall()
    return [r["tag"] for r in rows]


def _set_post_tags(db, post_id: int, tags: list[str]):
    db.execute("DELETE FROM longform_tags WHERE post_id = ?", (post_id,))
    for tag in tags:
        tag = tag.strip().lower()
        if tag:
            db.execute("INSERT OR IGNORE INTO longform_tags (post_id, tag) VALUES (?, ?)", (post_id, tag))


def _get_post_comments(db, post_id: int) -> tuple[list[dict], list[dict]]:
    """Return (comments, thoughts) for a post."""
    rows = db.execute(
        "SELECT * FROM longform_comments WHERE post_id = ? ORDER BY created_at ASC",
        (post_id,),
    ).fetchall()
    comments = []
    thoughts = []
    for r in rows:
        d = dict(r)
        d["is_thought"] = bool(d["is_thought"])
        if d["is_thought"]:
            thoughts.append(d)
        else:
            comments.append(d)
    return comments, thoughts


def _post_to_dict(db, row) -> dict:
    post = dict(row)
    post["tags"] = _get_post_tags(db, post["id"])
    # Count comments and thoughts
    counts = db.execute(
        "SELECT is_thought, COUNT(*) as cnt FROM longform_comments WHERE post_id = ? GROUP BY is_thought",
        (post["id"],),
    ).fetchall()
    post["comment_count"] = 0
    post["thought_count"] = 0
    for c in counts:
        if c["is_thought"]:
            post["thought_count"] = c["cnt"]
        else:
            post["comment_count"] = c["cnt"]
    return post


def _post_to_detail_dict(db, row) -> dict:
    post = _post_to_dict(db, row)
    comments, thoughts = _get_post_comments(db, post["id"])
    post["comments"] = comments
    post["thoughts"] = thoughts
    return post


# --- Endpoints ---


@router.get("/tags")
def list_tags():
    """Return all distinct tags for autocomplete."""
    with get_db_connection(readonly=True) as db:
        rows = db.execute("SELECT DISTINCT tag FROM longform_tags ORDER BY tag").fetchall()
    return [r["tag"] for r in rows]


@router.get("")
def list_posts(
    status: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    sort_by: Optional[str] = Query(None),
    sort_dir: Optional[str] = Query("desc"),
):
    with get_db_connection(readonly=True) as db:
        query = "SELECT lp.* FROM longform_posts lp WHERE 1=1"
        params: list = []

        if status:
            query += " AND lp.status = ?"
            params.append(status)

        # Tag filter
        if tag:
            query = query.replace("SELECT lp.* FROM longform_posts lp", "SELECT DISTINCT lp.* FROM longform_posts lp")
            query = query.replace(" WHERE ", " JOIN longform_tags lt ON lp.id = lt.post_id WHERE ")
            query += " AND lt.tag = ?"
            params.append(tag.lower())

        # FTS search
        if search:
            fts_rows = db.execute(
                "SELECT rowid FROM fts_longform WHERE fts_longform MATCH ?", (search,)
            ).fetchall()
            fts_ids = [r["rowid"] for r in fts_rows]
            if not fts_ids:
                return []
            placeholders = ",".join("?" * len(fts_ids))
            query += f" AND lp.id IN ({placeholders})"
            params.extend(fts_ids)

        # Sorting
        if sort_by and sort_by in SORT_COLUMNS:
            direction = "DESC" if sort_dir == "desc" else "ASC"
            query += f" ORDER BY {SORT_COLUMNS[sort_by]} {direction}"
        else:
            query += " ORDER BY lp.updated_at DESC"

        rows = db.execute(query, params).fetchall()
        result = [_post_to_dict(db, r) for r in rows]
    return result


@router.post("")
def create_post(post: LongformCreate):
    status = post.status.lower() if post.status else "draft"
    if status not in VALID_STATUSES:
        status = "draft"

    word_count = len(post.body.split()) if post.body else 0
    published_at = datetime.now().isoformat() if status == "published" else None

    with get_write_db() as db:
        cursor = db.execute(
            "INSERT INTO longform_posts (title, body, status, word_count, published_at) VALUES (?, ?, ?, ?, ?)",
            (post.title, post.body, status, word_count, published_at),
        )
        post_id = cursor.lastrowid

        if post.tags:
            _set_post_tags(db, post_id, post.tags)

        db.commit()
        row = db.execute("SELECT * FROM longform_posts WHERE id = ?", (post_id,)).fetchone()
        result = _post_to_dict(db, row)
    rebuild_fts_table("fts_longform")
    return result


@router.get("/{post_id}")
def get_post(post_id: int):
    with get_db_connection(readonly=True) as db:
        row = db.execute("SELECT * FROM longform_posts WHERE id = ?", (post_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Post not found")
        result = _post_to_detail_dict(db, row)
    return result


@router.patch("/{post_id}")
def update_post(post_id: int, update: LongformUpdate):
    with get_write_db() as db:
        existing = db.execute("SELECT * FROM longform_posts WHERE id = ?", (post_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Post not found")

        new_tags = update.tags
        update_fields = {}
        for field, value in update.model_dump(exclude_unset=True).items():
            if field == "tags":
                continue
            if field == "status" and value is not None:
                value = value.lower()
                if value not in VALID_STATUSES:
                    continue
            update_fields[field] = value

        # Recompute word_count if body changed
        extra = ["updated_at = ?"]
        extra_params: list = [datetime.now().isoformat()]

        if "body" in update_fields:
            body_text = update_fields["body"] or ""
            extra.append("word_count = ?")
            extra_params.append(len(body_text.split()))

        # Set published_at when transitioning to published
        if update.status == "published" and existing["status"] != "published":
            extra.append("published_at = ?")
            extra_params.append(datetime.now().isoformat())

        set_clause, params = safe_update_query("longform_posts", update_fields, LONGFORM_ALLOWED_COLUMNS, extra)
        params.extend(extra_params)
        params.append(post_id)
        db.execute(f"UPDATE longform_posts SET {set_clause} WHERE id = ?", params)

        if new_tags is not None:
            _set_post_tags(db, post_id, new_tags)

        db.commit()
        row = db.execute("SELECT * FROM longform_posts WHERE id = ?", (post_id,)).fetchone()
        result = _post_to_detail_dict(db, row)
    rebuild_fts_table("fts_longform")
    return result


@router.delete("/{post_id}")
def delete_post(post_id: int):
    with get_write_db() as db:
        db.execute("DELETE FROM longform_posts WHERE id = ?", (post_id,))
        db.commit()
    rebuild_fts_table("fts_longform")
    return {"ok": True}


# --- Comments / Thoughts ---


@router.post("/{post_id}/comments")
def create_comment(post_id: int, comment: LongformCommentCreate):
    with get_write_db() as db:
        exists = db.execute("SELECT id FROM longform_posts WHERE id = ?", (post_id,)).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="Post not found")

        cursor = db.execute(
            "INSERT INTO longform_comments (post_id, text, is_thought) VALUES (?, ?, ?)",
            (post_id, comment.text, 1 if comment.is_thought else 0),
        )
        comment_id = cursor.lastrowid
        db.commit()

        row = db.execute("SELECT * FROM longform_comments WHERE id = ?", (comment_id,)).fetchone()
        result = dict(row)
        result["is_thought"] = bool(result["is_thought"])
    return result


@router.delete("/{post_id}/comments/{comment_id}")
def delete_comment(post_id: int, comment_id: int):
    with get_write_db() as db:
        row = db.execute(
            "SELECT id FROM longform_comments WHERE id = ? AND post_id = ?",
            (comment_id, post_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Comment not found")

        db.execute("DELETE FROM longform_comments WHERE id = ?", (comment_id,))
        db.commit()
    return {"ok": True}


# --- Import from Claude session ---

_SESSION_TO_LONGFORM_PROMPT = (
    "You are converting a Claude Code terminal session into a well-structured blog post. "
    "Given the raw session text, produce a JSON object with two fields:\n"
    '  "title": a compelling blog post title (5-15 words)\n'
    '  "body": a clean, well-structured markdown blog post\n\n'
    "The body should:\n"
    "- Remove all conversational artifacts (prompts, ANSI codes, terminal commands)\n"
    "- Extract the key insights, decisions, and learnings\n"
    "- Organize into logical sections with headings\n"
    "- Use code blocks for any relevant code snippets\n"
    "- Be written in a professional but accessible tone\n"
    "- Include an introduction and conclusion\n"
    "Return ONLY valid JSON, no markdown fences."
)


@router.post("/from-session/{session_id}")
def create_from_session(session_id: int):
    """Create a longform post from a saved Claude session, using Gemini to clean it up."""
    from app_config import get_secret

    with get_db_connection(readonly=True) as db:
        session = db.execute("SELECT * FROM claude_sessions WHERE id = ?", (session_id,)).fetchone()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

    session = dict(session)

    # Read plain text from the session file on disk
    filepath = Path(session["filepath"]).resolve()
    # Validate the filepath is within the expected sessions directory
    from config import DATABASE_PATH

    sessions_dir = (DATABASE_PATH.parent / "claude_sessions").resolve()
    if not str(filepath).startswith(str(sessions_dir)):
        logger.warning("Session filepath outside expected directory: %s", filepath)
        plain_text = ""
    elif filepath.exists():
        with open(filepath, "r") as f:
            data = json.load(f)
            plain_text = data.get("plain_text", "")
    else:
        plain_text = ""

    if not plain_text:
        plain_text = session.get("summary", "") or session.get("preview", "")

    # Try Gemini cleanup
    api_key = get_secret("GEMINI_API_KEY") or ""
    title = session.get("title", "Untitled")
    body = plain_text

    if api_key and plain_text.strip():
        try:
            from google import genai

            client = genai.Client(api_key=api_key)
            # Truncate to last 12000 chars
            text = plain_text[-12000:] if len(plain_text) > 12000 else plain_text

            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=f"Convert this Claude Code session to a blog post:\n\n{text}",
                config={
                    "system_instruction": _SESSION_TO_LONGFORM_PROMPT,
                    "temperature": 0.3,
                    "response_mime_type": "application/json",
                },
            )

            result = json.loads(response.text)
            if isinstance(result, dict):
                title = result.get("title", title)
                body = result.get("body", body)
        except Exception as e:
            logger.warning(f"Gemini session-to-longform failed: {e}")

    word_count = len(body.split()) if body else 0

    with get_write_db() as db:
        cursor = db.execute(
            "INSERT INTO longform_posts (title, body, status, word_count, claude_session_id) VALUES (?, ?, ?, ?, ?)",
            (title, body, "draft", word_count, session_id),
        )
        post_id = cursor.lastrowid
        db.commit()

        row = db.execute("SELECT * FROM longform_posts WHERE id = ?", (post_id,)).fetchone()
        result = _post_to_dict(db, row)
    rebuild_fts_table("fts_longform")
    return result
