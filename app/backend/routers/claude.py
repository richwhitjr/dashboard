"""WebSocket endpoint that spawns Claude Code in a PTY."""

import asyncio
import fcntl
import json
import logging
import os
import pty
import signal
import struct
import termios
from pathlib import Path

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app_config import get_profile, get_prompt_context
from database import get_db_connection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["claude"])

REPO_DIR = str(Path(__file__).resolve().parent.parent.parent.parent)


def _build_system_prompt() -> str:
    """Build the Claude Code system prompt dynamically from profile and employee DB."""
    ctx = get_prompt_context()

    # Fetch team info from the database
    team_lines = []
    try:
        with get_db_connection(readonly=True) as db:
            rows = db.execute(
                "SELECT name, title, is_executive FROM employees ORDER BY is_executive DESC, name"
            ).fetchall()

        direct_reports = []
        executives = []
        for r in rows:
            label = f"{r['name']} ({r['title']})" if r["title"] else r["name"]
            if r["is_executive"]:
                executives.append(label)
            else:
                direct_reports.append(label)

        if direct_reports:
            team_lines.append(f"Direct reports: {', '.join(direct_reports)}.")
        if executives:
            team_lines.append(f"Exec peers: {', '.join(executives)}.")
    except Exception:
        pass  # Gracefully degrade if DB is unavailable

    team_info = " ".join(team_lines)

    profile = get_profile()
    user_name = profile.get("user_name", "").strip()

    return (
        f"You are the executive assistant and strategic thought partner {ctx}. "
        "You have full access to the user's dashboard -- calendar, email, Slack, Notion, "
        "notes, team files, and Granola meeting transcripts. Be direct, structured, and "
        "actionable. Lead with answers, not preamble. Use the dashboard APIs and SQLite "
        "database proactively to pull context. "
        + (f"{team_info} " if team_info else "")
        + (
            f"Run /{user_name.lower().split()[0]}-persona for the full detailed persona and team context."
            if user_name
            else ""
        )
    )


MAX_CONCURRENT = 5
_active_sessions: set[int] = set()  # PIDs of active child processes
_sessions_lock = asyncio.Lock()


async def _kill_and_wait(pid: int, timeout: float = 3.0):
    """Kill a child process with SIGTERM, escalating to SIGKILL if needed."""
    loop = asyncio.get_event_loop()
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return

    deadline = loop.time() + timeout
    while loop.time() < deadline:
        try:
            result = await loop.run_in_executor(None, lambda: os.waitpid(pid, os.WNOHANG))
            if result[0] != 0:
                return  # process exited
        except ChildProcessError:
            return
        await asyncio.sleep(0.1)

    # Escalate to SIGKILL
    logger.warning(f"Claude process {pid} did not exit after SIGTERM, sending SIGKILL")
    try:
        os.kill(pid, signal.SIGKILL)
        await loop.run_in_executor(None, lambda: os.waitpid(pid, 0))
    except (OSError, ChildProcessError):
        pass


@router.websocket("/ws/claude")
async def claude_terminal(ws: WebSocket, persona_id: int | None = Query(None)):
    await ws.accept()

    # Check concurrent session limit
    async with _sessions_lock:
        if len(_active_sessions) >= MAX_CONCURRENT:
            await ws.close(code=4429, reason="Too many concurrent sessions")
            return

    # Build system prompt, optionally augmented with persona
    system_prompt = _build_system_prompt()
    if persona_id:
        try:
            with get_db_connection(readonly=True) as db:
                row = db.execute("SELECT system_prompt FROM personas WHERE id = ?", (persona_id,)).fetchone()
            if row and row["system_prompt"]:
                system_prompt += "\n\n--- Persona ---\n" + row["system_prompt"]
        except Exception:
            pass  # Gracefully degrade if DB lookup fails

    # Fork a PTY running claude
    child_pid, fd = pty.fork()

    if child_pid == 0:
        # Child process — exec claude with EA system prompt
        os.chdir(REPO_DIR)
        os.environ["TERM"] = "xterm-256color"
        # Clear nested-session guard so Claude Code doesn't refuse to start
        os.environ.pop("CLAUDECODE", None)
        os.execlp("claude", "claude", "--system-prompt", system_prompt)
        # execlp never returns

    # Parent process — register and relay between WebSocket and PTY
    async with _sessions_lock:
        _active_sessions.add(child_pid)

    loop = asyncio.get_event_loop()

    # Set initial terminal size
    def set_size(rows: int, cols: int):
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)
        os.kill(child_pid, signal.SIGWINCH)

    set_size(24, 80)

    async def pty_to_ws():
        """Read from PTY, send to WebSocket."""
        try:
            while True:
                data = await loop.run_in_executor(None, os.read, fd, 4096)
                if not data:
                    break
                await ws.send_bytes(data)
        except (OSError, WebSocketDisconnect):
            pass

    reader_task = asyncio.create_task(pty_to_ws())

    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break

            if "text" in msg:
                # JSON control messages (e.g. resize)
                try:
                    ctrl = json.loads(msg["text"])
                    if ctrl.get("type") == "resize":
                        set_size(ctrl["rows"], ctrl["cols"])
                        continue
                except (json.JSONDecodeError, KeyError):
                    # Plain text input
                    os.write(fd, msg["text"].encode())
                    continue

            if "bytes" in msg:
                os.write(fd, msg["bytes"])
    except WebSocketDisconnect:
        pass
    finally:
        reader_task.cancel()
        try:
            os.close(fd)
        except OSError:
            pass
        await _kill_and_wait(child_pid)
        async with _sessions_lock:
            _active_sessions.discard(child_pid)
