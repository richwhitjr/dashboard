"""Agent chat router — CRUD for conversations + SSE streaming chat endpoint."""

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent_core import build_system_prompt, run_agent_loop
from database import get_db_connection, get_write_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agent", tags=["agent"])

_CONV_COLS = "id, title, saved, created_at, updated_at"


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class CreateConversationRequest(BaseModel):
    title: str = "New conversation"


class UpdateConversationRequest(BaseModel):
    title: str


class SaveConversationRequest(BaseModel):
    title: Optional[str] = None


class ChatRequest(BaseModel):
    message: str


# ---------------------------------------------------------------------------
# Conversation CRUD
# ---------------------------------------------------------------------------


@router.get("/conversations")
def list_conversations(saved: Optional[int] = Query(None)):
    """List agent conversations, newest first. Use ?saved=1 for saved only."""
    with get_db_connection(readonly=True) as db:
        if saved is not None:
            rows = db.execute(
                f"SELECT {_CONV_COLS} FROM agent_conversations WHERE saved = ? ORDER BY updated_at DESC",
                (saved,),
            ).fetchall()
        else:
            rows = db.execute(f"SELECT {_CONV_COLS} FROM agent_conversations ORDER BY updated_at DESC").fetchall()
    return [dict(r) for r in rows]


@router.post("/conversations")
def create_conversation(req: CreateConversationRequest):
    """Create a new conversation (unsaved by default)."""
    with get_write_db() as db:
        cursor = db.execute(
            "INSERT INTO agent_conversations (title) VALUES (?)",
            (req.title,),
        )
        db.commit()
        conv_id = cursor.lastrowid
        row = db.execute(
            f"SELECT {_CONV_COLS} FROM agent_conversations WHERE id = ?",
            (conv_id,),
        ).fetchone()
    return dict(row)


