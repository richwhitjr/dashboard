"""WebSocket endpoint that spawns Claude Code in a PTY."""

import asyncio
import fcntl
import json
import logging
import os
import pty
import shutil
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
    """Build the Claude Code system prompt dynamically from profile and people DB."""
    ctx = get_prompt_context()

    # Fetch team info from the database
    team_lines = []
    try:
        with get_db_connection(readonly=True) as db:
            rows = db.execute(
                "SELECT name, title, is_executive FROM people ORDER BY is_executive DESC, name"
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

    prompt = (
        f"You are the executive assistant and strategic thought partner {ctx}. "
        "You have full access to the user's dashboard -- calendar, email, Slack, Notion, "
        "notes, team files, and Granola meeting transcripts. Be direct, structured, and "
        "actionable. Lead with answers, not preamble. "
        "IMPORTANT: NEVER use MCP servers or tools (Granola, Notion, Slack, etc.) directly. "
        "ALL data is available through the internal database and APIs. "
        "Preferred access methods, in order: "
        "1) GraphQL API at http://localhost:8000/graphql — richest queries, links people to all data. "
        "2) REST APIs at http://localhost:8000/api/... — CRUD and search endpoints. "
        "3) SQLite queries on ~/.personal-dashboard/dashboard.db — direct table access. "
        "Key REST endpoints: /api/meetings, /api/gmail/search, /api/slack/search, "
        "/api/calendar/search, /api/notion/search, /api/notes, /api/issues, "
        "/api/people, /api/priorities, /api/search?q=. "
        "Key tables: granola_meetings (transcripts in transcript_text), calendar_events, "
        "emails, slack_messages, notion_pages, notes, people, issues. "
        + (f"{team_info} " if team_info else "")
        + (
            f"Run /{user_name.lower().split()[0]}-persona for the full detailed persona and team context."
            if user_name
            else ""
        )
    )

    # Append memory summary (persistent, history-aware) or fall back to status context
    memory_injected = False
    try:
        with get_db_connection(readonly=True) as db:
            row = db.execute("SELECT summary_text, generated_at FROM memory_summary WHERE id = 1").fetchone()
        if row and row["summary_text"]:
            prompt += f"\n\n--- Memory (as of {row['generated_at']}) ---\n" + row["summary_text"]
            memory_injected = True
    except Exception:
        pass

    if not memory_injected:
        try:
            with get_db_connection(readonly=True) as db:
                row = db.execute("SELECT context_text, generated_at FROM cached_status_context WHERE id = 1").fetchone()
            if row and row["context_text"]:
                prompt += f"\n\n--- Current Status (as of {row['generated_at']}) ---\n" + row["context_text"]
        except Exception:
            pass  # Table may not exist yet or be empty

    return prompt


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


async def _demo_claude_terminal(ws: WebSocket):
    """Simulated Claude Code terminal for demo mode."""

    # ANSI helpers
    GREEN = "\x1b[1;32m"
    CYAN = "\x1b[36m"
    DIM = "\x1b[90m"
    BOLD = "\x1b[1m"
    RESET = "\x1b[0m"

    async def write(text: str):
        await ws.send_bytes(text.encode())

    async def write_slow(text: str, delay: float = 0.015):
        for char in text:
            await ws.send_bytes(char.encode())
            await asyncio.sleep(delay)

    # Show prompt directly (skip startup banner)
    await asyncio.sleep(0.3)
    await write(f"{GREEN}>{RESET} ")

    # Demo responses keyed on input keywords
    responses = {
        "auth": (
            f"\r\n\r\n{CYAN}Looking at the auth migration status...{RESET}\r\n\r\n"
            f"Based on the dashboard data, here's the current auth migration status:\r\n\r\n"
            f"  {BOLD}Auth Migration Progress{RESET}\r\n"
            f"  ├─ {GREEN}60%{RESET} of users migrated to OAuth 2.1\r\n"
            f"  ├─ {BOLD}PR #247{RESET} (auth refactor) ready for review\r\n"
            f"  ├─ Load test showed {BOLD}2x latency{RESET} at peak — needs edge caching\r\n"
            f"  └─ Target: 100% by end of Q1\r\n\r\n"
            f"  {BOLD}Recommended next steps:{RESET}\r\n"
            f"  1. Review Marcus's PR #247 — it's been open 3 days\r\n"
            f"  2. Discuss latency fix with Sarah in your 1:1\r\n"
            f"  3. Update the board deck engineering section\r\n"
        ),
        "team": (
            f"\r\n\r\n{CYAN}Pulling team data from the dashboard...{RESET}\r\n\r\n"
            f"  {BOLD}Your Direct Reports{RESET}\r\n"
            f"  ├─ Sarah Kim — Engineering Manager (API & Auth)\r\n"
            f"  ├─ Lisa Park — Engineering Manager, Platform\r\n"
            f"  ├─ Marcus Johnson — Senior Backend Engineer\r\n"
            f"  ├─ Anna Kowalski — QA Lead\r\n"
            f"  └─ James Wright — DevOps Engineer\r\n\r\n"
            f"  {BOLD}Upcoming 1:1s{RESET}\r\n"
            f"  ├─ Sarah Kim — today at 10:00 AM {DIM}(API migration concerns){RESET}\r\n"
            f"  ├─ Marcus Johnson — today at 11:00 AM\r\n"
            f"  └─ Lisa Park — tomorrow at 2:00 PM\r\n"
        ),
        "priorities": (
            f"\r\n\r\n{CYAN}Fetching today's priorities...{RESET}\r\n\r\n"
            f"  {BOLD}Top Priorities for Today{RESET}\r\n"
            f"  1. {BOLD}Prep for 1:1 with Sarah Kim{RESET} — she flagged API migration timeline concerns\r\n"
            f"  2. {BOLD}Review Marcus's auth PR #{RESET}247 — blocking the sprint (3 days open)\r\n"
            f"  3. {BOLD}Respond to Lisa's Slack DM{RESET} — needs budget approval for Datadog upgrade\r\n"
            f"  4. {BOLD}Board deck review with CEO{RESET} — meeting at 2pm, review engineering section\r\n"
            f"  5. {BOLD}Overdue CloudScale invoice{RESET} — $12.4k, 5 days past due\r\n"
        ),
        "help": (
            f"\r\n\r\n  {BOLD}Available commands{RESET}\r\n"
            f"  ├─ Ask about your {BOLD}team{RESET}, {BOLD}priorities{RESET}, {BOLD}auth migration{RESET}\r\n"
            f"  ├─ Query the {BOLD}dashboard{RESET} data (emails, slack, calendar)\r\n"
            f"  ├─ Ask for {BOLD}help{RESET} with code review, architecture, writing\r\n"
            f"  └─ Type {BOLD}/quit{RESET} to end the session\r\n"
        ),
    }

    default_response = (
        f"\r\n\r\n{CYAN}Let me look into that...{RESET}\r\n\r\n"
        f"I have access to your full dashboard — calendar, email, Slack, Notion,\r\n"
        f"meeting notes, and team data. Here's what I can help with:\r\n\r\n"
        f"  • {BOLD}Team management{RESET} — 1:1 prep, org chart, people context\r\n"
        f"  • {BOLD}Project status{RESET} — auth migration, infrastructure, hiring\r\n"
        f"  • {BOLD}Daily priorities{RESET} — what needs your attention today\r\n"
        f"  • {BOLD}Code review{RESET} — PR analysis, architecture decisions\r\n"
        f"  • {BOLD}Writing{RESET} — blog posts, docs, communications\r\n\r\n"
        f"Try asking about your {BOLD}team{RESET}, {BOLD}priorities{RESET}, or the {BOLD}auth migration{RESET}.\r\n"
    )

    input_buf = ""

    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break

            # Handle resize (ignore)
            if "text" in msg:
                try:
                    ctrl = json.loads(msg["text"])
                    if ctrl.get("type") == "resize":
                        continue
                except (json.JSONDecodeError, KeyError):
                    data = msg["text"]
                    for ch in data:
                        if ch == "\r" or ch == "\n":
                            # Process input
                            query = input_buf.strip().lower()
                            input_buf = ""

                            if query in ("/quit", "exit", "quit"):
                                await write(f"\r\n\r\n{DIM}--- session ended ---{RESET}\r\n")
                                return

                            # Find matching response
                            response = default_response
                            for keyword, resp in responses.items():
                                if keyword in query:
                                    response = resp
                                    break

                            await write("\r\n")
                            await write_slow(response, delay=0.008)
                            await write(f"\r\n{GREEN}>{RESET} ")
                        elif ch == "\x7f" or ch == "\x08":  # backspace
                            if input_buf:
                                input_buf = input_buf[:-1]
                                await write("\x08 \x08")
                        elif ch == "\x03":  # Ctrl-C
                            input_buf = ""
                            await write(f"^C\r\n{GREEN}>{RESET} ")
                        elif ord(ch) >= 32:  # printable
                            input_buf += ch
                            await write(ch)
                    continue

            if "bytes" in msg:
                data = msg["bytes"].decode("utf-8", errors="replace")
                for ch in data:
                    if ch == "\r" or ch == "\n":
                        query = input_buf.strip().lower()
                        input_buf = ""

                        if query in ("/quit", "exit", "quit"):
                            await write(f"\r\n\r\n{DIM}--- session ended ---{RESET}\r\n")
                            return

                        response = default_response
                        for keyword, resp in responses.items():
                            if keyword in query:
                                response = resp
                                break

                        await write("\r\n")
                        await write_slow(response, delay=0.008)
                        await write(f"\r\n{GREEN}>{RESET} ")
                    elif ch == "\x7f" or ch == "\x08":
                        if input_buf:
                            input_buf = input_buf[:-1]
                            await write("\x08 \x08")
                    elif ch == "\x03":
                        input_buf = ""
                        await write(f"^C\r\n{GREEN}>{RESET} ")
                    elif ord(ch) >= 32:
                        input_buf += ch
                        await write(ch)
    except WebSocketDisconnect:
        pass


@router.websocket("/ws/claude")
async def claude_terminal(ws: WebSocket, persona_id: int | None = Query(None)):
    await ws.accept()

    # Demo mode — simulated terminal
    from demo_middleware import is_demo_mode

    if is_demo_mode():
        await _demo_claude_terminal(ws)
        return

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

    # Resolve full path to claude binary before fork (child may have different PATH)
    claude_bin = shutil.which("claude") or "claude"

    # Fork a PTY running claude
    child_pid, fd = pty.fork()

    if child_pid == 0:
        # Child process — exec claude with EA system prompt
        try:
            os.chdir(REPO_DIR)
            os.environ["TERM"] = "xterm-256color"
            # Clear nested-session guard so Claude Code doesn't refuse to start
            os.environ.pop("CLAUDECODE", None)
            os.execlp(claude_bin, "claude", "--strict-mcp-config", "--system-prompt", system_prompt)
        except Exception:
            os._exit(1)  # MUST exit child — never fall through to parent code

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
        """Read from PTY, send to WebSocket — strip Claude Code startup banner."""
        banner_buf = b""
        banner_done = False
        BANNER_END = "\u2570".encode("utf-8")  # ╰ character, last line of banner box
        MAX_BANNER_SIZE = 8192  # Safety: give up filtering after 8KB

        try:
            while True:
                data = await loop.run_in_executor(None, os.read, fd, 4096)
                if not data:
                    break

                if banner_done:
                    await ws.send_bytes(data)
                    continue

                banner_buf += data

                # Safety valve: if buffer is too large, forward everything
                if len(banner_buf) > MAX_BANNER_SIZE:
                    banner_done = True
                    await ws.send_bytes(banner_buf)
                    banner_buf = b""
                    continue

                idx = banner_buf.find(BANNER_END)
                if idx >= 0:
                    # Find end of the ╰ line
                    newline_after = banner_buf.find(b"\n", idx)
                    if newline_after >= 0:
                        rest = banner_buf[newline_after + 1 :]
                        # Strip leading blank lines between banner and prompt
                        rest = rest.lstrip(b"\r\n")
                        banner_done = True
                        if rest:
                            await ws.send_bytes(rest)
                        banner_buf = b""
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
