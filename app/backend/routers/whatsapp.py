"""WhatsApp integration — receives messages from Baileys sidecar, processes with Claude agent."""

import logging
import re
import secrets
import subprocess
import time
from collections import defaultdict
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException

from app_config import get_profile
from config import DATA_DIR, REPO_ROOT
from database import get_db_connection, get_write_db
from models import WhatsAppIncoming
from whatsapp_agent import chat as agent_chat
from whatsapp_agent import chunk_message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])

BAILEYS_BASE = "http://localhost:3001"

# --- Webhook auth: shared token between sidecar and backend ---
_WEBHOOK_TOKEN_PATH = DATA_DIR / ".whatsapp_webhook_token"

MAX_MESSAGE_LENGTH = 4096  # Max chars per incoming message


def _get_or_create_webhook_token() -> str:
    """Get or create a shared webhook token for sidecar <-> backend auth."""
    if _WEBHOOK_TOKEN_PATH.exists():
        token = _WEBHOOK_TOKEN_PATH.read_text().strip()
        if token:
            return token
    token = secrets.token_urlsafe(32)
    _WEBHOOK_TOKEN_PATH.write_text(token)
    import os
    import stat
    os.chmod(_WEBHOOK_TOKEN_PATH, stat.S_IRUSR | stat.S_IWUSR)  # 0600
    return token


# Create token eagerly at import time so it exists before sidecar starts
_webhook_token: str = _get_or_create_webhook_token()


def get_webhook_token() -> str:
    return _webhook_token


def _verify_webhook_token(x_webhook_token: str | None = Header(None)):
    """Verify the sidecar webhook token."""
    if not x_webhook_token or x_webhook_token != get_webhook_token():
        raise HTTPException(status_code=403, detail="Invalid or missing webhook token")


# --- Rate limiting ---
_rate_limit: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT_MAX = 10  # max messages per window
RATE_LIMIT_WINDOW = 60  # seconds


def _check_rate_limit(sender: str) -> bool:
    """Return True if the sender is within rate limits."""
    now = time.time()
    timestamps = _rate_limit[sender]
    # Prune old entries
    _rate_limit[sender] = [t for t in timestamps if now - t < RATE_LIMIT_WINDOW]
    if len(_rate_limit[sender]) >= RATE_LIMIT_MAX:
        return False
    _rate_limit[sender].append(now)
    return True


# --- Phone normalization ---
def _normalize_phone(phone: str) -> str:
    """Normalize phone number for comparison: strip @domain, +, -, spaces, parens."""
    return re.sub(r"[^0-9]", "", phone.split("@")[0])


# --- Group name sanitization ---
def _sanitize_group_name(name: str) -> str:
    """Sanitize group name to prevent prompt injection."""
    # Strip control chars, limit length, remove anything that looks like instructions
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)  # strip control chars
    return name[:80]  # cap length


async def _process_and_reply(sender: str, text: str, message_id: str, group_context: str = ""):
    """Process message through Claude agent and send reply via Baileys."""
    try:
        # Prepend group context so the agent knows it's a group chat
        full_text = f"{group_context}{text}" if group_context else text
        logger.info("WhatsApp: processing message from %s: %s", sender[:20], text[:50])
        response_text = await agent_chat(sender, full_text, message_id)
        logger.info("WhatsApp: agent replied (%d chars)", len(response_text))

        chunks = chunk_message(response_text)
        async with httpx.AsyncClient(timeout=30) as client:
            for chunk in chunks:
                r = await client.post(
                    f"{BAILEYS_BASE}/send",
                    json={"to": sender, "text": chunk},
                )
                if r.status_code != 200:
                    logger.error("Baileys send failed: %d %s", r.status_code, r.text)
                    break
            # Send checkmark reaction after reply
            if message_id:
                try:
                    await client.post(
                        f"{BAILEYS_BASE}/react",
                        json={"jid": sender, "messageId": message_id, "emoji": "\u2705"},
                    )
                except Exception:
                    pass
    except Exception:
        logger.exception("Failed to process WhatsApp message")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    f"{BAILEYS_BASE}/send",
                    json={"to": sender, "text": "Sorry, I hit an error processing that. Try again?"},
                )
        except Exception:
            pass


