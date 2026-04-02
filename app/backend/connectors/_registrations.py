"""Register all connectors with the plugin registry.

Imported once at startup by registry.init_registry().
"""

from connectors.registry import ConnectorInfo, register

# --- Google (Gmail + Calendar) ---
register(
    ConnectorInfo(
        id="google",
        name="Google",
        description="Gmail, Calendar, Drive, Sheets",
        category="oauth",
        secret_keys=["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"],
        help_steps=[
            "Go to console.cloud.google.com and create a project (or use existing)",
            "Enable Gmail, Calendar, Drive, and Sheets APIs",
            "Go to 'Credentials' → create 'OAuth 2.0 Client ID' (Desktop app type)",
            "Copy the Client ID and Client Secret below, then click Authenticate",
            "If you see 'Google hasn't verified this app': click 'Advanced' → "
            "'Go to [app name] (unsafe)' to approve your own OAuth client",
            "If authentication fails for other users: go to 'OAuth consent screen' → "
            "publish the app (move out of Testing mode)",
        ],
        help_url="https://console.cloud.google.com/apis/credentials",
        sync_sources=["gmail", "calendar"],
        default_enabled=True,
        sync_fn=None,  # Google has separate gmail/calendar sync fns
        check_fn="routers.auth._check_google",
    )
)

# --- Google Drive (Drive + Sheets + Docs) ---
register(
    ConnectorInfo(
        id="google_drive",
        name="Google Drive",
        description="Drive files, Google Sheets, and Google Docs",
        category="oauth",
        secret_keys=[],
        help_steps=[
            "Connect Google (Gmail/Calendar) first — same OAuth token",
            "Enable this connector to sync recent Drive activity",
            "If you see 'Google hasn't verified this app': click 'Advanced' → "
            "'Go to [app name] (unsafe)' to approve your own OAuth client",
            "If authentication fails for other users: go to 'OAuth consent screen' → "
            "publish the app (move out of Testing mode)",
        ],
        sync_sources=["drive", "sheets", "docs"],
        default_enabled=False,
        sync_fn=None,  # Has separate drive/sheets/docs sync fns
        check_fn="routers.auth._check_google",
    )
)

# --- Microsoft 365 (Outlook Email + Calendar) ---
register(
    ConnectorInfo(
        id="microsoft",
        name="Microsoft 365",
        description="Outlook Email and Calendar via Microsoft Graph",
        category="oauth",
        secret_keys=["MICROSOFT_CLIENT_ID", "MICROSOFT_CLIENT_SECRET"],
        help_steps=[
            "Go to portal.azure.com → Azure Active Directory → App registrations",
            "Create a new registration (set redirect URI to "
            "http://localhost:8080, type 'Mobile and desktop applications')",
            "Under 'Certificates & secrets', create a new client secret",
            "Under 'API permissions', add Microsoft Graph: Mail.ReadWrite, Calendars.ReadWrite, User.Read",
            "Copy the Application (client) ID and Client Secret below, then click Authenticate",
        ],
        help_url="https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps",
        sync_sources=["outlook_email", "outlook_calendar"],
        default_enabled=False,
        sync_fn=None,  # Has separate email/calendar sync fns
        check_fn="routers.auth._check_microsoft",
    )
)

# --- Microsoft OneDrive (Word, Excel, PowerPoint, files) ---
register(
    ConnectorInfo(
        id="microsoft_drive",
        name="Microsoft OneDrive",
        description="OneDrive files, Word, Excel, and PowerPoint",
        category="oauth",
        secret_keys=[],
        help_steps=[
            "Connect Microsoft 365 first — same OAuth token",
            "Enable this connector to sync recent OneDrive activity",
            "Requires Files.Read permission (you may need to re-authenticate)",
        ],
        sync_sources=["onedrive"],
        default_enabled=False,
        sync_fn="connectors.onedrive.sync_onedrive_files",
        check_fn="routers.auth._check_microsoft",
    )
)

