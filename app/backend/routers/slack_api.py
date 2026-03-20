"""Live Slack API endpoints for search, channel history, and messaging."""

import json
import logging
import os
import ssl
import time
from datetime import datetime
from typing import Optional

import certifi
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel

from app_config import get_prompt_context, get_secret
from database import get_db_connection, get_write_db
from models import SlackMessageEdit, SlackReaction
from routers._ranking_cache import compute_items_hash

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/slack", tags=["slack"])


def _ts_within_days(ts_str: str | None, days: int) -> bool:
    """Check if a Slack timestamp is within the given number of days."""
    if not ts_str:
        return False
    try:
        cutoff = time.time() - (days * 86400)
        return float(ts_str) >= cutoff
    except (ValueError, TypeError):
        return True


def _get_client():
    try:
        from slack_sdk import WebClient
    except ImportError:
        raise HTTPException(status_code=503, detail="slack_sdk not installed")

    token = get_secret("SLACK_TOKEN") or os.environ.get("SLACK_TOKEN", "")
    if not token:
        raise HTTPException(status_code=503, detail="SLACK_TOKEN not configured")

    ssl_context = ssl.create_default_context(cafile=certifi.where())
    return WebClient(token=token, ssl=ssl_context)


class SlackMessage(BaseModel):
    channel: str
    text: str
    thread_ts: Optional[str] = None


