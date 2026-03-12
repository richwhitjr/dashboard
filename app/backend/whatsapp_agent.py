"""WhatsApp chat agent — uses configurable AI provider with tool use."""

import json
import logging
import re
from datetime import datetime

import httpx

from app_config import get_prompt_context
from config import REPO_ROOT
from database import get_db_connection, get_write_db

logger = logging.getLogger(__name__)

DASHBOARD_BASE = "http://localhost:8000"
MAX_HISTORY = 50  # rolling window of messages
MAX_TOOL_ROUNDS = 10  # prevent infinite tool loops

TOOLS = [
    {
        "name": "get_briefing",
        "description": "Get today's morning briefing: weather, calendar, priorities, inbox pulse",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "search_calendar",
        "description": "Search calendar events by query string",
        "input_schema": {
            "type": "object",
            "properties": {"q": {"type": "string", "description": "Search query"}},
            "required": ["q"],
        },
    },
    {
        "name": "search_email",
        "description": "Search Gmail by query (supports Gmail search syntax like from:, subject:, etc.)",
        "input_schema": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "Gmail search query"},
                "max_results": {
                    "type": "integer",
                    "description": "Max results (default 5)",
                },
            },
            "required": ["q"],
        },
    },
    {
        "name": "search_slack",
        "description": "Search Slack messages",
        "input_schema": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "Slack search query"},
                "count": {"type": "integer", "description": "Max results (default 5)"},
            },
            "required": ["q"],
        },
    },
    {
        "name": "get_people",
        "description": "List people/coworkers. Optionally filter by is_coworker=true.",
        "input_schema": {
            "type": "object",
            "properties": {
                "is_coworker": {"type": "boolean"},
            },
            "required": [],
        },
    },
    {
        "name": "get_person",
        "description": "Get detailed info about a specific person by their ID (slug like 'alice-smith')",
        "input_schema": {
            "type": "object",
            "properties": {
                "person_id": {"type": "string", "description": "Person ID slug"},
            },
            "required": ["person_id"],
        },
    },
    {
        "name": "get_notes",
        "description": "Get notes/todos. Filter by status: 'open' or 'done'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["open", "done"],
                    "description": "Filter by status (default: open)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "create_note",
        "description": "Create a new note/todo item. Use @Name to link to a person.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Note text"},
                "priority": {
                    "type": "integer",
                    "description": "Priority (0=normal, 1=high, 2=urgent)",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "get_issues",
        "description": "Get tracked issues. Optionally filter by status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by status (open/done)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "global_search",
        "description": "Full-text search across all data sources (people, notes, meetings, emails, issues)",
        "input_schema": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "Search query"},
            },
            "required": ["q"],
        },
    },
    {
        "name": "get_weather",
        "description": "Get current weather for the user's location",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_meetings",
        "description": "Get recent and upcoming meetings with notes and transcripts",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "query_graphql",
        "description": (
            "Execute a GraphQL query against the dashboard knowledge graph. "
            "This is the PREFERRED tool for fetching structured data — it links people to emails, "
            "Slack, calendar, GitHub PRs, Drive files, Ramp transactions, notes, issues, and meetings. "
            "Use standard GraphQL syntax. Example queries:\n"
            '  { person(id: "alice-smith") { name title emails { subject date } slackMessages { text ts } } }\n'
            '  { people(isCoworker: true) { name title directReports { name } } }\n'
            '  { search(query: "quarterly review") { people { name } notes { text } emails { subject } total } }\n'
            '  { notes(status: "open") { text priority people { name } } }\n'
            '  { issues(status: "open") { title priority tags } }\n'
            '  { calendarEvents(fromDate: "2026-03-12") { summary startTime attendees } }\n'
            '  { emails(limit: 10) { subject fromName date } }\n'
            '  { slackMessages(limit: 10) { text channelName userName ts } }\n'
            '  { driveFiles(limit: 10) { name modifiedTime webViewLink } }\n'
            '  { githubPrs(state: "open") { title author state repo } }\n'
            '  { rampTransactions(limit: 10) { amount merchantName transactionDate } }\n'
            '  { news(limit: 10) { title url source snippet } }\n'
            '  { longformPosts(status: "draft") { title wordCount createdAt } }\n'
            "Mutations available: createNote, createIssue, updateIssue, sendSlackMessage, "
            "addSlackReaction, sendEmail, createCalendarEvent, deleteCalendarEvent, rsvpCalendarEvent, "
            "createNotionPage, appendNotionText, archiveNotionPage, createGoogleDoc, appendToGoogleDoc, "
            "appendSheetRows, updateSheetCells, archiveEmails."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "GraphQL query or mutation string"},
                "variables": {
                    "type": "object",
                    "description": "Optional variables for the query",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "query_database",
        "description": (
            "Execute a READ-ONLY SQL query against the dashboard SQLite database. "
            "Use this as a FALLBACK when the GraphQL API or REST tools don't cover what you need. "
            "Key tables: employees (name, title, reports_to, is_coworker, group, company), "
            "notes (text, priority, status, employee_id, due_date), "
            "issues (title, description, priority, tshirt_size, status, due_date), "
            "calendar_events (summary, start_time, end_time, attendees_json), "
            "emails (subject, snippet, from_name, from_email, date, is_unread), "
            "slack_messages (channel_name, user_name, text, ts, is_mention), "
            "notion_pages (title, url, last_edited_time), "
            "github_pull_requests (number, title, state, author, repo), "
            "granola_meetings (title, created_at, panel_summary_plain), "
            "ramp_transactions (amount, merchant_name, card_holder, date), "
            "drive_files (name, mime_type, modified_time, web_view_link), "
            "news_items (title, url, source, domain, snippet, found_at), "
            "sync_state (source, last_sync_at, last_sync_status). "
            "Only SELECT queries are allowed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "SQL SELECT query"},
            },
            "required": ["sql"],
        },
    },
]


