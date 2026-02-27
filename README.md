# Personal Dashboard

A local-first personal dashboard that centralizes your email, calendar, Slack, Notion, GitHub, meetings, and more into a single quiet interface. Runs as a native macOS app or in the browser.

## Features

- **Morning Briefing**: AI-generated priorities, weather, inbox pulse (email, Slack, GitHub, tasks, bills), calendar timeline, overnight digest — all on the default home page
- **People & Contacts**: Unified directory for coworkers and external contacts with group filtering, org chart, 1:1 topic tracking, per-person context pages, social links, custom attributes, and relationship connections
- **Notes & Issues**: Quick-capture notes with `@mention` autocomplete, plus local issue tracking with priorities, t-shirt sizing, tags, due dates, and person/meeting linking
- **Issue Discovery**: Press `D` to have AI scan your email, Slack, meetings, Notion, and calendar, then propose new issues to accept, reject, or edit
- **Longform Writing**: Markdown editor for blog posts and drafts with split/preview modes, tagging, comments, word count, and "open in Claude" integration
- **Unified Inbox**: Gmail, Slack, Notion, GitHub, and Google Drive activity in one view
- **Google Drive**: Browse recent files with Gemini AI relevance ranking and score filtering
- **News Feed**: Aggregated from your Slack channels, email, and Google News RSS
- **Meetings**: Calendar integration with cancelled/declined event filtering, plus Granola transcript sync
- **Ramp Finance**: Expense tracking with AI-prioritized transactions, bills, vendors, and project budgets with incremental sync
- **Embedded Claude Code**: Full Claude Code CLI terminal with persona and session management
- **Global Search**: `Cmd+K` command palette to search across all data sources, with quick-create (Tab to create notes, thoughts, or issues)
- **Plugin Connectors**: Enable/disable services as needed — Google, Slack, Notion, GitHub, Ramp, Granola, Drive, and more
- **Keyboard-Driven**: Vim-style navigation, chord shortcuts, undo (`u`), and a full shortcut help overlay

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+ with npm
- macOS (for native app; browser mode works on any OS)

### Install & Run

```bash
# Clone and start
git clone <repo-url> personal-dashboard
cd personal-dashboard

make dev    # Backend (port 8000) + frontend (port 5173) with hot reload
```

