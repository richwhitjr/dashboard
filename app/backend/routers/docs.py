"""CRUD endpoints for docs with tags, folders, comments, and AI editing."""

import io
import json
import logging
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse

from database import get_db_connection, get_write_db, rebuild_fts_table
from models import LongformAIEditRequest, LongformCommentCreate, LongformCreate, LongformUpdate
from routers.changes import bump
from utils.safe_sql import safe_update_query

logger = logging.getLogger(__name__)

DOCS_ALLOWED_COLUMNS = {"title", "body", "status", "folder"}
VALID_STATUSES = {"active", "archived"}

SORT_COLUMNS = {
    "created_at": "lp.created_at",
    "updated_at": "lp.updated_at",
    "title": "lp.title",
    "word_count": "lp.word_count",
}

router = APIRouter(prefix="/api/docs", tags=["docs"])


# --- Helpers ---


def _get_doc_tags(db, doc_id: int) -> list[str]:
    rows = db.execute("SELECT tag FROM longform_tags WHERE post_id = ? ORDER BY tag", (doc_id,)).fetchall()
    return [r["tag"] for r in rows]


def _set_doc_tags(db, doc_id: int, tags: list[str]):
    db.execute("DELETE FROM longform_tags WHERE post_id = ?", (doc_id,))
    for tag in tags:
        tag = tag.strip().lower()
        if tag:
            db.execute("INSERT OR IGNORE INTO longform_tags (post_id, tag) VALUES (?, ?)", (doc_id, tag))


def _get_doc_people(db, doc_id: int) -> list[dict]:
    rows = db.execute(
        "SELECT p.id, p.name FROM longform_post_people lpp "
        "JOIN people p ON lpp.person_id = p.id WHERE lpp.post_id = ? ORDER BY p.name",
        (doc_id,),
    ).fetchall()
    return [{"id": r["id"], "name": r["name"]} for r in rows]


def _set_doc_people(db, doc_id: int, person_ids: list[str]):
    db.execute("DELETE FROM longform_post_people WHERE post_id = ?", (doc_id,))
    for pid in person_ids:
        db.execute(
            "INSERT OR IGNORE INTO longform_post_people (post_id, person_id) VALUES (?, ?)",
            (doc_id, pid),
        )


def _get_doc_comments(db, doc_id: int) -> tuple[list[dict], list[dict]]:
    """Return (comments, thoughts) for a doc."""
    rows = db.execute(
        "SELECT * FROM longform_comments WHERE post_id = ? ORDER BY created_at ASC",
        (doc_id,),
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


def _doc_to_dict(db, row) -> dict:
    doc = dict(row)
    doc["tags"] = _get_doc_tags(db, doc["id"])
    doc["people"] = _get_doc_people(db, doc["id"])
    counts = db.execute(
        "SELECT is_thought, COUNT(*) as cnt FROM longform_comments WHERE post_id = ? GROUP BY is_thought",
        (doc["id"],),
    ).fetchall()
    doc["comment_count"] = 0
    doc["thought_count"] = 0
    for c in counts:
        if c["is_thought"]:
            doc["thought_count"] = c["cnt"]
        else:
            doc["comment_count"] = c["cnt"]
    return doc


def _doc_to_detail_dict(db, row) -> dict:
    doc = _doc_to_dict(db, row)
    comments, thoughts = _get_doc_comments(db, doc["id"])
    doc["comments"] = comments
    doc["thoughts"] = thoughts
    return doc


# --- Endpoints ---


@router.get("/tags")
def list_tags():
    """Return all distinct tags for autocomplete."""
    with get_db_connection(readonly=True) as db:
        rows = db.execute("SELECT DISTINCT tag FROM longform_tags ORDER BY tag").fetchall()
    return [r["tag"] for r in rows]


@router.get("/folders")
def list_folders():
    """Return all distinct folder names with doc counts."""
    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            "SELECT folder, COUNT(*) as count FROM longform_posts"
            " WHERE folder IS NOT NULL AND folder != '' GROUP BY folder ORDER BY folder"
        ).fetchall()
    return [{"name": r["folder"], "count": r["count"]} for r in rows]


