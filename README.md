# Personal Dashboard

A local-first personal dashboard that centralizes your email, calendar, Slack, Notion, GitHub, meetings, and more into a single quiet interface. Runs as a native macOS app or in the browser.

## Features

- **AI Priorities**: Morning briefings powered by Gemini, pulling from your email, Slack, calendar, and notes
- **Team Management**: Org chart, 1:1 topic tracking, per-person context pages, meeting history
- **Notes**: Quick-capture with `@mention` autocomplete, employee linking, and keyboard shortcuts
- **Unified Inbox**: Gmail, Slack, Notion, and GitHub activity in one view
- **News Feed**: Aggregated from your Slack channels, email, and Google News RSS
- **Meetings**: Calendar integration plus Granola transcript sync
- **Embedded Claude Code**: Full Claude Code CLI terminal inside the dashboard
- **Plugin Connectors**: Enable/disable services as needed — Google, Slack, Notion, GitHub, Ramp, Granola, and more

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
| Google | OAuth | Gmail, Calendar, Drive |
| Slack | API Token | DMs, mentions, channel search |
| Notion | API Token | Recently edited pages |
| GitHub | CLI (`gh`) | Pull requests, issues, code search |
| Granola | Local file | Meeting transcripts and notes |
| Ramp | Client credentials | Expenses, vendors, bills |
| News | None | URL extraction from Slack/email + Google News RSS |
| Gemini AI | API Key | Powers AI priority rankings |

Each connector includes setup instructions in the app. Enable/disable them in Settings.

## Pages

| Route | Page | Purpose |
|-------|------|---------|
| `/` | Dashboard | AI priorities, calendar, email, Slack, Notion, news |
| `/notes` | Notes | Task CRUD with @mention autocomplete |
| `/thoughts` | Thoughts | Personal notes prefixed with `[t]` |
| `/team` | Org Chart | Hierarchical team view |
| `/employees/:id` | Employee | Person detail: meetings, 1:1 topics, notes |
| `/meetings` | Meetings | Calendar + Granola meeting history |
| `/email` | Email | Gmail search and thread reading |
| `/slack` | Slack | Message history, channels, DMs |
| `/notion` | Notion | Recently edited pages |
| `/github` | GitHub | Pull requests and issues |
| `/ramp` | Ramp | Expense tracking |
| `/news` | News | Infinite scroll aggregated news |
| `/claude` | Claude Code | Embedded CLI terminal |
| `/settings` | Settings | Profile, connectors, sync controls |
| `/setup` | Setup | First-run onboarding wizard |

## Team Data

Employee profiles and meeting notes are stored as markdown:

```
teams/{person}/
  role.md               # Title, responsibilities, goals
  1-1.md                # Running 1:1 topics
  meetings/             # Meeting note files
    2024-01-15-topic.md

executives/{person}/    # Executive team (same structure)
```

The markdown connector reads these on sync and populates the database.

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
- **Sync-on-demand** — data syncs manually or via the Sync button
- **Plugin connectors** — each service self-registers with metadata
- **Markdown-driven** — team data lives in git-trackable markdown files

## Keyboard Shortcuts

Press `?` in the app to see all shortcuts. Highlights:

- `Cmd+K` — Search across everything
- `c` — Quick-capture a note
- `s` — Trigger sync
- `j/k` — Navigate lists
- `r` — Refresh data

## API

All data is accessible via REST at `http://localhost:8000`. See [CLAUDE.md](CLAUDE.md) for the full API reference.

## License

MIT
