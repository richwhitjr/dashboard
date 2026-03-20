"""Core agent logic — shared by WhatsApp and web chat interfaces.

Provides the tool definitions, tool execution, system prompt building,
and agentic chat loop that can be used by any channel.
"""

import json
import logging
import re
from datetime import date

import httpx

from app_config import get_prompt_context
from config import REPO_ROOT
from database import get_db_connection

logger = logging.getLogger(__name__)

DASHBOARD_BASE = "http://localhost:8000"
MAX_TOOL_ROUNDS = 15  # prevent infinite tool loops

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
        "name": "search_notion",
        "description": "Search Notion pages and databases by query string",
        "input_schema": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "Search query"},
                "page_size": {"type": "integer", "description": "Max results (default 10)"},
            },
            "required": ["q"],
        },
    },
    {
        "name": "search_drive",
        "description": "Search Google Drive files by full-text query",
        "input_schema": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "Search query"},
                "max_results": {"type": "integer", "description": "Max results (default 20)"},
            },
            "required": ["q"],
        },
    },
    {
        "name": "search_github",
        "description": "Search GitHub pull requests and issues",
        "input_schema": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "Search query"},
                "type": {
                    "type": "string",
                    "enum": ["pr", "issue", "all"],
                    "description": "Filter by type (default: pr)",
                },
                "state": {
                    "type": "string",
                    "enum": ["open", "closed"],
                    "description": "Filter by state (optional)",
                },
            },
            "required": ["q"],
        },
    },
    {
        "name": "search_obsidian",
        "description": "Search Obsidian vault notes by title, content, or tags",
        "input_schema": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "description": "Max results (default 20)"},
            },
            "required": ["q"],
        },
    },
    {
        "name": "get_news",
        "description": "Get recent news items aggregated from Slack links, email links, and Google News RSS",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max results (default 20)"},
            },
            "required": [],
        },
    },
    {
        "name": "get_ramp_transactions",
        "description": (
            "Get recent Ramp expense transactions, ranked by relevance. "
            "Use for expense queries, spend analysis, and vendor lookups."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "Look-back window in days (default 7)"},
            },
            "required": [],
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
            "Execute a READ-ONLY GraphQL query against the dashboard knowledge graph. "
            "This is the PREFERRED tool for fetching structured data — it links people to emails, "
            "Slack, calendar, GitHub PRs, Drive files, Ramp transactions, notes, issues, and meetings. "
            "Use standard GraphQL syntax. Only queries are allowed (no mutations). Example queries:\n"
            '  { person(id: "alice-smith") { name title emails { subject date } slackMessages { text ts } } }\n'
            "  { people(isCoworker: true) { name title directReports { name } } }\n"
            '  { search(query: "quarterly review") { people { name } notes { text } emails { subject } total } }\n'
            '  { notes(status: "open") { text priority people { name } } }\n'
            '  { issues(status: "open") { title priority tags } }\n'
            '  { calendarEvents(fromDate: "2026-03-12") { summary startTime attendees } }\n'
            "  { emails(limit: 10) { subject fromName date } }\n"
            "  { slackMessages(limit: 10) { text channelName userName ts } }\n"
            "  { driveFiles(limit: 10) { name modifiedTime webViewLink } }\n"
            '  { githubPrs(state: "open") { title author state repo } }\n'
            "  { rampTransactions(limit: 10) { amount merchantName transactionDate } }\n"
            "  { news(limit: 10) { title url source snippet } }\n"
            '  { longformPosts(status: "draft") { title wordCount createdAt } }\n'
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "GraphQL query string (read-only, no mutations)"},
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
            "obsidian_notes (title, folder, content_preview, tags, wiki_links, word_count, modified_time), "
            "news_items (title, url, source, domain, snippet, found_at), "
            "sync_state (source, last_sync_at, last_sync_status). "
            "Outlook emails sync into the `emails` table alongside Gmail (same schema). "
            "OneDrive files sync into `drive_files`. Use these tables for Microsoft-specific queries. "
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
    # --- Write tools ---
    {
        "name": "create_note",
        "description": (
            "Create a note, thought, agenda item, or follow-up. "
            "Start text with [t] for a thought, [1] for a 1:1 agenda item. "
            "Use @Name in text to link to a person. "
            "To add a follow-up for someone, include their person_id."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": (
                        "Note text. Prefix [t] for thought, [1] for 1:1 agenda item. Use @Name to mention people."
                    ),
                },
                "person_id": {
                    "type": "string",
                    "description": "Person ID to link this note to (for follow-ups, agenda items)",
                },
                "priority": {
                    "type": "integer",
                    "description": "Priority 0 (highest) to 3 (lowest), default 0",
                    "minimum": 0,
                    "maximum": 3,
                },
                "is_one_on_one": {
                    "type": "boolean",
                    "description": "Mark as 1:1 agenda item (alternative to [1] prefix)",
                },
                "due_date": {
                    "type": "string",
                    "description": "Due date in YYYY-MM-DD format",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "update_note",
        "description": (
            "Update or close a note/thought/agenda item. "
            "Set status to 'done' to close it. "
            "Use get_notes first to find the note ID."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "note_id": {"type": "integer", "description": "ID of the note to update"},
                "status": {
                    "type": "string",
                    "enum": ["open", "done"],
                    "description": "Set to 'done' to close",
                },
                "text": {"type": "string", "description": "Updated note text"},
                "priority": {
                    "type": "integer",
                    "description": "Updated priority 0-3",
                    "minimum": 0,
                    "maximum": 3,
                },
            },
            "required": ["note_id"],
        },
    },
    {
        "name": "create_issue",
        "description": (
            "Create a tracked issue/task. Use @Name in the title to link people. "
            "Issues have priority (0=critical to 3=low) and t-shirt size (s/m/l/xl)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Issue title. Use @Name to mention people.",
                },
                "description": {"type": "string", "description": "Detailed description"},
                "priority": {
                    "type": "integer",
                    "description": "0=critical, 1=high, 2=medium (default), 3=low",
                    "minimum": 0,
                    "maximum": 3,
                },
                "size": {
                    "type": "string",
                    "enum": ["s", "m", "l", "xl"],
                    "description": "T-shirt size estimate (default: m)",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags for categorization",
                },
                "due_date": {"type": "string", "description": "Due date in YYYY-MM-DD format"},
                "person_id": {"type": "string", "description": "Person ID to assign"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "update_issue",
        "description": (
            "Update or close an issue. Set status to 'done' to close it. Use get_issues first to find the issue ID."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_id": {"type": "integer", "description": "ID of the issue to update"},
                "status": {
                    "type": "string",
                    "enum": ["open", "in_progress", "done"],
                    "description": "Issue status",
                },
                "title": {"type": "string", "description": "Updated title"},
                "description": {"type": "string", "description": "Updated description"},
                "priority": {
                    "type": "integer",
                    "description": "Updated priority 0-3",
                    "minimum": 0,
                    "maximum": 3,
                },
                "size": {
                    "type": "string",
                    "enum": ["s", "m", "l", "xl"],
                    "description": "Updated size",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Replace tags",
                },
            },
            "required": ["issue_id"],
        },
    },
    {
        "name": "create_longform",
        "description": (
            "Create a longform writing piece (draft blog post, memo, document). "
            "Returns the post ID for later editing in the dashboard."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Post title"},
                "body": {"type": "string", "description": "Post body in markdown"},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags for categorization",
                },
                "person_id": {"type": "string", "description": "Person ID to link this post to"},
            },
            "required": ["title", "body"],
        },
    },
    {
        "name": "add_one_on_one_note",
        "description": (
            "Add a 1:1 meeting note for a specific person. "
            "This creates a structured meeting note with a date. "
            "Use get_people or get_person to find the person_id first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "person_id": {
                    "type": "string",
                    "description": "Person ID (slug like 'alice-smith')",
                },
                "content": {"type": "string", "description": "Meeting notes content"},
                "meeting_date": {
                    "type": "string",
                    "description": "Meeting date YYYY-MM-DD (defaults to today)",
                },
                "title": {"type": "string", "description": "Optional title for the meeting notes"},
            },
            "required": ["person_id", "content"],
        },
    },
    # --- Sandbox tools ---
    {
        "name": "list_sandbox_apps",
        "description": "List all sandbox apps. Returns id, name, description, files list, and timestamps for each app.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "create_sandbox_app",
        "description": (
            "Create a new sandbox app. Returns the new app with its id, which you'll need for file operations. "
            "The app starts with a template index.html."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "App name (will be slugified for the ID)"},
                "description": {"type": "string", "description": "Brief description of the app"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "read_sandbox_file",
        "description": (
            "Read the text content of a file in a sandbox app. "
            "Use list_sandbox_apps first to find the app_id and file names."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "app_id": {"type": "string", "description": "Sandbox app ID (slug)"},
                "file_path": {
                    "type": "string",
                    "description": "File path relative to app root (e.g. 'index.html', 'js/app.js')",
                },
            },
            "required": ["app_id", "file_path"],
        },
    },
    {
        "name": "write_sandbox_file",
        "description": (
            "Write or overwrite a file in a sandbox app. Creates parent directories as needed. "
            "Use this to build HTML/CSS/JS apps. Cannot write to manifest.json."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "app_id": {"type": "string", "description": "Sandbox app ID (slug)"},
                "file_path": {
                    "type": "string",
                    "description": "File path relative to app root (e.g. 'index.html', 'style.css')",
                },
                "content": {"type": "string", "description": "Full file content to write"},
            },
            "required": ["app_id", "file_path", "content"],
        },
    },
    {
        "name": "delete_sandbox_app",
        "description": "Delete a sandbox app and all its files. This cannot be undone.",
        "input_schema": {
            "type": "object",
            "properties": {
                "app_id": {"type": "string", "description": "Sandbox app ID (slug) to delete"},
            },
            "required": ["app_id"],
        },
    },
    # --- Shell & web tools ---
    {
        "name": "bash",
        "description": (
            "Run a read-only bash command and return its output. "
            "Use for: current time/date (`date`), file reads (`cat`, `ls`), "
            "gh CLI queries (`gh pr list`, `gh issue list`), "
            "system info (`df -h`, `ps aux`, `env`), grep/find, and similar. "
            "Scripting interpreters (python, node, ruby, perl, etc.), sub-shells (bash, zsh), "
            "and write operations (rm, mv, cp, sudo, git commit/push, redirections, etc.) are blocked."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The bash command to run (read-only)"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default 30, max 120)"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "web_fetch",
        "description": (
            "Fetch a URL and return its readable text content. "
            "Use to read articles, documentation, GitHub pages, or any URL the user provides."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to fetch"},
                "max_chars": {"type": "integer", "description": "Max characters to return (default 8000)"},
            },
            "required": ["url"],
        },
    },
]