@router.get("")
def list_docs(
    status: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    folder: Optional[str] = Query(None),
    folder_prefix: bool = Query(False),
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

        if folder:
            if folder == "__root__":
                query += " AND (lp.folder IS NULL OR lp.folder = '')"
            elif folder_prefix:
                query += " AND (lp.folder = ? OR lp.folder LIKE ?)"
                params.append(folder)
                params.append(folder + "/%")
            else:
                query += " AND lp.folder = ?"
                params.append(folder)

        # Tag filter
        if tag:
            query = query.replace("SELECT lp.* FROM longform_posts lp", "SELECT DISTINCT lp.* FROM longform_posts lp")
            query = query.replace(" WHERE ", " JOIN longform_tags lt ON lp.id = lt.post_id WHERE ")
            query += " AND lt.tag = ?"
            params.append(tag.lower())

        # FTS search
        if search:
            fts_rows = db.execute("SELECT rowid FROM fts_longform WHERE fts_longform MATCH ?", (search,)).fetchall()
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
        result = [_doc_to_dict(db, r) for r in rows]
    return result


@router.post("")
def create_doc(doc: LongformCreate):
    status = doc.status.lower() if doc.status else "active"
    if status not in VALID_STATUSES:
        status = "active"

    word_count = len(doc.body.split()) if doc.body else 0
    folder = doc.folder.strip() if doc.folder and doc.folder.strip() else None

    with get_write_db() as db:
        cursor = db.execute(
            "INSERT INTO longform_posts (title, body, status, word_count, folder) VALUES (?, ?, ?, ?, ?)",
            (doc.title, doc.body, status, word_count, folder),
        )
        doc_id = cursor.lastrowid

        if doc.tags:
            _set_doc_tags(db, doc_id, doc.tags)
        if doc.person_ids:
            _set_doc_people(db, doc_id, doc.person_ids)

        db.commit()
        row = db.execute("SELECT * FROM longform_posts WHERE id = ?", (doc_id,)).fetchone()
        result = _doc_to_dict(db, row)
    rebuild_fts_table("fts_longform")
    bump("docs")
    return result


@router.get("/{doc_id}")
def get_doc(doc_id: int):
    with get_db_connection(readonly=True) as db:
        row = db.execute("SELECT * FROM longform_posts WHERE id = ?", (doc_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Doc not found")
        result = _doc_to_detail_dict(db, row)
    return result


@router.patch("/{doc_id}")
def update_doc(doc_id: int, update: LongformUpdate):
    with get_write_db() as db:
        existing = db.execute("SELECT * FROM longform_posts WHERE id = ?", (doc_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Doc not found")

        new_tags = update.tags
        new_person_ids = update.person_ids
        update_fields = {}
        for field, value in update.model_dump(exclude_unset=True).items():
            if field in ("tags", "person_ids"):
                continue
            if field == "status" and value is not None:
                value = value.lower()
                if value not in VALID_STATUSES:
                    continue
            if field == "folder" and value is not None:
                value = value.strip() or None
            update_fields[field] = value

        extra = ["updated_at = ?"]
        extra_params: list = [datetime.now().isoformat()]

        if "body" in update_fields:
            body_text = update_fields["body"] or ""
            extra.append("word_count = ?")
            extra_params.append(len(body_text.split()))

        set_clause, params = safe_update_query("longform_posts", update_fields, DOCS_ALLOWED_COLUMNS, extra)
        params.extend(extra_params)
        params.append(doc_id)
        db.execute(f"UPDATE longform_posts SET {set_clause} WHERE id = ?", params)

        if new_tags is not None:
            _set_doc_tags(db, doc_id, new_tags)
        if new_person_ids is not None:
            _set_doc_people(db, doc_id, new_person_ids)

        db.commit()
        row = db.execute("SELECT * FROM longform_posts WHERE id = ?", (doc_id,)).fetchone()
        result = _doc_to_detail_dict(db, row)
    rebuild_fts_table("fts_longform")
    bump("docs")
    return result


@router.delete("/{doc_id}")
def delete_doc(doc_id: int):
    with get_write_db() as db:
        db.execute("DELETE FROM longform_posts WHERE id = ?", (doc_id,))
        db.commit()
    rebuild_fts_table("fts_longform")
    bump("docs")
    return {"ok": True}


# --- Comments / Thoughts ---


@router.post("/{doc_id}/comments")
def create_comment(doc_id: int, comment: LongformCommentCreate):
    with get_write_db() as db:
        exists = db.execute("SELECT id FROM longform_posts WHERE id = ?", (doc_id,)).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="Doc not found")

        cursor = db.execute(
            "INSERT INTO longform_comments (post_id, text, is_thought) VALUES (?, ?, ?)",
            (doc_id, comment.text, 1 if comment.is_thought else 0),
        )
        comment_id = cursor.lastrowid
        db.commit()

        row = db.execute("SELECT * FROM longform_comments WHERE id = ?", (comment_id,)).fetchone()
        result = dict(row)
        result["is_thought"] = bool(result["is_thought"])
    bump("docs")
    return result


@router.delete("/{doc_id}/comments/{comment_id}")
def delete_comment(doc_id: int, comment_id: int):
    with get_write_db() as db:
        row = db.execute(
            "SELECT id FROM longform_comments WHERE id = ? AND post_id = ?",
            (comment_id, doc_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Comment not found")

        db.execute("DELETE FROM longform_comments WHERE id = ?", (comment_id,))
        db.commit()
    bump("docs")
    return {"ok": True}


# --- AI Editing ---


def _build_editing_prompt(ctx: str, selected_text: str = "") -> str:
    selection_context = ""
    if selected_text:
        selection_context = (
            f"\nIMPORTANT: The user has selected this specific passage for editing:\n"
            f'"""\n{selected_text}\n"""\n'
            f"Focus your changes on this passage while keeping the rest of the document intact."
        )

    return (
        f"You are a skilled writing editor and collaborator {ctx}. "
        "You help improve documents by following editing instructions precisely.\n\n"
        "Your response must be a JSON object with two keys:\n"
        '- "revised_body": the complete revised document in Markdown format\n'
        '- "commentary": 1-3 sentences explaining what you changed and why\n\n'
        "Rules:\n"
        "1. Return the ENTIRE document in revised_body, not just the changed portion\n"
        "2. Preserve the overall structure, voice, and formatting unless asked to change it\n"
        "3. Only change what the instruction asks for — do not rewrite unrelated sections\n"
        "4. Keep the same Markdown formatting conventions as the original\n"
        "5. If the instruction is about feedback only (e.g., 'what do you think?'), set "
        "revised_body to the original unchanged text and put your feedback in commentary\n"
        "6. Be concise in commentary — explain what changed, not why the original was bad\n"
        f"{selection_context}\n"
        "Respond with ONLY valid JSON. No markdown fences, no explanation outside the JSON."
    )


def _call_gemini_edit(
    title: str,
    body: str,
    instruction: str,
    selected_text: str = "",
    history: list[dict] | None = None,
) -> dict:
    from ai_client import generate
    from app_config import get_prompt_context

    ctx = get_prompt_context()
    system_prompt = _build_editing_prompt(ctx, selected_text)

    body_text = body[-30000:] if len(body) > 30000 else body

    user_message = f"Title: {title}\n\nDocument:\n{body_text}\n\nInstruction: {instruction}"
    if history:
        history_text = "\n".join(
            f"Previous instruction: {h.get('instruction', '')}\nWhat was changed: {h.get('commentary', '')}"
            for h in history[-3:]
        )
        user_message = f"Recent editing history:\n{history_text}\n\n{user_message}"

    text = generate(system_prompt=system_prompt, user_message=user_message, json_mode=True)
    if not text:
        return {"revised_body": body, "commentary": "", "error": "AI not configured"}

    parsed = json.loads(text)
    return {
        "revised_body": parsed.get("revised_body", body),
        "commentary": parsed.get("commentary", ""),
        "error": None,
    }


@router.post("/{doc_id}/ai-edit")
def ai_edit_doc(doc_id: int, req: LongformAIEditRequest):
    """Use Gemini to edit the doc based on a natural language instruction."""
    with get_db_connection(readonly=True) as db:
        row = db.execute("SELECT id FROM longform_posts WHERE id = ?", (doc_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Doc not found")

    try:
        result = _call_gemini_edit(
            title=req.title,
            body=req.body,
            instruction=req.instruction,
            selected_text=req.selected_text,
            history=req.history,
        )
    except Exception as e:
        logger.error("AI edit failed: %s", e)
        result = {"revised_body": req.body, "commentary": "", "error": str(e)}

    return result


# --- Import from Claude session ---

_SESSION_TO_DOC_PROMPT = (
    "You are converting a Claude Code terminal session into a well-structured document. "
    "Given the raw session text, produce a JSON object with two fields:\n"
    '  "title": a clear document title (5-15 words)\n'
    '  "body": a clean, well-structured markdown document\n\n'
    "The body should:\n"
    "- Remove all conversational artifacts (prompts, ANSI codes, terminal commands)\n"
    "- Extract the key insights, decisions, and learnings\n"
    "- Organize into logical sections with headings\n"
    "- Use code blocks for any relevant code snippets\n"
    "- Be written in a professional but accessible tone\n"
    "- Include an introduction and conclusion\n"
    "Return ONLY valid JSON, no markdown fences."
)


_AGENT_CONV_TO_DOC_PROMPT = (
    "You are converting an agent chat conversation into a well-structured document. "
    "Given the raw conversation, produce a JSON object with two fields:\n"
    '  "title": a clear title (5-15 words)\n'
    '  "body": a clean, well-structured markdown document\n\n'
    "The body should:\n"
    "- Extract the key insights, decisions, and information from the conversation\n"
    "- Remove conversational filler and redundancy\n"
    "- Organize into logical sections with headings where appropriate\n"
    "- Use code blocks for any relevant code snippets\n"
    "- Be written in a professional but accessible tone\n"
    "Return ONLY valid JSON, no markdown fences."
)


@router.post("/from-agent-conversation/{conv_id}")
def create_from_agent_conversation(conv_id: int):
    """Create a doc from an agent chat conversation, using AI to clean it up."""
    with get_db_connection(readonly=True) as db:
        conv = db.execute("SELECT * FROM agent_conversations WHERE id = ?", (conv_id,)).fetchone()
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        msgs = db.execute(
            "SELECT role, content FROM agent_messages WHERE conversation_id = ? ORDER BY created_at",
            (conv_id,),
        ).fetchall()

    conv = dict(conv)
    lines = []
    for msg in msgs:
        role = "You" if msg["role"] == "user" else "Agent"
        lines.append(f"**{role}:** {msg['content']}")
    plain_text = "\n\n".join(lines)

    title = conv.get("title", "Untitled Chat")
    body = plain_text

    if plain_text.strip():
        try:
            from ai_client import generate

            text_input = plain_text[-12000:] if len(plain_text) > 12000 else plain_text
            ai_text = generate(
                system_prompt=_AGENT_CONV_TO_DOC_PROMPT,
                user_message=f"Convert this agent conversation to a document:\n\n{text_input}",
                json_mode=True,
                temperature=0.3,
            )
            if ai_text:
                result = json.loads(ai_text)
                if isinstance(result, dict):
                    title = result.get("title", title)
                    body = result.get("body", body)
        except Exception as e:
            logger.warning(f"AI agent-conv-to-doc failed: {e}")

    word_count = len(body.split()) if body else 0

    with get_write_db() as db:
        cursor = db.execute(
            "INSERT INTO longform_posts (title, body, status, word_count) VALUES (?, ?, ?, ?)",
            (title, body, "active", word_count),
        )
        doc_id = cursor.lastrowid
        db.commit()

        row = db.execute("SELECT * FROM longform_posts WHERE id = ?", (doc_id,)).fetchone()
        result = _doc_to_dict(db, row)
    rebuild_fts_table("fts_longform")
    bump("docs")
    return result


@router.post("/from-session/{session_id}")
def create_from_session(session_id: int):
    """Create a doc from a saved Claude session, using AI to clean it up."""
    with get_db_connection(readonly=True) as db:
        session = db.execute("SELECT * FROM claude_sessions WHERE id = ?", (session_id,)).fetchone()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

    session = dict(session)

    filepath = Path(session["filepath"]).resolve()
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

    title = session.get("title", "Untitled")
    body = plain_text

    if plain_text.strip():
        try:
            from ai_client import generate

            text_input = plain_text[-12000:] if len(plain_text) > 12000 else plain_text
            ai_text = generate(
                system_prompt=_SESSION_TO_DOC_PROMPT,
                user_message=f"Convert this Claude Code session to a document:\n\n{text_input}",
                json_mode=True,
                temperature=0.3,
            )
            if ai_text:
                result = json.loads(ai_text)
                if isinstance(result, dict):
                    title = result.get("title", title)
                    body = result.get("body", body)
        except Exception as e:
            logger.warning(f"AI session-to-doc failed: {e}")

    word_count = len(body.split()) if body else 0

    with get_write_db() as db:
        cursor = db.execute(
            "INSERT INTO longform_posts (title, body, status, word_count, claude_session_id) VALUES (?, ?, ?, ?, ?)",
            (title, body, "active", word_count, session_id),
        )
        doc_id = cursor.lastrowid
        db.commit()

        row = db.execute("SELECT * FROM longform_posts WHERE id = ?", (doc_id,)).fetchone()
        result = _doc_to_dict(db, row)
    rebuild_fts_table("fts_longform")
    bump("docs")
    return result


# --- Export endpoints ---


def _get_doc_raw(doc_id: int) -> dict:
    """Fetch a doc's title and body, raise 404 if missing."""
    with get_db_connection(readonly=True) as db:
        row = db.execute("SELECT id, title, body FROM longform_posts WHERE id = ?", (doc_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Doc not found")
    return {"id": row["id"], "title": row["title"], "body": row["body"] or ""}


@router.get("/{doc_id}/export/docx")
def export_docx(doc_id: int):
    """Export doc as a .docx file via pandoc."""
    doc = _get_doc_raw(doc_id)
    pandoc_bin = shutil.which("pandoc")
    if not pandoc_bin:
        for candidate in ["/opt/homebrew/bin/pandoc", "/usr/local/bin/pandoc", "/opt/homebrew/anaconda3/bin/pandoc"]:
            if Path(candidate).exists():
                pandoc_bin = candidate
                break
    if not pandoc_bin:
        raise HTTPException(status_code=503, detail="pandoc not found — install via: brew install pandoc")

    content = f"# {doc['title']}\n\n{doc['body']}"
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            [pandoc_bin, "--from=markdown", "--to=docx", f"--output={tmp_path}"],
            input=content.encode("utf-8"),
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.error("pandoc failed: %s", result.stderr.decode())
            raise HTTPException(status_code=500, detail="Failed to generate .docx")

        with open(tmp_path, "rb") as f:
            data = f.read()
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    safe_title = "".join(c for c in doc["title"] if c.isalnum() or c in " -_").strip() or "document"
    filename = f"{safe_title}.docx"
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{doc_id}/export/pdf-html", response_class=HTMLResponse)
def export_pdf_html(doc_id: int):
    """Return a print-ready HTML page for PDF generation via browser print dialog."""
    import markdown as md
    import nh3

    doc = _get_doc_raw(doc_id)
    raw_html = md.markdown(doc["body"], extensions=["fenced_code", "tables", "nl2br"])
    body_html = nh3.clean(
        raw_html,
        tags={
            "p",
            "br",
            "em",
            "strong",
            "a",
            "code",
            "pre",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "ul",
            "ol",
            "li",
            "blockquote",
            "table",
            "thead",
            "tbody",
            "tr",
            "th",
            "td",
            "img",
        },
        attributes={"a": {"href", "title"}, "img": {"src", "alt", "title"}},
    )
    title_html = doc["title"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{title_html}</title>
<style>
  body {{ font-family: Georgia, serif; max-width: 780px; margin: 40px auto;
         padding: 0 24px; color: #1a1a1a; line-height: 1.6; }}
  h1 {{ font-size: 2em; margin-bottom: 0.25em; }}
  h2 {{ font-size: 1.4em; margin-top: 1.5em; }}
  h3 {{ font-size: 1.1em; margin-top: 1.2em; }}
  pre {{ background: #f5f5f5; padding: 12px; border-radius: 4px; overflow-x: auto; font-size: 0.85em; }}
  code {{ font-family: monospace; font-size: 0.9em; background: #f0f0f0; padding: 1px 4px; border-radius: 3px; }}
  pre code {{ background: none; padding: 0; }}
  blockquote {{ border-left: 3px solid #ccc; margin-left: 0; padding-left: 16px; color: #555; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
  th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
  th {{ background: #f5f5f5; font-weight: bold; }}
  img {{ max-width: 100%; }}
  @media print {{
    body {{ margin: 0; padding: 20px; }}
    .no-print {{ display: none; }}
    a {{ color: inherit; text-decoration: none; }}
  }}
</style>
</head>
<body>
<div class="no-print" style="background:#f0f4ff;border:1px solid #c0d0ff;
  padding:10px 16px;border-radius:6px;margin-bottom:20px;font-family:sans-serif;font-size:14px;">
  Press <strong>Ctrl+P</strong> (or <strong>&#8984;+P</strong> on Mac) and choose <strong>"Save as PDF"</strong>.
</div>
<h1>{title_html}</h1>
{body_html}
<script>setTimeout(function() {{ window.print(); }}, 400);</script>
</body>
</html>"""
    return HTMLResponse(content=html)


@router.post("/{doc_id}/export/notion")
def export_to_notion(doc_id: int, parent_id: Optional[str] = None, parent_type: str = "page_id"):
    """Create a Notion page from this doc and populate it with the body.

    If parent_id is omitted the page is created in the user's private workspace root.
    """
    import httpx

    from routers.notion_api import NOTION_API_BASE, _get_headers

    doc = _get_doc_raw(doc_id)
    headers = _get_headers()

    parent: dict = {"workspace": True} if not parent_id else {parent_type: parent_id}
    page_body: dict = {
        "parent": parent,
        "properties": {
            "title": {"title": [{"text": {"content": doc["title"]}}]},
        },
    }
    try:
        with httpx.Client(timeout=20) as client:
            resp = client.post(f"{NOTION_API_BASE}/pages", headers=headers, json=page_body)
            resp.raise_for_status()
            page_data = resp.json()
    except Exception as e:
        logger.error("Failed to create Notion page: %s", e)
        raise HTTPException(status_code=500, detail="Failed to create Notion page")

    page_id = page_data["id"]
    page_url = page_data.get("url", f"https://notion.so/{page_id.replace('-', '')}")

    raw_body = doc["body"].strip()
    if raw_body:
        paragraphs = [p.strip() for p in raw_body.split("\n\n") if p.strip()]
        blocks = [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": para[:2000]}}]},
            }
            for para in paragraphs
        ]
        for i in range(0, len(blocks), 100):
            batch = blocks[i : i + 100]
            try:
                with httpx.Client(timeout=20) as client:
                    resp = client.patch(
                        f"{NOTION_API_BASE}/blocks/{page_id}/children",
                        headers=headers,
                        json={"children": batch},
                    )
                    resp.raise_for_status()
            except Exception as e:
                logger.warning("Failed to append Notion blocks (batch %d): %s", i // 100, e)

    return {"url": page_url, "page_id": page_id}


@router.post("/{doc_id}/export/google-docs")
def export_to_google_docs(doc_id: int, folder_id: Optional[str] = None):
    """Create a Google Doc from this doc."""
    from googleapiclient.discovery import build

    from routers.drive_api import get_google_credentials

    doc = _get_doc_raw(doc_id)
    content = f"# {doc['title']}\n\n{doc['body']}"

    try:
        creds = get_google_credentials()
        docs_service = build("docs", "v1", credentials=creds)
    except Exception as e:
        logger.error("Google Docs not authenticated: %s", e)
        raise HTTPException(status_code=503, detail="Google Docs not authenticated")

    try:
        result = docs_service.documents().create(body={"title": doc["title"]}).execute()
        gdoc_id = result["documentId"]

        if content.strip():
            docs_service.documents().batchUpdate(
                documentId=gdoc_id,
                body={"requests": [{"insertText": {"location": {"index": 1}, "text": content}}]},
            ).execute()

        if folder_id:
            drive_service = build("drive", "v3", credentials=creds)
            drive_service.files().update(
                fileId=gdoc_id,
                addParents=folder_id,
                fields="id, parents",
            ).execute()
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to create Google Doc: %s", e)
        raise HTTPException(status_code=500, detail="Failed to create Google Doc")

    return {
        "url": f"https://docs.google.com/document/d/{gdoc_id}/edit",
        "doc_id": gdoc_id,
    }
