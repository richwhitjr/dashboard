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
        "/api/calendar/search, /api/notion/search, /api/drive/search, /api/github/search, "
        "/api/obsidian/all?q=, /api/news, /api/ramp/prioritized, "
        "/api/notes, /api/issues, /api/people, /api/priorities, /api/search?q=. "
        "Microsoft Outlook emails sync into the `emails` table (same schema as Gmail); "
        "OneDrive files sync into `drive_files`. Use SQLite queries to access Microsoft data. "
        "PAGINATION: Most list endpoints return partial results by default — always paginate to get "
        "complete data. Use ?offset=N&limit=200 (max 200) and loop until has_more is false or "
        "offset+limit >= total. Paginated endpoints include: "
        "/api/obsidian/all (default 30, check total+has_more), "
        "/api/notes, /api/issues, /api/people, /api/news, /api/drive/files, "
        "/api/github/prs, /api/ramp/transactions, /api/ramp/bills. "
        "For search endpoints (gmail, slack, notion, calendar) increase max_results or count param. "
        "For SQLite queries use LIMIT/OFFSET to page through large tables. "
        "Sandbox APIs: GET/POST /api/sandbox/apps (list/create), "
        "GET/PATCH/DELETE /api/sandbox/apps/{id} (read/update/delete app), "
        "GET/PUT/DELETE /api/sandbox/apps/{id}/files/{path} (read/write/delete files). "
        "Key tables: granola_meetings (transcripts in transcript_text), calendar_events, "
        "emails, slack_messages, notion_pages, obsidian_notes, notes, people, issues. "
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


def _build_sandbox_system_prompt(manifest: dict, files: list[str]) -> str:
    """Build a system prompt for Claude when editing a sandbox app."""
    app_name = manifest.get("name", "Sandbox App")
    desc = manifest.get("description", "")

    files_str = ", ".join(files) if files else "(none yet — start with index.html)"

    return (
        f"You are building a web app called '{app_name}'" + (f" — {desc}" if desc else "") + ". "
        "This is a single-page HTML/CSS/JS app with no build step required. "
        "The entry point is index.html. You can create additional .js, .css, and .html files as needed. "
        "IMPORTANT: Only modify files in the current working directory. Do NOT modify files outside it. "
        "Do NOT touch manifest.json — the dashboard manages it. "
        "\n\nThe dashboard API is available at the same origin — use fetch('/api/...'). "
        "Key REST endpoints: "
        "/api/people, /api/notes, /api/issues, /api/meetings, /api/briefing, "
        "/api/weather, /api/priorities, /api/gmail/search?q=, /api/slack/search?q=, "
        "/api/calendar/search?q=, /api/notion/search?q=, /api/news, /api/drive/files, "
        "/api/github/prs, /api/ramp/transactions, /api/search?q=. "
        "GraphQL is available at /graphql for rich queries linking people to all data. "
        "\n\nYou can use CDN libraries via <script> tags from "
        "cdn.jsdelivr.net, cdnjs.cloudflare.com, unpkg.com, or esm.sh. "
        "Use system fonts: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif. "
        "Make the app visually polished — the user sees it in an iframe alongside this terminal. "
        f"\n\nCurrent files in the app directory: {files_str}"
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
async def claude_terminal(
    ws: WebSocket,
    persona_id: int | None = Query(None),
    sandbox_id: str | None = Query(None),
):
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

    # Resolve sandbox directory if building a sandbox app
    sandbox_dir = None
    if sandbox_id:
        from config import DATA_DIR

        sandbox_dir = (DATA_DIR / "sandbox" / sandbox_id).resolve()
        if not sandbox_dir.is_dir() or not str(sandbox_dir).startswith(str((DATA_DIR / "sandbox").resolve())):
            await ws.close(code=4004, reason="Sandbox app not found")
            return

    # Build system prompt
    if sandbox_dir:
        # Sandbox mode — focused prompt for app building
        import json as _json

        manifest = {}
        manifest_path = sandbox_dir / "manifest.json"
        if manifest_path.exists():
            try:
                manifest = _json.loads(manifest_path.read_text())
            except Exception:
                pass
        files = [f.name for f in sandbox_dir.iterdir() if f.is_file() and f.name != "manifest.json"]
        system_prompt = _build_sandbox_system_prompt(manifest, files)
    else:
        # Normal mode — full EA system prompt
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
    # Augment PATH with common user-local install locations that may not be in the
    # server process environment (e.g. ~/.local/bin, ~/.npm-global/bin, /opt/homebrew/bin)
    _extra_paths = [
        str(Path.home() / ".local" / "bin"),
        str(Path.home() / ".npm-global" / "bin"),
        "/opt/homebrew/bin",
        "/usr/local/bin",
    ]
    _search_path = os.environ.get("PATH", "") + os.pathsep + os.pathsep.join(_extra_paths)
    claude_bin = shutil.which("claude", path=_search_path) or "claude"

    # Fork a PTY running claude
    child_pid, fd = pty.fork()

    if child_pid == 0:
        # Child process — exec claude
        try:
            os.chdir(str(sandbox_dir) if sandbox_dir else REPO_DIR)
            os.environ["TERM"] = "xterm-256color"
            # Clear nested-session guard so Claude Code doesn't refuse to start
            os.environ.pop("CLAUDECODE", None)
            os.execlp(claude_bin, "claude", "--system-prompt", system_prompt)
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