@router.post("/incoming")
async def incoming_message(
    body: WhatsAppIncoming,
    background_tasks: BackgroundTasks,
    x_webhook_token: str | None = Header(None),
):
    """Handle incoming WhatsApp message from Baileys sidecar."""
    # Verify webhook token from sidecar
    _verify_webhook_token(x_webhook_token)

    # Enforce message size limit
    if len(body.text) > MAX_MESSAGE_LENGTH:
        return {"status": "rejected", "reason": f"Message too long (max {MAX_MESSAGE_LENGTH} chars)"}

    profile = get_profile()
    config_phone = profile.get("whatsapp_phone", "")

    # Security: only respond to the configured phone number (or self-messages from linked device)
    if not config_phone:
        return {"status": "ignored", "reason": "whatsapp_phone not configured in profile"}

    # Group messages are already filtered by mention gating in the sidecar
    # For DMs, verify the sender matches the configured phone
    if not body.from_self and not body.is_group:
        sender_number = _normalize_phone(body.sender)
        config_number = _normalize_phone(config_phone)

        if sender_number != config_number:
            logger.debug("Ignoring message from %s (expected %s)", sender_number, config_number)
            return {"status": "ignored", "reason": "unauthorized sender"}

    # Rate limit per sender
    if not _check_rate_limit(body.sender):
        logger.warning("Rate limit exceeded for %s", body.sender[:20])
        return {"status": "rejected", "reason": "rate limit exceeded"}

    # Build group context prefix for the agent (sanitized)
    group_context = ""
    if body.is_group and body.group_name:
        safe_name = _sanitize_group_name(body.group_name)
        group_context = f"[Group: {safe_name}] "

    background_tasks.add_task(_process_and_reply, body.sender, body.text, body.message_id, group_context)

    return {"status": "processing"}


@router.get("/status")
async def whatsapp_status():
    """Proxy WhatsApp connection status from Baileys sidecar."""
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"{BAILEYS_BASE}/status")
            return r.json()
    except Exception:
        return {"connected": False, "error": "WhatsApp sidecar not running"}


@router.get("/qr")
async def whatsapp_qr():
    """Proxy QR code from Baileys sidecar for pairing."""
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"{BAILEYS_BASE}/qr")
            return r.json()
    except Exception:
        return {"error": "WhatsApp sidecar not running — click Start below"}


@router.post("/start")
async def start_sidecar():
    """Start the WhatsApp Baileys sidecar process."""
    # Check if already running
    try:
        r = httpx.get(f"{BAILEYS_BASE}/status", timeout=2)
        if r.status_code == 200:
            return {"status": "already_running", **r.json()}
    except Exception:
        pass

    # Start the sidecar
    whatsapp_dir = REPO_ROOT / "app" / "whatsapp"
    try:
        subprocess.Popen(
            ["node", "index.js"],
            cwd=str(whatsapp_dir),
            stdout=open("/tmp/dashboard-whatsapp.log", "a"),
            stderr=subprocess.STDOUT,
        )
    except Exception as e:
        return {"status": "error", "error": str(e)}

    # Wait briefly and check if it started
    import asyncio

    await asyncio.sleep(2)
    try:
        r = httpx.get(f"{BAILEYS_BASE}/status", timeout=3)
        return {"status": "started", **r.json()}
    except Exception:
        return {"status": "started", "detail": "Sidecar starting up — check status in a few seconds"}


@router.get("/conversations")
async def list_conversations(x_webhook_token: str | None = Header(None)):
    """List WhatsApp conversations."""
    _verify_webhook_token(x_webhook_token)
    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            """SELECT id, phone_number, created_at, last_message_at
               FROM whatsapp_conversations ORDER BY last_message_at DESC"""
        ).fetchall()
    return [dict(r) for r in rows]


@router.get("/conversations/{conversation_id}/messages")
async def get_messages(conversation_id: int, limit: int = 50, x_webhook_token: str | None = Header(None)):
    """Get messages for a conversation."""
    _verify_webhook_token(x_webhook_token)
    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            """SELECT id, role, content, created_at
               FROM whatsapp_messages WHERE conversation_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (conversation_id, min(limit, 200)),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


@router.delete("/conversations/cleanup")
async def cleanup_old_messages(days: int = 30, x_webhook_token: str | None = Header(None)):
    """Delete messages older than N days to prevent unbounded table growth."""
    _verify_webhook_token(x_webhook_token)
    days = max(1, min(days, 365))  # clamp to reasonable range
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    with get_write_db() as db:
        result = db.execute("DELETE FROM whatsapp_messages WHERE created_at < ?", (cutoff,))
        deleted = result.rowcount
        # Remove conversations with no remaining messages
        db.execute(
            """DELETE FROM whatsapp_conversations WHERE id NOT IN
               (SELECT DISTINCT conversation_id FROM whatsapp_messages)"""
        )
        db.commit()
    logger.info("WhatsApp cleanup: deleted %d messages older than %d days", deleted, days)
    return {"deleted_messages": deleted, "cutoff": cutoff}


def _check_whatsapp() -> dict:
    """Check WhatsApp connection status (used by connector registry)."""
    result = {"configured": False, "connected": False, "error": None, "detail": None}

    # WhatsApp needs an AI provider key — check whichever is configured
    from ai_client import _get_api_key, _get_provider_and_model

    provider, _ = _get_provider_and_model()
    api_key = _get_api_key(provider)
    if not api_key:
        result["detail"] = f"No API key for AI provider '{provider}' — configure in Settings"
        return result

    result["configured"] = True

    try:
        r = httpx.get(f"{BAILEYS_BASE}/status", timeout=3)
        data = r.json()
        if data.get("connected"):
            result["connected"] = True
            result["detail"] = f"Connected as {data.get('phone', 'linked device')}"
        else:
            result["error"] = "WhatsApp sidecar running but not connected — scan QR code"
    except Exception:
        result["error"] = "WhatsApp sidecar not running — click Start"

    return result