async def execute_tool(name: str, tool_input: dict) -> str:
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
            elif name == "search_notion":
                params = {"q": tool_input["q"]}
                if "page_size" in tool_input:
                    params["page_size"] = tool_input["page_size"]
                r = await client.get("/api/notion/search", params=params)
            elif name == "search_drive":
                params = {"q": tool_input["q"]}
                if "max_results" in tool_input:
                    params["max_results"] = tool_input["max_results"]
                r = await client.get("/api/drive/search", params=params)
            elif name == "search_github":
                params = {"q": tool_input["q"]}
                if "type" in tool_input:
                    params["type"] = tool_input["type"]
                if "state" in tool_input:
                    params["state"] = tool_input["state"]
                r = await client.get("/api/github/search", params=params)
            elif name == "search_obsidian":
                params = {"q": tool_input["q"]}
                if "limit" in tool_input:
                    params["limit"] = tool_input["limit"]
                r = await client.get("/api/obsidian/all", params=params)
            elif name == "get_news":
                params = {"limit": tool_input.get("limit", 20)}
                r = await client.get("/api/news", params=params)
            elif name == "get_ramp_transactions":
                params = {"days": tool_input.get("days", 7)}
                r = await client.get("/api/ramp/prioritized", params=params)
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
                gql_query = tool_input.get("query", "").strip()
                # Strip # line comments before checking — prevents bypass via "# comment\nmutation {…}"
                gql_stripped = re.sub(r"#[^\n]*", "", gql_query).strip()
                if gql_stripped.lower().startswith("mutation"):
                    return json.dumps({"error": "Mutations are not allowed. Read-only queries only."})
                body = {"query": gql_query}
                if "variables" in tool_input:
                    body["variables"] = tool_input["variables"]
                r = await client.post("/graphql", json=body)
            elif name == "bash":
                import subprocess

                cmd = tool_input["command"]
                timeout = min(tool_input.get("timeout", 30), 120)
                # Block output redirection and common write/destructive commands
                if re.search(r"(?:^|[\s;|&])>+\s*\S", cmd):
                    return '{"error": "Output redirection (> and >>) is not allowed"}'
                _bash_blocked = re.compile(
                    r"\b(rm|rmdir|mv|cp|mkdir|touch|chmod|chown|chflags"
                    r"|truncate|shred|dd|mkfs|fdisk|diskutil"
                    r"|sudo|su|kill|killall|pkill"
                    r"|reboot|shutdown|halt|poweroff|wget|tee"
                    # Scripting interpreters bypass all shell-level restrictions via stdlib
                    r"|python|python3|pypy|pypy3"
                    r"|node|nodejs|ruby|perl|php|lua|julia|Rscript"
                    # Sub-shell spawning
                    r"|bash|zsh|fish|ksh|csh|tcsh|dash)\b"
                    r"|pip\s+(install|uninstall)"
                    r"|npm\s+(install|uninstall|i\b|ci\b)"
                    r"|yarn\s+(add|remove|install)"
                    r"|brew\s+(install|uninstall)"
                    r"|git\s+(commit|push|add|merge|rebase|clean)\b"
                    r"|git\s+reset\b"
                    r"|git\s+branch\s+-[dD]"
                    r"|git\s+stash\s+(pop|drop|clear)",
                    re.IGNORECASE,
                )
                if _bash_blocked.search(cmd):
                    return (
                        '{"error": "Command contains a disallowed operation. Only read-only commands are permitted."}'
                    )
                if re.search(
                    r"\bcurl\b.+(-X\s*(POST|PUT|DELETE|PATCH)|--data\b|-d\s|--upload-file\b|-T\s|-F\s)",
                    cmd,
                    re.IGNORECASE | re.DOTALL,
                ):
                    return '{"error": "curl with mutating HTTP methods is not allowed"}'
                try:
                    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
                    out = result.stdout
                    if result.stderr.strip():
                        out += f"\nSTDERR: {result.stderr.strip()}"
                    out = out.strip() or "(no output)"
                    if len(out) > 8000:
                        out = out[:8000] + "\n... (truncated)"
                    return out
                except subprocess.TimeoutExpired:
                    return f'{{"error": "Command timed out after {timeout}s"}}'
            elif name == "web_fetch":
                url = tool_input["url"]
                max_chars = tool_input.get("max_chars", 8000)
                try:
                    resp = await httpx.AsyncClient(timeout=15, follow_redirects=True).get(
                        url, headers={"User-Agent": "Mozilla/5.0"}
                    )
                    resp.raise_for_status()
                    ct = resp.headers.get("content-type", "")
                    if "html" in ct:
                        try:
                            from trafilatura import extract

                            text = extract(resp.text) or resp.text
                        except ImportError:
                            text = resp.text
                    else:
                        text = resp.text
                    text = text.strip()
                    if len(text) > max_chars:
                        text = text[:max_chars] + "\n... (truncated)"
                    return text or "(empty response)"
                except Exception as exc:
                    return json.dumps({"error": f"fetch failed: {exc}"})
            elif name == "query_database":
                sql = tool_input.get("sql", "").strip()
                sql_upper = sql.upper()
                if not sql_upper.startswith("SELECT"):
                    return json.dumps({"error": "Only SELECT queries are allowed"})
                if ";" in sql:
                    return json.dumps({"error": "Multiple statements are not allowed"})
                _blocked = {
                    "INSERT",
                    "UPDATE",
                    "DELETE",
                    "DROP",
                    "ALTER",
                    "CREATE",
                    "ATTACH",
                    "DETACH",
                    "PRAGMA",
                    "REPLACE",
                    "GRANT",
                    "EXEC",
                }
                sql_words = set(re.findall(r"[A-Z]+", sql_upper))
                blocked_found = sql_words & _blocked
                if blocked_found:
                    return json.dumps({"error": f"Disallowed keywords: {', '.join(blocked_found)}"})
                try:
                    with get_db_connection(readonly=True) as db:
                        rows = db.execute(sql).fetchall()
                    results = [dict(row) for row in rows]
                    return json.dumps(results[:200], default=str)
                except Exception:
                    return json.dumps({"error": "SQL query failed — check syntax"})
            # --- Write tools ---
            elif name == "create_note":
                body = {"text": tool_input["text"]}
                if "person_id" in tool_input:
                    body["person_ids"] = [tool_input["person_id"]]
                if "priority" in tool_input:
                    body["priority"] = tool_input["priority"]
                if "is_one_on_one" in tool_input:
                    body["is_one_on_one"] = tool_input["is_one_on_one"]
                if "due_date" in tool_input:
                    body["due_date"] = tool_input["due_date"]
                r = await client.post("/api/notes", json=body)
            elif name == "update_note":
                note_id = tool_input["note_id"]
                body = {}
                for key in ("status", "text", "priority"):
                    if key in tool_input:
                        body[key] = tool_input[key]
                r = await client.patch(f"/api/notes/{note_id}", json=body)
            elif name == "create_issue":
                body = {"title": tool_input["title"]}
                if "description" in tool_input:
                    body["description"] = tool_input["description"]
                if "priority" in tool_input:
                    body["priority"] = tool_input["priority"]
                if "size" in tool_input:
                    body["tshirt_size"] = tool_input["size"]
                if "tags" in tool_input:
                    body["tags"] = tool_input["tags"]
                if "due_date" in tool_input:
                    body["due_date"] = tool_input["due_date"]
                if "person_id" in tool_input:
                    body["person_ids"] = [tool_input["person_id"]]
                r = await client.post("/api/issues", json=body)
            elif name == "update_issue":
                issue_id = tool_input["issue_id"]
                body = {}
                for key in ("status", "title", "description", "priority", "tags"):
                    if key in tool_input:
                        body[key] = tool_input[key]
                if "size" in tool_input:
                    body["tshirt_size"] = tool_input["size"]
                r = await client.patch(f"/api/issues/{issue_id}", json=body)
            elif name == "create_longform":
                body = {
                    "title": tool_input["title"],
                    "body": tool_input["body"],
                    "status": "draft",
                }
                if "tags" in tool_input:
                    body["tags"] = tool_input["tags"]
                if "person_id" in tool_input:
                    body["person_ids"] = [tool_input["person_id"]]
                r = await client.post("/api/longform", json=body)
            elif name == "add_one_on_one_note":
                person_id = tool_input["person_id"]
                body = {
                    "meeting_date": tool_input.get("meeting_date", date.today().isoformat()),
                    "content": tool_input["content"],
                }
                if "title" in tool_input:
                    body["title"] = tool_input["title"]
                r = await client.post(f"/api/people/{person_id}/one-on-one-notes", json=body)
            # --- Sandbox tools ---
            elif name == "list_sandbox_apps":
                r = await client.get("/api/sandbox/apps")
            elif name == "create_sandbox_app":
                body = {"name": tool_input["name"]}
                if "description" in tool_input:
                    body["description"] = tool_input["description"]
                r = await client.post("/api/sandbox/apps", json=body)
            elif name == "read_sandbox_file":
                r = await client.get(f"/api/sandbox/apps/{tool_input['app_id']}/files/{tool_input['file_path']}")
                # serve_file returns raw content (not JSON), handle directly
                text = r.text
                if len(text) > 8000:
                    text = text[:8000] + "\n... (truncated)"
                return text
            elif name == "write_sandbox_file":
                r = await client.put(
                    f"/api/sandbox/apps/{tool_input['app_id']}/files/{tool_input['file_path']}",
                    json={"content": tool_input["content"]},
                )
            elif name == "delete_sandbox_app":
                r = await client.delete(f"/api/sandbox/apps/{tool_input['app_id']}")
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