@router.get("/all")
def get_all_slack(
    offset: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
    q: str | None = Query(None, description="Text search on message, user, channel"),
    author: str | None = Query(None, description="Filter by username"),
    from_date: str | None = Query(None, description="ISO date string, e.g. 2026-01-01"),
    to_date: str | None = Query(None, description="ISO date string, inclusive"),
):
    """Return all synced Slack messages, newest first, with pagination and optional search."""
    from datetime import datetime, timezone

    conditions: list[str] = []
    params: list = []

    if q:
        like = f"%{q}%"
        conditions.append("(text LIKE ? OR user_name LIKE ? OR channel_name LIKE ?)")
        params.extend([like, like, like])
    if author:
        conditions.append("user_name LIKE ?")
        params.append(f"%{author}%")
    if from_date:
        ts = datetime.fromisoformat(from_date).replace(tzinfo=timezone.utc).timestamp()
        conditions.append("CAST(ts AS REAL) >= ?")
        params.append(ts)
    if to_date:
        ts = datetime.fromisoformat(to_date).replace(tzinfo=timezone.utc).timestamp() + 86400
        conditions.append("CAST(ts AS REAL) <= ?")
        params.append(ts)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            f"SELECT id, channel_name, channel_type, user_name, text, ts, is_mention, permalink "
            f"FROM slack_messages {where} ORDER BY ts DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        total = db.execute(f"SELECT COUNT(*) as c FROM slack_messages {where}", params).fetchone()["c"]
    return {
        "items": [dict(r) for r in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < total,
    }


@router.get("/search")
def search_slack(
    q: str = Query(..., description="Slack search query (supports from:, in:, has:, etc.)"),
    count: int = Query(20, ge=1, le=100),
):
    """Search messages across the entire Slack workspace."""
    client = _get_client()
    try:
        result = client.search_messages(query=q, count=count)
    except Exception as e:
        logger.error("Slack search failed: %s", e)
        raise HTTPException(status_code=500, detail="Slack search failed")

    matches = result.get("messages", {}).get("matches", [])
    messages = []
    for m in matches:
        channel = m.get("channel", {})
        messages.append(
            {
                "text": m.get("text", ""),
                "user": m.get("username", ""),
                "channel_id": channel.get("id", ""),
                "channel_name": channel.get("name", ""),
                "ts": m.get("ts", ""),
                "thread_ts": m.get("thread_ts"),
                "permalink": m.get("permalink", ""),
            }
        )

    total = result.get("messages", {}).get("total", 0)
    return {"query": q, "total": total, "count": len(messages), "messages": messages}


@router.get("/channels")
def list_channels(
    types: str = Query("public_channel,private_channel", description="Channel types to list"),
    limit: int = Query(100, ge=1, le=200),
):
    """List accessible Slack channels."""
    client = _get_client()
    try:
        result = client.conversations_list(types=types, limit=limit, exclude_archived=True)
    except Exception as e:
        logger.error("Failed to list channels: %s", e)
        raise HTTPException(status_code=500, detail="Failed to list channels")

    channels = []
    for ch in result.get("channels", []):
        channels.append(
            {
                "id": ch.get("id", ""),
                "name": ch.get("name", ""),
                "is_private": ch.get("is_private", False),
                "is_member": ch.get("is_member", False),
                "topic": ch.get("topic", {}).get("value", ""),
                "purpose": ch.get("purpose", {}).get("value", ""),
                "num_members": ch.get("num_members", 0),
            }
        )

    return {"count": len(channels), "channels": channels}


@router.get("/channels/{channel_id}/history")
def channel_history(
    channel_id: str,
    limit: int = Query(20, ge=1, le=100),
    oldest: Optional[str] = Query(None, description="Start of time range (Unix ts)"),
    latest: Optional[str] = Query(None, description="End of time range (Unix ts)"),
):
    """Get recent messages from a channel."""
    client = _get_client()
    try:
        kwargs = {"channel": channel_id, "limit": limit}
        if oldest:
            kwargs["oldest"] = oldest
        if latest:
            kwargs["latest"] = latest
        result = client.conversations_history(**kwargs)
    except Exception as e:
        logger.error("Failed to get channel history: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get channel history")

    messages = []
    for msg in result.get("messages", []):
        messages.append(
            {
                "text": msg.get("text", ""),
                "user": msg.get("user", ""),
                "ts": msg.get("ts", ""),
                "thread_ts": msg.get("thread_ts"),
                "reply_count": msg.get("reply_count", 0),
                "reactions": [
                    {"name": r.get("name", ""), "count": r.get("count", 0)} for r in msg.get("reactions", [])
                ],
            }
        )

    return {"channel_id": channel_id, "count": len(messages), "messages": messages}


@router.get("/thread/{channel_id}/{thread_ts}")
def get_thread(channel_id: str, thread_ts: str):
    """Get all replies in a thread."""
    client = _get_client()
    try:
        result = client.conversations_replies(channel=channel_id, ts=thread_ts)
    except Exception as e:
        logger.error("Failed to get thread: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get thread")

    messages = []
    for msg in result.get("messages", []):
        messages.append(
            {
                "text": msg.get("text", ""),
                "user": msg.get("user", ""),
                "ts": msg.get("ts", ""),
            }
        )

    return {"channel_id": channel_id, "thread_ts": thread_ts, "count": len(messages), "messages": messages}


@router.patch("/message")
def edit_message(msg: SlackMessageEdit):
    """Edit an existing Slack message."""
    client = _get_client()
    try:
        result = client.chat_update(channel=msg.channel, ts=msg.ts, text=msg.text)
    except Exception as e:
        logger.error("Failed to edit message: %s", e)
        raise HTTPException(status_code=500, detail="Failed to edit message")
    return {"ok": result.get("ok"), "channel": result.get("channel"), "ts": result.get("ts")}


@router.delete("/message")
def delete_message(channel: str = Query(...), ts: str = Query(...)):
    """Delete a Slack message."""
    client = _get_client()
    try:
        result = client.chat_delete(channel=channel, ts=ts)
    except Exception as e:
        logger.error("Failed to delete message: %s", e)
        raise HTTPException(status_code=500, detail="Failed to delete message")
    return {"ok": result.get("ok")}


@router.post("/react")
def add_reaction(reaction: SlackReaction):
    """Add an emoji reaction to a message."""
    client = _get_client()
    try:
        result = client.reactions_add(channel=reaction.channel, timestamp=reaction.ts, name=reaction.name)
    except Exception as e:
        logger.error("Failed to add reaction: %s", e)
        raise HTTPException(status_code=500, detail="Failed to add reaction")
    return {"ok": result.get("ok")}


@router.delete("/react")
def remove_reaction(channel: str = Query(...), ts: str = Query(...), name: str = Query(...)):
    """Remove an emoji reaction from a message."""
    client = _get_client()
    try:
        result = client.reactions_remove(channel=channel, timestamp=ts, name=name)
    except Exception as e:
        logger.error("Failed to remove reaction: %s", e)
        raise HTTPException(status_code=500, detail="Failed to remove reaction")
    return {"ok": result.get("ok")}


@router.post("/send")
def send_message(msg: SlackMessage):
    """Send a message to a Slack channel or DM."""
    client = _get_client()
    try:
        kwargs = {"channel": msg.channel, "text": msg.text}
        if msg.thread_ts:
            kwargs["thread_ts"] = msg.thread_ts
        result = client.chat_postMessage(**kwargs)
    except Exception as e:
        logger.error("Failed to send message: %s", e)
        raise HTTPException(status_code=500, detail="Failed to send message")

    return {
        "ok": result.get("ok", False),
        "channel": result.get("channel", ""),
        "ts": result.get("ts", ""),
        "message": result.get("message", {}).get("text", ""),
    }


# --- Gemini-ranked Slack messages ---


def _build_slack_rank_prompt() -> str:
    ctx = get_prompt_context()
    return f"""\
You are a priority-ranking assistant {ctx}. You will receive a list of \
recent Slack messages. Your job is to rank them by importance/priority for the user.

For each message, assign a priority_score from 1-10 where:
- 10: Urgent, needs immediate attention (direct questions to the user, production issues, exec requests)
- 7-9: High priority (important decisions, team blockers, project updates needing input)
- 4-6: Medium (useful context, FYI updates, interesting discussions)
- 1-3: Low (chitchat, automated notifications, irrelevant channels)

Consider:
1. Direct messages and mentions of the user are highest priority
2. Messages from direct reports and executives matter more
3. Questions awaiting the user's response are urgent
4. Production issues, incidents, or blockers are urgent
5. Project updates and decisions are medium-high
6. General channel chatter and automated bot messages are low

Return ONLY valid JSON — an array of objects with keys: id, priority_score, reason (one short sentence).
Order by priority_score descending. Return ALL messages provided, scored."""


def _rank_slack_with_gemini(messages: list[dict]) -> list[dict]:
    """Rank Slack messages by priority using the configured AI provider."""
    from ai_client import generate

    now = datetime.now().strftime("%A, %B %d %Y, %I:%M %p")
    user_message = f"Current time: {now}\n\nSlack messages to rank:\n{json.dumps(messages, default=str)}"

    text = generate(system_prompt=_build_slack_rank_prompt(), user_message=user_message, json_mode=True)
    if not text:
        return []

    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def _dismissed_slack_ids(db) -> set[str]:
    rows = db.execute("SELECT item_id FROM dismissed_dashboard_items WHERE source = 'slack'").fetchall()
    return {r["item_id"] for r in rows}


def rerank_slack(days: int = 7) -> bool:
    """Rerank Slack items — updates cache if data changed. Returns True if cache was updated."""
    from routers._ranking_cache import finish_reranking, start_reranking

    if not start_reranking("slack"):
        return False
    try:
        return _do_rerank_slack(days)
    finally:
        finish_reranking("slack")


def _do_rerank_slack(days: int = 7) -> bool:
    cutoff = f"-{days} days"
    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            "SELECT id, user_name, text, channel_name, channel_type, ts, is_mention, permalink "
            "FROM slack_messages "
            "WHERE datetime(ts, 'unixepoch') >= datetime('now', ?) "
            "ORDER BY ts DESC LIMIT 100",
            (cutoff,),
        ).fetchall()

    if not rows:
        return False

    messages_for_llm = [
        {
            "id": r["id"],
            "user_name": r["user_name"],
            "text": r["text"][:500],
            "channel_name": r["channel_name"],
            "channel_type": r["channel_type"],
            "is_mention": bool(r["is_mention"]),
        }
        for r in rows
    ]

    items_hash = compute_items_hash(messages_for_llm)
    with get_db_connection(readonly=True) as db:
        cached = db.execute("SELECT data_hash FROM cached_slack_priorities ORDER BY id DESC LIMIT 1").fetchone()
        if cached and cached["data_hash"] == items_hash:
            return False

    logger.info("Slack rerank — calling AI (%d messages)", len(messages_for_llm))
    try:
        ranked = _rank_slack_with_gemini(messages_for_llm)
    except Exception as e:
        logger.error("Slack rerank failed: %s", e)
        return False

    msg_lookup = {r["id"]: dict(r) for r in rows}
    items = []
    for rank in ranked:
        msg_id = rank.get("id", "")
        msg = msg_lookup.get(msg_id)
        if not msg:
            continue
        items.append(
            {
                "id": msg["id"],
                "user_name": msg["user_name"],
                "text": msg["text"],
                "channel_name": msg["channel_name"],
                "channel_type": msg["channel_type"],
                "ts": msg["ts"],
                "is_mention": bool(msg["is_mention"]),
                "permalink": msg["permalink"],
                "priority_score": rank.get("priority_score", 5),
                "priority_reason": rank.get("reason", ""),
            }
        )

    items.sort(key=lambda x: x["priority_score"], reverse=True)
    items = items[:50]

    if not items:
        logger.warning("Slack rerank produced 0 items — not caching empty result")
        return False

    result = {"items": items}

    with get_write_db() as db:
        db.execute("DELETE FROM cached_slack_priorities")
        db.execute(
            "INSERT INTO cached_slack_priorities (data_json, data_hash) VALUES (?, ?)",
            (json.dumps(result), items_hash),
        )
        db.commit()

    logger.info("Slack rerank complete — %d items cached", len(items))
    return True