@router.patch("/conversations/{conv_id}")
def update_conversation(conv_id: int, req: UpdateConversationRequest):
    """Update conversation title."""
    with get_write_db() as db:
        db.execute(
            "UPDATE agent_conversations SET title = ?, updated_at = ? WHERE id = ?",
            (req.title, datetime.now().isoformat(), conv_id),
        )
        db.commit()
        row = db.execute(
            f"SELECT {_CONV_COLS} FROM agent_conversations WHERE id = ?",
            (conv_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return dict(row)


@router.post("/conversations/{conv_id}/save")
def save_conversation(conv_id: int, req: SaveConversationRequest):
    """Mark a conversation as saved. Optionally update title."""
    with get_write_db() as db:
        now = datetime.now().isoformat()
        if req.title:
            db.execute(
                "UPDATE agent_conversations SET saved = 1, title = ?, updated_at = ? WHERE id = ?",
                (req.title, now, conv_id),
            )
        else:
            db.execute(
                "UPDATE agent_conversations SET saved = 1, updated_at = ? WHERE id = ?",
                (now, conv_id),
            )
        db.commit()
        row = db.execute(
            f"SELECT {_CONV_COLS} FROM agent_conversations WHERE id = ?",
            (conv_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return dict(row)


@router.delete("/conversations/{conv_id}")
def delete_conversation(conv_id: int):
    """Delete a conversation and all its messages."""
    with get_write_db() as db:
        db.execute("DELETE FROM agent_messages WHERE conversation_id = ?", (conv_id,))
        db.execute("DELETE FROM agent_conversations WHERE id = ?", (conv_id,))
        db.commit()
    return {"status": "ok"}


@router.get("/conversations/{conv_id}/messages")
def get_messages(conv_id: int):
    """Get all messages for a conversation."""
    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            "SELECT id, conversation_id, role, content, tool_calls_json, created_at "
            "FROM agent_messages WHERE conversation_id = ? ORDER BY created_at ASC",
            (conv_id,),
        ).fetchall()
    result = []
    for r in rows:
        msg = dict(r)
        if msg["tool_calls_json"]:
            try:
                msg["tool_calls"] = json.loads(msg["tool_calls_json"])
            except (json.JSONDecodeError, TypeError):
                msg["tool_calls"] = []
        else:
            msg["tool_calls"] = []
        del msg["tool_calls_json"]
        result.append(msg)
    return result


# ---------------------------------------------------------------------------
# SSE Chat endpoint
# ---------------------------------------------------------------------------


_SENTINEL = object()


@router.post("/conversations/{conv_id}/chat")
async def chat_sse(conv_id: int, req: ChatRequest):
    """Stream an agent response via Server-Sent Events.

    Events:
      - event: text        — final text response
      - event: tool_call   — agent is calling a tool
      - event: tool_result — tool completed
      - event: done        — response fully saved
      - event: error       — something went wrong
    """
    # Verify conversation exists
    with get_db_connection(readonly=True) as db:
        conv = db.execute("SELECT id FROM agent_conversations WHERE id = ?", (conv_id,)).fetchone()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Save user message
    with get_write_db() as db:
        db.execute(
            "INSERT INTO agent_messages (conversation_id, role, content) VALUES (?, 'user', ?)",
            (conv_id, req.message),
        )
        db.commit()

    # Use a queue to bridge between the on_event callback and the SSE generator
    queue: asyncio.Queue = asyncio.Queue()
    tool_calls_log: list[dict] = []

    async def on_event(event_type: str, data: dict):
        """Callback invoked by the agent loop — puts SSE strings into the queue."""
        if event_type == "tool_call":
            tool_calls_log.append({"name": data["name"], "input": data["input"]})
            await queue.put(f"event: tool_call\ndata: {json.dumps(data)}\n\n")
        elif event_type == "tool_result":
            # Attach result to the matching tool call for DB storage
            for tc in reversed(tool_calls_log):
                if tc["name"] == data["name"] and "result" not in tc:
                    result_str = data["result"]
                    if len(result_str) > 2000:
                        result_str = result_str[:2000] + "..."
                    tc["result"] = result_str
                    break
            await queue.put(f"event: tool_result\ndata: {json.dumps(data)}\n\n")
        elif event_type == "text":
            await queue.put(f"event: text\ndata: {json.dumps(data)}\n\n")

    async def run_agent():
        """Run the agent loop in a background task, feeding events into the queue."""
        try:
            # Load conversation history
            with get_db_connection(readonly=True) as db:
                rows = db.execute(
                    "SELECT role, content FROM agent_messages WHERE conversation_id = ? ORDER BY created_at ASC",
                    (conv_id,),
                ).fetchall()

            messages = [{"role": r["role"], "content": r["content"]} for r in rows]
            system = build_system_prompt()

            text = await run_agent_loop(
                messages=messages,
                system_prompt=system,
                on_event=on_event,
            )

            # Save assistant message
            tc_json = json.dumps(tool_calls_log) if tool_calls_log else None
            with get_write_db() as db:
                cursor = db.execute(
                    "INSERT INTO agent_messages "
                    "(conversation_id, role, content, tool_calls_json) "
                    "VALUES (?, 'assistant', ?, ?)",
                    (conv_id, text, tc_json),
                )
                db.execute(
                    "UPDATE agent_conversations SET updated_at = ? WHERE id = ?",
                    (datetime.now().isoformat(), conv_id),
                )
                db.commit()
                message_id = cursor.lastrowid

            await queue.put(f"event: done\ndata: {json.dumps({'message_id': message_id})}\n\n")
        except Exception as e:
            logger.exception("Agent chat error")
            await queue.put(f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n")
        finally:
            await queue.put(_SENTINEL)

    async def event_stream():
        """SSE generator — reads from the queue and yields events."""
        task = asyncio.create_task(run_agent())
        try:
            while True:
                item = await queue.get()
                if item is _SENTINEL:
                    break
                yield item
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
