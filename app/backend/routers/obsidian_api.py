"""Obsidian vault API — synced notes with LLM prioritization."""

import json
import logging
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Query

from app_config import get_prompt_context
from database import get_db_connection, get_write_db
from routers._ranking_cache import compute_items_hash

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/obsidian", tags=["obsidian"])


# --- Vault config ---


@router.get("/vault")
def get_vault_config():
    """Return current vault path (auto-detected or configured)."""
    from app_config import load_config
    from connectors.obsidian import get_vault_path

    cfg = load_config()
    configured_path = cfg.get("connectors", {}).get("obsidian", {}).get("vault_path")
    detected_path = get_vault_path()

    return {
        "configured_path": configured_path,
        "detected_path": str(detected_path) if detected_path else None,
        "active_path": str(detected_path) if detected_path else None,
    }


@router.post("/vault")
def set_vault_path(body: dict):
    """Set or clear custom vault path."""
    from app_config import save_config

    vault_path = body.get("vault_path", "").strip()
    if vault_path:
        from pathlib import Path

        p = Path(vault_path).expanduser()
        if not p.is_dir():
            return {"error": f"Directory not found: {vault_path}"}
        save_config({"connectors": {"obsidian": {"vault_path": str(p)}}})
        return {"status": "ok", "vault_path": str(p)}
    else:
        # Clear custom path, revert to auto-detect
        save_config({"connectors": {"obsidian": {"vault_path": None}}})
        return {"status": "ok", "vault_path": None}


# --- Paginated list of all synced notes ---