Open [http://localhost:5173](http://localhost:5173) — the setup wizard will guide you through connecting your services.

### Native macOS App

```bash
make dashboard   # Install deps, build, and launch the native macOS app
```

This updates dependencies, builds the frontend, and opens `Dashboard.app` — a native macOS window powered by pywebview. No browser needed.

## First-Run Setup

On first launch, a setup wizard walks you through:

1. **Profile** — Your name, title, company (optional — personalizes AI prompts)
2. **Connectors** — Enable services and enter credentials right in the app
3. **Done** — Start using the dashboard

All steps are skippable. The dashboard works with zero configuration and you can connect services later in Settings.

## Data Storage

All user data lives in `~/.personal-dashboard/` (configurable via `DASHBOARD_DATA_DIR` env var):

```
~/.personal-dashboard/
  config.json      # Profile, secrets, connector settings (chmod 0600)
  dashboard.db     # SQLite database
```

Secrets are stored in `config.json` with restricted file permissions. Environment variables (`.env`) are also supported as a fallback.

## Connectors

| Connector | Type | What It Syncs |
|-----------|------|---------------|
| Google | OAuth | Gmail, Calendar |
| Google Drive | OAuth | Drive files, Docs, Sheets |
| Slack | API Token | DMs, mentions, channel search |
| Notion | API Token | Recently edited pages |
| GitHub | CLI (`gh`) | Pull requests, issues, code search |
| Granola | Local file | Meeting transcripts and notes |
| Ramp | Client credentials | Transactions, bills, vendors (incremental sync) |
| News | None | URL extraction from Slack/email + Google News RSS |
| Gemini AI | API Key | Powers AI priority rankings, issue discovery, and relevance scoring |

Each connector includes setup instructions in the app. Enable/disable them in Settings.

## Pages

| Route | Page | Purpose |
|-------|------|---------|
| `/` | Briefing | Morning briefing: weather, inbox pulse, calendar, AI priorities, overnight digest |
| `/priorities` | Priorities | Detailed AI priority rankings view |
| `/notes` | Notes | Task CRUD with @mention autocomplete |
| `/thoughts` | Thoughts | Personal notes prefixed with `[t]` |
| `/issues` | Issues | Local issue tracking with priority, sizing, tags, and AI discovery |
| `/longform` | Longform | Blog posts and drafts with markdown editor, tags, and comments |
| `/team` | Org Chart | Hierarchical team view |
| `/people` | People | Directory of coworkers and contacts with group filtering |
| `/people/:id` | Person | Person detail: meetings, 1:1 topics, notes, attributes, connections |
| `/meetings` | Meetings | Calendar + Granola meeting history |
| `/email` | Email | Gmail search and thread reading |
| `/slack` | Slack | Message history, channels, DMs |
| `/notion` | Notion | Recently edited pages |
| `/drive` | Drive | Google Drive files with Gemini AI relevance ranking |
| `/github` | GitHub | Pull requests and issues |
| `/ramp` | Ramp | Transactions, bills, and project tracking with AI ranking |
| `/news` | News | Infinite scroll aggregated news |
| `/claude` | Claude Code | Embedded CLI terminal |
| `/personas` | Personas | Claude Code persona and session management |
| `/help` | Help | Feature overview and keyboard shortcuts |
| `/settings` | Settings | Profile, connectors, sync controls |
| `/setup` | Setup | First-run onboarding wizard |

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI, Uvicorn, Python 3.11+ |
| Frontend | React 19, TypeScript, Vite, React Router |
| State | TanStack React Query |
| Database | SQLite (WAL mode) |
| Styling | Custom Tufte CSS — no Tailwind/MUI |
| Native app | pywebview |
| AI | Gemini 2.0 Flash |
| Terminal | xterm.js via WebSocket PTY |

## Make Commands

| Command | Description |
|---------|-------------|
| `make dashboard` | Install deps, build, and launch native macOS app |
| `make dev` | Start backend + frontend with hot reload |
| `make build` | Build production frontend |
| `make app` | Build and launch native macOS app (no dep install) |
| `make start` | Same as `make dashboard` |
| `make stop` | Kill servers |
| `make restart` | Stop + start dev mode |
| `make status` | Check if servers are running |
| `make logs` | Tail backend + frontend logs |
| `make lint` | Run Python (ruff) and TypeScript (tsc + eslint) linting |
| `make fmt` | Auto-format Python and TypeScript |
| `make test` | Run Playwright tests (requires `make dev` running) |
| `make db-upgrade` | Run Alembic database migrations |
| `make db-downgrade` | Roll back last migration |
| `make db-revision` | Create a new migration |

## Development

```bash
# Backend only
cd app/backend
source venv/bin/activate
uvicorn main:app --reload --port 8000

# Frontend only
cd app/frontend
npm run dev
```

The frontend dev server proxies API requests to `localhost:8000`.

## Architecture

- **Local-only** — runs entirely on your machine, no cloud
- **Single user** — no auth layer, trusted local environment
- **Sync-on-demand** — data syncs manually or via the Sync button; Granola syncs on startup; Ramp supports incremental sync
- **Plugin connectors** — each service self-registers with metadata
- **AI-powered** — Gemini ranks priorities, discovers issues, scores Drive files and expenses
- **Full-text search** — SQLite FTS indexes across people, notes, meetings, emails, and issues
- **People management** — coworkers vs. contacts, with groups, social links, custom attributes, and relationship tracking

## Keyboard Shortcuts

Press `?` in the app to see all shortcuts. Highlights:

- `Cmd+K` — Search / command palette (`Tab` to quick-create, `Cmd+E` for external search)
- `c` — Quick-capture a note
- `D` — Discover issues (AI scan of email, Slack, meetings, Notion, calendar)
- `s` — Trigger sync
- `r` — Refresh page data
- `u` — Undo last action
- `j/k` — Navigate lists
- `g d` — Go to Briefing (chord: `g` then a letter)
- `g n` — Go to Notes
- `g i` — Go to Issues
- `g l` — Go to Longform
- `g m` — Go to Meetings
- `g c` — Go to Claude

Full navigation chords: `g d` (briefing), `g n` (notes), `g t` (thoughts), `g i` (issues), `g l` (longform), `g m` (meetings), `g w` (news), `g p` (people), `g o` (team/org), `g h` (github), `g c` (claude), `g x` (ramp), `g s` (settings).

## API

All data is accessible via REST at `http://localhost:8000`. See [CLAUDE.md](CLAUDE.md) for the full API reference.

## License

MIT
