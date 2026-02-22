import json
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks

from connectors.markdown import parse_meeting_files
from database import batch_upsert, get_db_connection, get_write_db
from utils.employee_matching import rebuild_from_db

router = APIRouter(prefix="/api/sync", tags=["sync"])

_sync_lock = threading.Lock()
_sync_running = False
_sync_current_source: str | None = None


def _update_sync_state(source: str, status: str, error: str | None, items: int):
    with get_write_db() as db:
        db.execute(
            """INSERT INTO sync_state (source, last_sync_at, last_sync_status, last_error, items_synced)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(source) DO UPDATE SET
                 last_sync_at=excluded.last_sync_at,
                 last_sync_status=excluded.last_sync_status,
                 last_error=excluded.last_error,
                 items_synced=excluded.items_synced""",
            (source, datetime.now().isoformat(), status, error, items),
        )
        db.commit()


def sync_meeting_files():
    """Refresh meeting_files table from disk for employees that have a dir_path."""
    # Phase 1: Read employee list
    with get_db_connection(readonly=True) as db:
        emp_rows = db.execute(
            "SELECT id, dir_path FROM employees WHERE dir_path IS NOT NULL AND dir_path != ''"
        ).fetchall()

    # Phase 2: Parse all meeting files from disk (no DB connection held)
    all_rows = []
    for row in emp_rows:
        meetings_dir = Path(row["dir_path"]) / "meetings"
        meetings = parse_meeting_files(meetings_dir, row["id"])
        for m in meetings:
            all_rows.append(
                (
                    m["employee_id"],
                    m["filename"],
                    m["filepath"],
                    m["meeting_date"],
                    m["title"],
                    m["summary"],
                    json.dumps(m["action_items"]),
                    m["granola_link"],
                    m["content_markdown"],
                    m["last_modified"],
                )
            )

    # Phase 3: Write in batches with write lock
    try:
        with get_write_db() as db:
            batch_upsert(
                db,
                """INSERT INTO meeting_files
                   (employee_id, filename, filepath, meeting_date, title, summary,
                    action_items_json, granola_link, content_markdown, last_modified)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(filepath) DO UPDATE SET
                     employee_id=excluded.employee_id,
                     filename=excluded.filename,
                     meeting_date=excluded.meeting_date,
                     title=excluded.title,
                     summary=excluded.summary,
                     action_items_json=excluded.action_items_json,
                     granola_link=excluded.granola_link,
                     content_markdown=excluded.content_markdown,
                     last_modified=excluded.last_modified""",
                all_rows,
            )
        rebuild_from_db()
        _update_sync_state("markdown", "success", None, len(all_rows))
    except Exception:
        _update_sync_state("markdown", "error", traceback.format_exc(), 0)
        raise


# Keep old name as alias for backward compatibility
sync_markdown = sync_meeting_files


def sync_granola():
    """Parse Granola cache and populate granola_meetings table."""
    try:
        from connectors.granola import sync_granola_meetings

        count = sync_granola_meetings()
        _update_sync_state("granola", "success", None, count)
    except ImportError:
        _update_sync_state("granola", "error", "Granola connector not yet implemented", 0)
    except Exception:
        _update_sync_state("granola", "error", traceback.format_exc(), 0)


def sync_gmail():
    try:
        from connectors.gmail import sync_gmail_messages

        count = sync_gmail_messages()
        _update_sync_state("gmail", "success", None, count)
    except ImportError:
        _update_sync_state("gmail", "error", "Gmail connector not yet implemented", 0)
    except Exception:
        _update_sync_state("gmail", "error", traceback.format_exc(), 0)


def sync_calendar():
    try:
        from connectors.calendar_sync import sync_calendar_events

        count = sync_calendar_events()
        _update_sync_state("calendar", "success", None, count)
    except ImportError:
        _update_sync_state("calendar", "error", "Calendar connector not yet implemented", 0)
    except Exception:
        _update_sync_state("calendar", "error", traceback.format_exc(), 0)


def sync_slack():
    try:
        from connectors.slack import sync_slack_data

        count = sync_slack_data()
        _update_sync_state("slack", "success", None, count)
    except ImportError:
        _update_sync_state("slack", "error", "Slack connector not yet implemented", 0)
    except Exception:
        _update_sync_state("slack", "error", traceback.format_exc(), 0)


def sync_notion():
    try:
        from connectors.notion import sync_notion_pages

        count = sync_notion_pages()
        _update_sync_state("notion", "success", None, count)
    except ImportError:
        _update_sync_state("notion", "error", "Notion connector not yet implemented", 0)
    except Exception:
        _update_sync_state("notion", "error", traceback.format_exc(), 0)


def sync_github():
    try:
        from connectors.github import sync_github_prs

        count = sync_github_prs()
        _update_sync_state("github", "success", None, count)
    except ImportError:
        _update_sync_state("github", "error", "GitHub connector not available", 0)
    except Exception:
        _update_sync_state("github", "error", traceback.format_exc(), 0)