async def _execute_tool(name: str, tool_input: dict) -> str:
    """Execute a tool by calling the dashboard REST API."""
    try:
        async with httpx.AsyncClient(base_url=DASHBOARD_BASE, timeout=30) as client:
            if name == "get_briefing":
                r = await client.get("/api/briefing")
            elif name == "search_calendar":
                r = await client.get("/api/calendar/search", params={"q": tool_input["q"]})
            elif name == "search_email":
                params = {"q": tool_input["q"]}
                if "max_results" in tool_input:
                    params["max_results"] = tool_input["max_results"]
                r = await client.get("/api/gmail/search", params=params)
            elif name == "search_slack":
                params = {"q": tool_input["q"]}
                if "count" in tool_input:
                    params["count"] = tool_input["count"]
                r = await client.get("/api/slack/search", params=params)
            elif name == "get_people":
                params = {}
                if "is_coworker" in tool_input:
                    params["is_coworker"] = tool_input["is_coworker"]
                r = await client.get("/api/people", params=params)
            elif name == "get_person":
                r = await client.get(f"/api/people/{tool_input['person_id']}")
            elif name == "get_notes":
                params = {}
                if "status" in tool_input:
                    params["status"] = tool_input["status"]
                r = await client.get("/api/notes", params=params)
            elif name == "create_note":
                body = {"text": tool_input["text"]}
                if "priority" in tool_input:
                    body["priority"] = tool_input["priority"]
                r = await client.post("/api/notes", json=body)
            elif name == "get_issues":
                params = {}
                if "status" in tool_input:
                    params["status"] = tool_input["status"]
                r = await client.get("/api/issues", params=params)
            elif name == "global_search":
                r = await client.get("/api/search", params={"q": tool_input["q"]})
            elif name == "get_weather":
                r = await client.get("/api/weather")
            elif name == "get_meetings":
                r = await client.get("/api/meetings")
            elif name == "query_graphql":
                body = {"query": tool_input["query"]}
                if "variables" in tool_input:
                    body["variables"] = tool_input["variables"]
                r = await client.post("/graphql", json=body)
            elif name == "query_database":
                sql = tool_input.get("sql", "").strip()
                # Safety: only allow SELECT queries
                if not sql.upper().startswith("SELECT"):
                    return json.dumps({"error": "Only SELECT queries are allowed"})
                try:
                    with get_db_connection(readonly=True) as db:
                        rows = db.execute(sql).fetchall()
                    results = [dict(row) for row in rows]
                    return json.dumps(results[:200], default=str)  # cap at 200 rows
                except Exception as e:
                    return json.dumps({"error": f"SQL error: {e}"})
            else:
                return json.dumps({"error": f"Unknown tool: {name}"})

            # Truncate very long responses to keep context manageable
            text = r.text
            if len(text) > 8000:
                text = text[:8000] + "\n... (truncated)"
            return text
    except Exception as e:
        logger.exception(f"Tool execution error: {name}")
        return json.dumps({"error": str(e)})


def _load_claude_md() -> str:
    """Load CLAUDE.md from the repo root for dashboard API reference."""
    try:
        claude_md_path = REPO_ROOT / "CLAUDE.md"
        if claude_md_path.exists():
            return claude_md_path.read_text()
    except Exception:
        pass
    return ""


