"""WhatsApp chat agent — thin wrapper over agent_core with WhatsApp-specific formatting."""

import logging
import re
from datetime import datetime

from agent_core import build_system_prompt, run_agent_loop
from database import get_db_connection, get_write_db

logger = logging.getLogger(__name__)

MAX_HISTORY = 50  # rolling window of messages

WHATSAPP_FORMATTING = (
    "IMPORTANT WhatsApp formatting rules:\n"
    "- Keep responses concise and mobile-friendly\n"
    "- Use plain text, not markdown headers (no # or ##)\n"
    "- Use *bold* for emphasis (WhatsApp style)\n"
    "- Use bullet points (- or •) for lists\n"
    "- Break long responses into short paragraphs\n"
    "- Lead with the answer, not preamble\n"
)


def _get_or_create_conversation(phone_number: str) -> int:
    """Get or create a conversation for this phone number."""
    with get_write_db() as db:
        row = db.execute(
            "SELECT id FROM whatsapp_conversations WHERE phone_number = ?",
            (phone_number,),
        ).fetchone()
        if row:
            return row["id"]
        cursor = db.execute(
            "INSERT INTO whatsapp_conversations (phone_number) VALUES (?)",
            (phone_number,),
        )
        db.commit()
        return cursor.lastrowid


def _load_history(conversation_id: int) -> list[dict]:
    """Load recent conversation messages in Anthropic API format."""
    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            """SELECT role, content FROM whatsapp_messages
               WHERE conversation_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (conversation_id, MAX_HISTORY),
        ).fetchall()

    # Reverse to chronological order
    messages = []
    for r in reversed(rows):
        messages.append({"role": r["role"], "content": r["content"]})
    return messages


def _save_message(conversation_id: int, role: str, content: str, wa_id: str = ""):
    """Save a message to the database."""
    with get_write_db() as db:
        db.execute(
            """INSERT INTO whatsapp_messages (conversation_id, role, content, whatsapp_message_id)
               VALUES (?, ?, ?, ?)""",
            (conversation_id, role, content, wa_id),
        )
        db.execute(
            "UPDATE whatsapp_conversations SET last_message_at = ? WHERE id = ?",
            (datetime.now().isoformat(), conversation_id),
        )
        db.commit()


WA_CHUNK_LIMIT = 4000  # WhatsApp display limit per message


def markdown_to_whatsapp(text: str) -> str:
    """Convert markdown formatting to WhatsApp-compatible formatting."""
    # Protect fenced code blocks (already WhatsApp-compatible)
    blocks = []

    def _save_block(m):
        blocks.append(m.group(0))
        return f"\x00CODEBLOCK{len(blocks) - 1}\x00"

    text = re.sub(r"```[\s\S]*?```", _save_block, text)

    # Protect inline code
    codes = []

    def _save_code(m):
        codes.append(m.group(0))
        return f"\x00INLINE{len(codes) - 1}\x00"

    text = re.sub(r"`[^`]+`", _save_code, text)

    # Headers: ## Header → *HEADER*
    text = re.sub(r"^#{1,6}\s+(.+)$", lambda m: f"*{m.group(1).upper()}*", text, flags=re.MULTILINE)

    # Bold: **text** or __text__ → *text*
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    text = re.sub(r"__(.+?)__", r"*\1*", text)

    # Strikethrough: ~~text~~ → ~text~
    text = re.sub(r"~~(.+?)~~", r"~\1~", text)

    # Links: [text](url) → text (url)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)

    # Restore protected spans
    for i, code in enumerate(codes):
        text = text.replace(f"\x00INLINE{i}\x00", code)
    for i, block in enumerate(blocks):
        text = text.replace(f"\x00CODEBLOCK{i}\x00", block)

    return text


def chunk_message(text: str, limit: int = WA_CHUNK_LIMIT) -> list[str]:
    """Split a long message into chunks, preferring newline boundaries."""
    if len(text) <= limit:
        return [text]
    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        # Find last newline within limit
        cut = text.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return chunks


async def chat(phone_number: str, user_message: str, wa_message_id: str = "") -> str:
    """Process an incoming WhatsApp message and return the agent's response."""
    conversation_id = _get_or_create_conversation(phone_number)

    # Load history and append user message
    history = _load_history(conversation_id)
    history.append({"role": "user", "content": user_message})
    _save_message(conversation_id, "user", user_message, wa_message_id)

    system = build_system_prompt(channel_instructions=WHATSAPP_FORMATTING)

    # Run the shared agentic loop
    text = await run_agent_loop(messages=history, system_prompt=system)

    # Format for WhatsApp
    text = markdown_to_whatsapp(text)
    _save_message(conversation_id, "assistant", text)
    return text