@router.get("/prioritized")
def get_prioritized_slack(
    refresh: bool = Query(False),
    days: int = Query(7, ge=1, le=90),
    background_tasks: BackgroundTasks = None,
):
    """Return top 50 Slack messages ranked by Gemini priority score."""
    from routers._ranking_cache import is_reranking

    with get_db_connection(readonly=True) as db:
        dismissed = _dismissed_slack_ids(db)
        cached = db.execute(
            "SELECT data_json, generated_at FROM cached_slack_priorities ORDER BY id DESC LIMIT 1"
        ).fetchone()

    if cached:
        data = json.loads(cached["data_json"])
        data["items"] = [
            item
            for item in data.get("items", [])
            if item["id"] not in dismissed and _ts_within_days(item.get("ts"), days)
        ]

        if not refresh:
            return data

        # Stale-while-revalidate: return cached data, rerank in background
        if background_tasks and not is_reranking("slack"):
            background_tasks.add_task(rerank_slack, days)
        data["stale"] = True
        return data

    # No cache — synchronous first-time ranking
    result = _do_rerank_slack(days)
    if not result:
        return {"items": [], "error": "No Slack messages synced yet"}

    with get_db_connection(readonly=True) as db:
        cached = db.execute("SELECT data_json FROM cached_slack_priorities ORDER BY id DESC LIMIT 1").fetchone()
        if cached:
            data = json.loads(cached["data_json"])
            data["items"] = [
                item
                for item in data.get("items", [])
                if item["id"] not in dismissed and _ts_within_days(item.get("ts"), days)
            ]
            return data

    return {"items": []}