# --- Slack ---
register(
    ConnectorInfo(
        id="slack",
        name="Slack",
        description="Direct messages, mentions, and channel search",
        category="token",
        secret_keys=["SLACK_TOKEN"],
        help_steps=[
            "Go to api.slack.com/apps and create a new app (or use an existing one)",
            "Under 'OAuth & Permissions', add Bot Token Scopes: "
            "channels:read, channels:history, search:read, users:read, chat:write",
            "Install the app to your workspace",
            "Copy the 'Bot User OAuth Token' (starts with xoxb-)",
        ],
        help_url="https://api.slack.com/apps",
        sync_sources=["slack"],
        default_enabled=True,
        sync_fn="connectors.slack.sync_slack_data",
        check_fn="routers.auth._check_slack",
    )
)

# --- Notion ---
register(
    ConnectorInfo(
        id="notion",
        name="Notion",
        description="Pages, databases, and meeting notes",
        category="token",
        secret_keys=["NOTION_TOKEN"],
        help_steps=[
            "Go to notion.so/my-integrations and create a new integration",
            "Give it read access to the workspace content",
            "Copy the 'Internal Integration Secret' (starts with secret_)",
            "Share pages/databases with the integration in Notion",
        ],
        help_url="https://www.notion.so/my-integrations",
        sync_sources=["notion"],
        default_enabled=False,
        sync_fn="connectors.notion.sync_notion_pages",
        check_fn="routers.auth._check_notion",
        capabilities=["meeting_notes", "pages"],
    )
)

# --- GitHub ---
register(
    ConnectorInfo(
        id="github",
        name="GitHub",
        description="Pull requests, code search, and review requests",
        category="cli",
        secret_keys=[],
        help_steps=[
            "Install the GitHub CLI: brew install gh",
            "Authenticate: gh auth login",
            "Set your repo in Profile settings (e.g. 'myorg/myrepo')",
        ],
        help_url="https://cli.github.com/",
        sync_sources=["github"],
        default_enabled=False,
        sync_fn="connectors.github.sync_github_prs",
        check_fn="routers.auth._check_github",
    )
)

# --- Granola ---
register(
    ConnectorInfo(
        id="granola",
        name="Granola",
        description="Meeting notes and transcripts via Granola MCP",
        category="oauth",
        secret_keys=[],
        help_steps=[
            "Install Granola from granola.ai and record at least one meeting",
            "Enable this connector and click Sync — you'll be prompted to authorize",
            "OAuth tokens are stored locally in ~/.personal-dashboard/",
        ],
        help_url="https://www.granola.ai/blog/granola-mcp",
        sync_sources=["granola"],
        default_enabled=False,
        sync_fn="connectors.granola.sync_granola_meetings",
        check_fn="routers.auth._check_granola",
        capabilities=["meeting_notes"],
    )
)

# --- Ramp ---
register(
    ConnectorInfo(
        id="ramp",
        name="Ramp",
        description="Corporate card transactions, bills, and expenses",
        category="client_credentials",
        secret_keys=["RAMP_CLIENT_ID", "RAMP_CLIENT_SECRET"],
        help_steps=[
            "Go to the Ramp Developer Portal",
            "Create an OAuth 2.0 application with Client Credentials grant",
            "Request scopes: transactions:read, bills:read, accounting:read",
            "Copy the Client ID and Client Secret",
        ],
        help_url="https://docs.ramp.com/",
        sync_sources=["ramp", "ramp_vendors", "ramp_bills"],
        default_enabled=False,
        sync_fn="connectors.ramp.sync_ramp_transactions",
        check_fn="routers.auth._check_ramp",
    )
)

# --- LunchMoney ---
register(
    ConnectorInfo(
        id="lunchmoney",
        name="LunchMoney",
        description="Personal finance transactions via LunchMoney",
        category="token",
        secret_keys=["LUNCHMONEY_TOKEN"],
        help_steps=[
            "Go to my.lunchmoney.app/developers",
            "Create a new Access Token (read-only is sufficient)",
            "Copy the token",
        ],
        help_url="https://my.lunchmoney.app/developers",
        sync_sources=["lunchmoney"],
        default_enabled=False,
        sync_fn="connectors.lunchmoney.sync_lunchmoney_transactions",
        check_fn="routers.auth._check_lunchmoney",
    )
)