def _build_system_prompt() -> str:
    """Build the WhatsApp agent system prompt from profile + persona + CLAUDE.md."""
    ctx = get_prompt_context()

    # Fetch team info
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
        pass

    team_info = " ".join(team_lines)

    # Load the Personal Assistant persona
    persona_prompt = ""
    try:
        with get_db_connection(readonly=True) as db:
            row = db.execute("SELECT system_prompt FROM personas WHERE name = 'Personal Assistant' LIMIT 1").fetchone()
        if row and row["system_prompt"]:
            persona_prompt = row["system_prompt"]
    except Exception:
        pass

    prompt = (
        f"You are a personal assistant chatting via WhatsApp {ctx}. "
        "You have access to tools that query the user's personal dashboard — a centralized system "
        "that aggregates calendar, email, Slack, Notion, Google Drive, GitHub, Ramp, notes, issues, "
        "people directory, meetings, news, and more."
        + (f" {team_info}" if team_info else "")
        + "\n\n"
        "CRITICAL RULES — Data Access:\n"
        "1. NEVER guess, assume, or fabricate information about the user, their team, schedule, "
        "emails, messages, or any data. ALWAYS use your tools to look it up first.\n"
        "2. PREFER the query_graphql tool — it's the most powerful way to fetch structured, "
        "linked data (e.g. a person with their emails, Slack messages, calendar events, PRs, etc. "
        "in a single query).\n"
        "3. Use the specific REST tools (search_email, search_slack, search_calendar, etc.) "
        "when you need live external service searches that go beyond synced data.\n"
        "4. Use query_database (read-only SQL) as a FALLBACK when GraphQL or REST tools don't "
        "cover your need — e.g. complex aggregations, date filtering, or tables not in the graph.\n"
        "5. If the user asks about a person, topic, event, or anything factual — LOOK IT UP. "
        "Do not rely on conversation history alone if the data might have changed.\n"
        "6. When the user asks you to DO something (send a message, create a note, schedule an event), "
        "use query_graphql mutations or the appropriate REST tool.\n"
        "\n"
        "IMPORTANT WhatsApp formatting rules:\n"
        "- Keep responses concise and mobile-friendly\n"
        "- Use plain text, not markdown headers (no # or ##)\n"
        "- Use *bold* for emphasis (WhatsApp style)\n"
        "- Use bullet points (- or •) for lists\n"
        "- Break long responses into short paragraphs\n"
        "- Lead with the answer, not preamble\n"
    )

    if persona_prompt:
        prompt += f"\n--- Persona ---\n{persona_prompt}"

    # Append CLAUDE.md as API reference
    claude_md = _load_claude_md()
    if claude_md:
        # Extract the most useful sections for the agent — API reference and DB schema
        prompt += (
            "\n\n--- Dashboard API & Schema Reference (from CLAUDE.md) ---\n"
            + claude_md
        )

    # Append cached status context
    try:
        with get_db_connection(readonly=True) as db:
            row = db.execute("SELECT context_text, generated_at FROM cached_status_context WHERE id = 1").fetchone()
        if row and row["context_text"]:
            prompt += f"\n\n--- Current Status (as of {row['generated_at']}) ---\n" + row["context_text"]
    except Exception:
        pass

    return prompt


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
    from ai_client import generate_chat

    conversation_id = _get_or_create_conversation(phone_number)

    # Load history and append user message
    history = _load_history(conversation_id)
    history.append({"role": "user", "content": user_message})
    _save_message(conversation_id, "user", user_message, wa_message_id)

    system = _build_system_prompt()

    # Agentic tool-use loop
    for _ in range(MAX_TOOL_ROUNDS):
        try:
            response = await generate_chat(
                system_prompt=system,
                messages=history,
                tools=TOOLS,
            )
        except Exception as e:
            logger.exception("AI chat error")
            return f"Sorry, I hit an error: {e}"

        if response.stop_reason == "tool_use" and response.tool_calls:
            # Agent wants to call tools — build assistant content for history
            assistant_content = []
            if response.text:
                assistant_content.append({"type": "text", "text": response.text})
            for tc in response.tool_calls:
                assistant_content.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.input})
            history.append({"role": "assistant", "content": assistant_content})

            tool_results = []
            for tc in response.tool_calls:
                logger.info(f"WhatsApp agent calling tool: {tc.name}({tc.input})")
                result = await _execute_tool(tc.name, tc.input)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": result,
                    }
                )

            history.append({"role": "user", "content": tool_results})
            continue

        # Extract final text response
        text = response.text or "I processed your request but have nothing to report."
        text = markdown_to_whatsapp(text)
        _save_message(conversation_id, "assistant", text)
        return text

    return "I used too many tools trying to answer — please try a simpler question."