def sync_ramp(org_only: bool = False):
    try:
        from connectors.ramp import sync_ramp_transactions

        count = sync_ramp_transactions(org_only=org_only)
        _update_sync_state("ramp", "success", None, count)
    except ImportError:
        _update_sync_state("ramp", "error", "Ramp connector not available", 0)
    except Exception:
        _update_sync_state("ramp", "error", traceback.format_exc(), 0)


def sync_ramp_vendors():
    try:
        from connectors.ramp import sync_ramp_vendors as _sync_vendors

        count = _sync_vendors()
        _update_sync_state("ramp_vendors", "success", None, count)
    except ImportError:
        _update_sync_state("ramp_vendors", "error", "Ramp connector not available", 0)
    except Exception:
        _update_sync_state("ramp_vendors", "error", traceback.format_exc(), 0)


def sync_ramp_bills():
    try:
        from connectors.ramp import seed_projects_from_vendors
        from connectors.ramp import sync_ramp_bills as _sync_bills

        count = _sync_bills()
        seed_projects_from_vendors()
        _update_sync_state("ramp_bills", "success", None, count)
    except ImportError:
        _update_sync_state("ramp_bills", "error", "Ramp connector not available", 0)
    except Exception:
        _update_sync_state("ramp_bills", "error", traceback.format_exc(), 0)


def sync_news():
    try:
        from connectors.news import sync_news as _sync_news

        count = _sync_news()
        _update_sync_state("news", "success", None, count)
    except ImportError:
        _update_sync_state("news", "error", "News connector not available", 0)
    except Exception:
        _update_sync_state("news", "error", traceback.format_exc(), 0)


def _is_enabled(connector_id: str) -> bool:
    """Check if a connector is enabled in the registry."""
    try:
        from connectors.registry import is_enabled

        return is_enabled(connector_id)
    except Exception:
        return True  # Default to enabled if registry not initialized


def _run_full_sync():
    global _sync_running, _sync_current_source
    try:
        # Group 1: Local sources — fast, no network, run in parallel
        _sync_current_source = "markdown"
        local_fns = [sync_meeting_files]
        if _is_enabled("granola"):
            local_fns.append(sync_granola)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futs = [pool.submit(fn) for fn in local_fns]
            for f in as_completed(futs):
                try:
                    f.result()
                except Exception:
                    pass

        # Group 2: External APIs — independent of each other, run in parallel
        _sync_current_source = "external"
        external = []
        if _is_enabled("google"):
            external.extend([sync_gmail, sync_calendar])
        if _is_enabled("slack"):
            external.append(sync_slack)
        if _is_enabled("notion"):
            external.append(sync_notion)
        if _is_enabled("github"):
            external.append(sync_github)
        if _is_enabled("ramp"):
            external.extend([sync_ramp, sync_ramp_vendors])

        if external:
            with ThreadPoolExecutor(max_workers=3) as pool:
                futs = [pool.submit(fn) for fn in external]
                for f in as_completed(futs):
                    try:
                        f.result()
                    except Exception:
                        pass

        # Group 3: Bills — depends on vendors being synced first
        if _is_enabled("ramp"):
            _sync_current_source = "ramp_bills"
            sync_ramp_bills()

        # Group 4: News — reads from already-synced slack/email rows, must run last
        if _is_enabled("news"):
            _sync_current_source = "news"
            sync_news()

        _sync_current_source = None
        # Rebuild FTS indexes after all data is refreshed
        from database import rebuild_fts

        rebuild_fts()
    finally:
        _sync_current_source = None
        _sync_running = False


@router.post("")
def trigger_sync(background_tasks: BackgroundTasks):
    global _sync_running
    with _sync_lock:
        if _sync_running:
            return {"status": "already_running"}
        _sync_running = True
    background_tasks.add_task(_run_full_sync)
    return {"status": "started"}


@router.post("/{source}")
def trigger_source_sync(source: str, background_tasks: BackgroundTasks, org_only: bool = True):
    if source == "ramp":
        background_tasks.add_task(sync_ramp, org_only=org_only)
        return {"status": "started", "source": source, "org_only": org_only}

    sync_map = {
        "markdown": sync_meeting_files,
        "granola": sync_granola,
        "gmail": sync_gmail,
        "calendar": sync_calendar,
        "slack": sync_slack,
        "notion": sync_notion,
        "github": sync_github,
        "news": sync_news,
        "ramp_vendors": sync_ramp_vendors,
        "ramp_bills": sync_ramp_bills,
    }
    fn = sync_map.get(source)
    if not fn:
        return {"error": f"Unknown source: {source}"}
    background_tasks.add_task(fn)
    return {"status": "started", "source": source}


@router.get("/status")
def get_sync_status():
    global _sync_running, _sync_current_source
    with get_db_connection(readonly=True) as db:
        rows = db.execute("SELECT * FROM sync_state").fetchall()
    return {
        "running": _sync_running,
        "current_source": _sync_current_source,
        "sources": {row["source"]: dict(row) for row in rows},
    }