@router.get("/all")
def get_all_notes(
    offset: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=200),
    q: str | None = Query(None, description="Search query (title, content preview, tags)"),
    from_date: str | None = Query(None, description="ISO date string, e.g. 2026-01-01"),
    to_date: str | None = Query(None, description="ISO date string, inclusive"),
):
    conditions: list[str] = []
    params: list = []

    if q:
        like = f"%{q}%"
        conditions.append("(title LIKE ? OR content_preview LIKE ? OR tags LIKE ?)")
        params.extend([like, like, like])
    if from_date:
        conditions.append("modified_time >= ?")
        params.append(from_date)
    if to_date:
        conditions.append("modified_time <= ?")
        params.append(to_date + "T23:59:59")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            f"SELECT id, title, relative_path, folder, content_preview, tags, wiki_links, "
            f"word_count, created_time, modified_time "
            f"FROM obsidian_notes {where} ORDER BY modified_time DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        total = db.execute(f"SELECT COUNT(*) as c FROM obsidian_notes {where}", params).fetchone()["c"]

    return {
        "items": [dict(r) for r in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < total,
    }


# --- Single note detail ---


@router.get("/note/{note_id}")
def get_note(note_id: str):
    with get_db_connection(readonly=True) as db:
        row = db.execute("SELECT * FROM obsidian_notes WHERE id = ?", (note_id,)).fetchone()
    if not row:
        return {"error": "Note not found"}
    return dict(row)


# --- LLM Prioritized endpoint ---


def _build_obsidian_rank_prompt() -> str:
    ctx = get_prompt_context()
    return f"""\
You are a priority-ranking assistant {ctx}. You will receive a list of \
Obsidian vault notes. Rank them by importance and relevance to the user right now.

For each note, assign a priority_score from 1-10 where:
- 10: Notes modified today, active meeting prep, urgent project notes
- 7-9: Recently edited notes in key folders (Meetings, People), notes with many links
- 4-6: Older weekly notes, general thoughts, reference material
- 1-3: Stale notes, empty stubs, archived content

Consider:
1. Recently modified notes are more relevant
2. Notes in Meetings/ and People/ folders relate to active work
3. Notes with many wiki links are well-connected and likely important
4. Weekly notes for the current/recent weeks are high priority
5. Higher word count suggests more substantive content
6. Tags and frontmatter provide context about the note's purpose

Return ONLY valid JSON — an array of objects with keys: id, priority_score, reason (one short sentence).
Order by priority_score descending. Return ALL notes provided, scored."""


def _rank_obsidian_with_ai(notes: list[dict]) -> list[dict]:
    """Rank Obsidian notes using the configured AI provider."""
    from ai_client import generate

    now = datetime.now().strftime("%A, %B %d %Y, %I:%M %p")
    user_message = f"Current time: {now}\n\nObsidian notes to rank:\n{json.dumps(notes, default=str)}"

    text = generate(system_prompt=_build_obsidian_rank_prompt(), user_message=user_message, json_mode=True)
    if not text:
        return []

    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def _dismissed_obsidian_ids(db) -> set[str]:
    rows = db.execute("SELECT item_id FROM dismissed_dashboard_items WHERE source = 'obsidian'").fetchall()
    return {r["item_id"] for r in rows}


def rerank_obsidian(days: int = 365) -> bool:
    """Rerank Obsidian notes — updates cache if data changed. Returns True if cache was updated."""
    from routers._ranking_cache import finish_reranking, start_reranking

    if not start_reranking("obsidian"):
        return False
    try:
        return _do_rerank_obsidian(days)
    finally:
        finish_reranking("obsidian")


def _do_rerank_obsidian(days: int = 365) -> bool:
    cutoff = f"-{days} days"
    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            "SELECT id, title, relative_path, folder, content_preview, tags, wiki_links, "
            "word_count, modified_time "
            "FROM obsidian_notes "
            "WHERE modified_time >= datetime('now', ?) "
            "ORDER BY modified_time DESC LIMIT 100",
            (cutoff,),
        ).fetchall()
        # Fallback: if date filter returns nothing, rank all notes
        if not rows:
            rows = db.execute(
                "SELECT id, title, relative_path, folder, content_preview, tags, wiki_links, "
                "word_count, modified_time "
                "FROM obsidian_notes "
                "ORDER BY modified_time DESC LIMIT 100",
            ).fetchall()

    if not rows:
        return False

    notes_for_llm = []
    note_lookup = {}
    for r in rows:
        rd = dict(r)
        notes_for_llm.append(
            {
                "id": rd["id"],
                "title": rd["title"],
                "folder": rd["folder"],
                "tags": rd["tags"],
                "wiki_links": rd["wiki_links"],
                "word_count": rd["word_count"],
                "modified_time": rd["modified_time"],
                "preview": (rd["content_preview"] or "")[:300],
            }
        )
        note_lookup[rd["id"]] = rd

    items_hash = compute_items_hash(notes_for_llm)
    with get_db_connection(readonly=True) as db:
        cached = db.execute("SELECT data_hash FROM cached_obsidian_priorities ORDER BY id DESC LIMIT 1").fetchone()
        if cached and cached["data_hash"] == items_hash:
            return False

    logger.info("Obsidian rerank — calling AI (%d notes)", len(notes_for_llm))
    try:
        ranked = _rank_obsidian_with_ai(notes_for_llm)
    except Exception as e:
        logger.error("Obsidian rerank failed: %s", e)
        return False

    items = []
    for rank in ranked:
        nid = rank.get("id", "")
        note_data = note_lookup.get(nid)
        if not note_data:
            continue
        items.append(
            {
                **note_data,
                "priority_score": rank.get("priority_score", 5),
                "priority_reason": rank.get("reason", ""),
            }
        )

    items.sort(key=lambda x: x["priority_score"], reverse=True)
    items = items[:50]

    if not items:
        logger.warning("Obsidian rerank produced 0 items — not caching empty result")
        return False

    result = {"items": items}

    with get_write_db() as db:
        db.execute("DELETE FROM cached_obsidian_priorities")
        db.execute(
            "INSERT INTO cached_obsidian_priorities (data_json, data_hash) VALUES (?, ?)",
            (json.dumps(result, default=str), items_hash),
        )
        db.commit()

    logger.info("Obsidian rerank complete — %d items cached", len(items))
    return True


@router.get("/prioritized")
def get_prioritized_obsidian(
    refresh: bool = Query(False),
    days: int = Query(365, ge=1, le=3650),
    background_tasks: BackgroundTasks = None,
):
    """Return Obsidian notes ranked by AI priority score."""
    from routers._ranking_cache import is_reranking

    with get_db_connection(readonly=True) as db:
        dismissed = _dismissed_obsidian_ids(db)
        cached = db.execute(
            "SELECT data_json, generated_at FROM cached_obsidian_priorities ORDER BY id DESC LIMIT 1"
        ).fetchone()

    if cached:
        data = json.loads(cached["data_json"])
        data["items"] = [item for item in data.get("items", []) if item["id"] not in dismissed]

        if not refresh:
            return data

        if background_tasks and not is_reranking("obsidian"):
            background_tasks.add_task(rerank_obsidian, days)
        data["stale"] = True
        return data

    # No cache — kick off background ranking and return immediately
    if background_tasks and not is_reranking("obsidian"):
        background_tasks.add_task(rerank_obsidian, days)
    return {"items": [], "stale": True}