# --- News ---
register(
    ConnectorInfo(
        id="news",
        name="News",
        description="Industry news from Slack links, email links, and Google News RSS",
        category="none",
        secret_keys=[],
        help_steps=[
            "News aggregation works automatically — no setup needed",
            "It extracts URLs from your synced Slack and email data",
            "Customize topics in Profile settings",
        ],
        sync_sources=["news"],
        default_enabled=True,
        sync_fn="connectors.news.sync_news",
        check_fn=None,
    )
)

# --- Obsidian ---
register(
    ConnectorInfo(
        id="obsidian",
        name="Obsidian",
        description="Notes and documents from local Obsidian vault",
        category="local",
        secret_keys=[],
        help_steps=[
            "Install Obsidian from obsidian.md (or have a vault directory)",
            "Your vault will be auto-detected from Obsidian's config",
            "Or set the vault path in connector settings (connectors.obsidian.vault_path)",
        ],
        help_url="https://obsidian.md",
        sync_sources=["obsidian"],
        default_enabled=False,
        sync_fn="connectors.obsidian.sync_obsidian_notes",
        check_fn="routers.auth._check_obsidian",
    )
)

# --- AI Provider (Gemini / Anthropic / OpenAI) ---
register(
    ConnectorInfo(
        id="gemini",
        name="Gemini AI",
        description="Google Gemini API key (used when AI Provider is set to Gemini)",
        category="token",
        secret_keys=["GEMINI_API_KEY"],
        help_steps=[
            "Go to aistudio.google.com/apikey",
            "Create a new API key (or use an existing one)",
            "Copy the API key",
        ],
        help_url="https://aistudio.google.com/apikey",
        sync_sources=[],
        default_enabled=False,
        sync_fn=None,
        check_fn=None,
    )
)

register(
    ConnectorInfo(
        id="anthropic",
        name="Anthropic AI",
        description="Anthropic API key (used when AI Provider is set to Anthropic)",
        category="token",
        secret_keys=["ANTHROPIC_API_KEY"],
        help_steps=[
            "Go to console.anthropic.com/settings/keys",
            "Create a new API key",
            "Copy the API key",
        ],
        help_url="https://console.anthropic.com/settings/keys",
        sync_sources=[],
        default_enabled=False,
        sync_fn=None,
        check_fn=None,
    )
)

register(
    ConnectorInfo(
        id="openai",
        name="OpenAI",
        description="OpenAI API key (used when AI Provider is set to OpenAI)",
        category="token",
        secret_keys=["OPENAI_API_KEY"],
        help_steps=[
            "Go to platform.openai.com/api-keys",
            "Create a new API key",
            "Copy the API key",
        ],
        help_url="https://platform.openai.com/api-keys",
        sync_sources=[],
        default_enabled=False,
        sync_fn=None,
        check_fn=None,
    )
)

# --- Claude Code ---
register(
    ConnectorInfo(
        id="claude_code",
        name="Claude Code",
        description="Embedded Claude Code terminal for AI-assisted coding",
        category="cli",
        secret_keys=[],
        help_steps=[
            "Install Claude Code: npm install -g @anthropic-ai/claude-code",
            "Or via Homebrew: brew install claude-code",
            "Run 'claude' once in your terminal to complete setup",
            "Enable this connector to show the Claude terminal in the sidebar",
        ],
        help_url="https://docs.anthropic.com/en/docs/claude-code/overview",
        sync_sources=[],
        default_enabled=False,
        sync_fn=None,
        check_fn="routers.auth._check_claude_code",
    )
)

# --- WhatsApp ---
register(
    ConnectorInfo(
        id="whatsapp",
        name="WhatsApp",
        description="Chat with your personal assistant via WhatsApp",
        category="token",
        secret_keys=[],
        help_steps=[
            "Configure an AI Provider above (Gemini, Anthropic, or OpenAI)",
            "Set your WhatsApp phone number in Profile settings (e.g. 15551234567)",
            "Click Start to launch the WhatsApp sidecar",
            "Scan the QR code to pair your phone",
            "Send a message from WhatsApp to test",
        ],
        sync_sources=[],
        default_enabled=False,
        sync_fn=None,
        check_fn="routers.whatsapp._check_whatsapp",
    )
)