def load_claude_md() -> str:
    """Load a minimal subset of CLAUDE.md — only the DB table list for SQL queries."""
    try:
        claude_md_path = REPO_ROOT / "CLAUDE.md"
        if not claude_md_path.exists():
            return ""
        content = claude_md_path.read_text()
        match = re.search(
            r"(## Database Tables\n.*?)(?=\n## |\Z)",
            content,
            re.DOTALL,
        )
        if match:
            return match.group(1).strip()
    except Exception:
        pass
    return ""


def build_system_prompt(channel_instructions: str = "") -> str:
    """Build the agent system prompt from profile + persona + CLAUDE.md.

    Args:
        channel_instructions: Channel-specific formatting rules appended to the prompt.
                              E.g. WhatsApp formatting rules, or empty for web chat.
    """
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
        f"You are a personal assistant {ctx}. "
        "You have access to tools that query and update the user's personal dashboard — a centralized system "
        "that aggregates calendar, email, Slack, Notion, Google Drive, GitHub, Ramp, notes, issues, "
        "people directory, meetings, news, and more." + (f" {team_info}" if team_info else "") + "\n\n"
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
        "6. You can CREATE and UPDATE local dashboard data: notes, thoughts, 1:1 agenda items, "
        "issues, longform drafts, 1:1 meeting notes, and sandbox apps. You can also read and write "
        "files in sandbox apps to build mini web apps. You CANNOT send emails, Slack messages, "
        "or create calendar events — those require the user to act directly in the dashboard.\n"
        "6b. Use the bash tool for: current time (`date`), file reads, `gh` CLI queries, "
        "and other read-only shell operations. "
        "Only read-only commands are permitted — writes, deletes, installs, mutations, "
        "and scripting interpreters (python, node, ruby, etc.) are blocked. "
        "Use web_fetch to read any URL the user provides (articles, docs, GitHub pages, etc.).\n"
        "7. When creating items, confirm what you created with key details (ID, title, linked person).\n"
        "8. When closing items, use get_notes or get_issues first to find the correct ID, then update.\n"
        "9. NEVER include raw API keys, tokens, passwords, or secrets in your responses.\n"
        "10. For WRITE operations (create_issue, create_note, create_longform, update_note, update_issue): "
        "ACT DIRECTLY. Do NOT over-research by looking up people, searching emails, or gathering context "
        "before creating/updating. The user said what they want — just do it. Use @Name in titles to link "
        "people automatically. Only look things up first if the user's request is ambiguous or you need "
        "an ID to update an existing item.\n"
        "11. NEVER claim you created, updated, or deleted something without actually calling the "
        "corresponding tool (create_issue, create_note, update_note, update_issue, etc.). "
        "If you did not make a tool call, you did NOT perform the action — do not fabricate results. "
        "You MUST use tools for all write operations.\n"
    )

    if channel_instructions:
        prompt += "\n" + channel_instructions

    if persona_prompt:
        prompt += f"\n--- Persona ---\n{persona_prompt}"

    # Append minimal DB schema reference for SQL queries
    claude_md = load_claude_md()
    if claude_md:
        prompt += "\n\n--- Database Table Reference ---\n" + claude_md

    # Append cached status context
    try:
        with get_db_connection(readonly=True) as db:
            row = db.execute("SELECT context_text, generated_at FROM cached_status_context WHERE id = 1").fetchone()
        if row and row["context_text"]:
            prompt += f"\n\n--- Current Status (as of {row['generated_at']}) ---\n" + row["context_text"]
    except Exception:
        pass

    return prompt


