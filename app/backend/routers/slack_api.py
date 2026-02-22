"""Live Slack API endpoints for search, channel history, and messaging."""

import json
import os
import ssl
import time
from datetime import datetime
from typing import Optional

import certifi
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app_config import get_prompt_context, get_secret
from database import get_db_connection, get_write_db

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

    token = os.environ.get("SLACK_TOKEN", "")
    if not token:
        from pathlib import Path

        env_path = Path(__file__).parent.parent / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("SLACK_TOKEN="):
                    token = line.split("=", 1)[1].strip().strip('"')
                    break
    if not token:
        raise HTTPException(status_code=503, detail="SLACK_TOKEN not configured")

    ssl_context = ssl.create_default_context(cafile=certifi.where())
    return WebClient(token=token, ssl=ssl_context)


class SlackMessage(BaseModel):
    channel: str
    text: str
    thread_ts: Optional[str] = None


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
        raise HTTPException(status_code=500, detail=f"Slack search failed: {e}")

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
        raise HTTPException(status_code=500, detail=f"Failed to list channels: {e}")

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
        raise HTTPException(status_code=500, detail=f"Failed to get channel history: {e}")

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
        raise HTTPException(status_code=500, detail=f"Failed to get thread: {e}")

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
        raise HTTPException(status_code=500, detail=f"Failed to send message: {e}")

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
    """Call Gemini to rank Slack messages by priority."""
    api_key = get_secret("GEMINI_API_KEY") or ""
    if not api_key:
        return []

    from google import genai

    client = genai.Client(api_key=api_key)
    now = datetime.now().strftime("%A, %B %d %Y, %I:%M %p")
    user_message = f"Current time: {now}\n\nSlack messages to rank:\n{json.dumps(messages, default=str)}"

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=user_message,
        config={
            "system_instruction": _build_slack_rank_prompt(),
            "temperature": 0.2,
            "response_mime_type": "application/json",
        },
    )

    try:
        items = json.loads(response.text)
        if isinstance(items, list):
            return items
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def _dismissed_slack_ids(db) -> set[str]:
    rows = db.execute("SELECT item_id FROM dismissed_dashboard_items WHERE source = 'slack'").fetchall()
    return {r["item_id"] for r in rows}


@router.get("/prioritized")
def get_prioritized_slack(refresh: bool = Query(False), days: int = Query(7, ge=1, le=90)):
    """Return top 50 Slack messages ranked by Gemini priority score."""
    with get_db_connection(readonly=True) as db:
        dismissed = _dismissed_slack_ids(db)
        cutoff = f"-{days} days"

        # Check cache first
        if not refresh:
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
                return data

        # Fetch recent messages from DB
        rows = db.execute(
            "SELECT id, user_name, text, channel_name, channel_type, ts, is_mention, permalink "
            "FROM slack_messages "
            "WHERE datetime(ts, 'unixepoch') >= datetime('now', ?) "
            "ORDER BY ts DESC LIMIT 100",
            (cutoff,),
        ).fetchall()

    if not rows:
        return {"items": [], "error": "No Slack messages synced yet"}

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

    try:
        ranked = _rank_slack_with_gemini(messages_for_llm)
    except Exception as e:
        return {"items": [], "error": str(e)}

    # Build lookup of full message data
    msg_lookup = {r["id"]: dict(r) for r in rows}

    # Merge rankings with full message data
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

    # Sort by score desc, filter dismissed, take top 50
    items.sort(key=lambda x: x["priority_score"], reverse=True)
    items = [i for i in items if i["id"] not in dismissed][:50]

    result = {"items": items}

    # Cache result (store full unfiltered set)
    all_items_result = {"items": items}
    with get_write_db() as db:
        db.execute("DELETE FROM cached_slack_priorities")
        db.execute(
            "INSERT INTO cached_slack_priorities (data_json) VALUES (?)",
            (json.dumps(all_items_result),),
        )
        db.commit()

    return result