async def run_agent_loop(
    messages: list[dict],
    system_prompt: str,
    on_event=None,
) -> str:
    """Run the agentic tool-use loop and return the final text response.

    Args:
        messages: Conversation history in Anthropic API format.
        system_prompt: The system prompt to use.
        on_event: Optional async callback for streaming events.
                  Called with (event_type, data) where event_type is one of:
                  'text', 'tool_call', 'tool_result'.
    """
    from ai_client import generate_chat

    for _ in range(MAX_TOOL_ROUNDS):
        try:
            response = await generate_chat(
                system_prompt=system_prompt,
                messages=messages,
                tools=TOOLS,
            )
        except Exception:
            logger.exception("AI chat error")
            return "Sorry, I hit an error processing your request. Please try again."

        if response.stop_reason == "tool_use" and response.tool_calls:
            # For Gemini: use raw parts to preserve thought_signature
            if response._gemini_parts is not None:
                messages.append({"role": "model", "parts": response._gemini_parts, "_gemini": True})
            else:
                # Anthropic/OpenAI: build assistant content in Anthropic format
                assistant_content = []
                if response.text:
                    assistant_content.append({"type": "text", "text": response.text})
                for tc in response.tool_calls:
                    assistant_content.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.input})
                messages.append({"role": "assistant", "content": assistant_content})

            tool_results = []
            for tc in response.tool_calls:
                logger.info(f"Agent calling tool: {tc.name}({tc.input})")
                if on_event:
                    await on_event("tool_call", {"name": tc.name, "input": tc.input})

                result = await execute_tool(tc.name, tc.input)

                if on_event:
                    await on_event("tool_result", {"name": tc.name, "result": result})

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": result,
                    }
                )

            messages.append({"role": "user", "content": tool_results})
            continue

        # Final text response
        text = response.text or "I processed your request but have nothing to report."
        if on_event:
            await on_event("text", {"text": text})
        return text

    return "I used too many tools trying to answer — please try a simpler question."
