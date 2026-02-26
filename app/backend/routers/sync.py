import json
import logging
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

from fastapi import APIRouter, BackgroundTasks

from connectors.markdown import parse_meeting_files
from database import batch_upsert, get_db_connection, get_write_db
from utils.person_matching import rebuild_from_db

router = APIRouter(prefix="/api/sync", tags=["sync"])

_sync_lock = threading.Lock()
_sync_running = False
_sync_active_sources: set[str] = set()
_sync_cancel = threading.Event()


def _update_sync_state(source: str, status: str, error: str | None, items: int, elapsed: float | None = None):
    with get_write_db() as db:
        db.execute(
            """INSERT INTO sync_state (source, last_sync_at, last_sync_status, last_error, items_synced, duration_seconds)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(source) DO UPDATE SET
                 last_sync_at=excluded.last_sync_at,
                 last_sync_status=excluded.last_sync_status,
                 last_error=excluded.last_error,
                 items_synced=excluded.items_synced,
                 duration_seconds=excluded.duration_seconds""",
            (source, datetime.now().isoformat(), status, error, items, round(elapsed, 1) if elapsed is not None else None),
        )
        db.commit()
    if elapsed is not None:
        logger.info("Sync [%s]: %s — %d items in %.1fs", source, status, items, elapsed)


def sync_meeting_files():
    """Refresh meeting_files table from disk for people that have a dir_path."""
    t0 = time.monotonic()
    # Phase 1: Read people list
    with get_db_connection(readonly=True) as db:
        emp_rows = db.execute(
            "SELECT id, dir_path FROM people WHERE dir_path IS NOT NULL AND dir_path != ''"
        ).fetchall()

    # Phase 2: Parse all meeting files from disk (no DB connection held)
    all_rows = []
    for row in emp_rows:
        meetings_dir = Path(row["dir_path"]) / "meetings"
        meetings = parse_meeting_files(meetings_dir, row["id"])
        for m in meetings:
            all_rows.append(
                (
                    m["person_id"],
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
                   (person_id, filename, filepath, meeting_date, title, summary,
                    action_items_json, granola_link, content_markdown, last_modified)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(filepath) DO UPDATE SET
                     person_id=excluded.person_id,
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
        _update_sync_state("markdown", "success", None, len(all_rows), elapsed=time.monotonic() - t0)
    except Exception:
        _update_sync_state("markdown", "error", traceback.format_exc(), 0, elapsed=time.monotonic() - t0)
        raise


# Keep old name as alias for backward compatibility
sync_markdown = sync_meeting_files


def sync_granola():
    """Parse Granola cache and populate granola_meetings table."""
    t0 = time.monotonic()
    try:
        from connectors.granola import sync_granola_meetings

        count = sync_granola_meetings()
        _update_sync_state("granola", "success", None, count, elapsed=time.monotonic() - t0)
    except ImportError:
        _update_sync_state("granola", "error", "Granola connector not yet implemented", 0)
    except Exception:
        _update_sync_state("granola", "error", traceback.format_exc(), 0, elapsed=time.monotonic() - t0)


def sync_gmail():
    t0 = time.monotonic()
    try:
        from connectors.gmail import sync_gmail_messages

        count = sync_gmail_messages()
        _update_sync_state("gmail", "success", None, count, elapsed=time.monotonic() - t0)
    except ImportError:
        _update_sync_state("gmail", "error", "Gmail connector not yet implemented", 0)
    except Exception:
        _update_sync_state("gmail", "error", traceback.format_exc(), 0, elapsed=time.monotonic() - t0)


def sync_calendar():
    t0 = time.monotonic()
    try:
        from connectors.calendar_sync import sync_calendar_events

        count = sync_calendar_events()
        _update_sync_state("calendar", "success", None, count, elapsed=time.monotonic() - t0)
    except ImportError:
        _update_sync_state("calendar", "error", "Calendar connector not yet implemented", 0)
    except Exception:
        _update_sync_state("calendar", "error", traceback.format_exc(), 0, elapsed=time.monotonic() - t0)


def sync_slack():
    t0 = time.monotonic()
    try:
        from connectors.slack import sync_slack_data

        count = sync_slack_data()
        _update_sync_state("slack", "success", None, count, elapsed=time.monotonic() - t0)
    except ImportError:
        _update_sync_state("slack", "error", "Slack connector not yet implemented", 0)
    except Exception:
        _update_sync_state("slack", "error", traceback.format_exc(), 0, elapsed=time.monotonic() - t0)


def sync_notion():
    t0 = time.monotonic()
    try:
        from connectors.notion import sync_notion_pages

        count = sync_notion_pages()
        _update_sync_state("notion", "success", None, count, elapsed=time.monotonic() - t0)
    except ImportError:
        _update_sync_state("notion", "error", "Notion connector not yet implemented", 0)
    except Exception:
        _update_sync_state("notion", "error", traceback.format_exc(), 0, elapsed=time.monotonic() - t0)


def sync_github():
    t0 = time.monotonic()
    try:
        from connectors.github import sync_github_prs

        count = sync_github_prs()
        _update_sync_state("github", "success", None, count, elapsed=time.monotonic() - t0)
    except ImportError:
        _update_sync_state("github", "error", "GitHub connector not available", 0)
    except Exception:
        _update_sync_state("github", "error", traceback.format_exc(), 0, elapsed=time.monotonic() - t0)


def _get_last_sync_date(source: str) -> str | None:
    """Return the last successful sync timestamp for incremental fetching."""
    try:
        with get_db_connection(readonly=True) as db:
            row = db.execute(
                "SELECT last_sync_at FROM sync_state WHERE source = ? AND last_sync_status = 'success'",
                (source,),
            ).fetchone()
            return row["last_sync_at"] if row else None
    except Exception:
        return None


def sync_ramp(org_only: bool = False):
    t0 = time.monotonic()
    try:
        from connectors.ramp import sync_ramp_transactions

        # Use last sync time for incremental fetch instead of full 90-day window
        from_date = _get_last_sync_date("ramp")
        count = sync_ramp_transactions(org_only=org_only, from_date=from_date)
        _update_sync_state("ramp", "success", None, count, elapsed=time.monotonic() - t0)
    except ImportError:
        _update_sync_state("ramp", "error", "Ramp connector not available", 0)
    except Exception:
        _update_sync_state("ramp", "error", traceback.format_exc(), 0, elapsed=time.monotonic() - t0)


def sync_ramp_vendors():
    t0 = time.monotonic()
    try:
        from connectors.ramp import sync_ramp_vendors as _sync_vendors

        count = _sync_vendors()
        _update_sync_state("ramp_vendors", "success", None, count, elapsed=time.monotonic() - t0)
    except ImportError:
        _update_sync_state("ramp_vendors", "error", "Ramp connector not available", 0)
    except Exception:
        _update_sync_state("ramp_vendors", "error", traceback.format_exc(), 0, elapsed=time.monotonic() - t0)


def sync_ramp_bills():
    t0 = time.monotonic()
    try:
        from connectors.ramp import seed_projects_from_vendors
        from connectors.ramp import sync_ramp_bills as _sync_bills

        # Use last sync time for incremental fetch; skip wipe when doing incremental
        from_date = _get_last_sync_date("ramp_bills")
        count = _sync_bills(from_date=from_date, wipe=from_date is None)
        seed_projects_from_vendors()
        _update_sync_state("ramp_bills", "success", None, count, elapsed=time.monotonic() - t0)
    except ImportError:
        _update_sync_state("ramp_bills", "error", "Ramp connector not available", 0)
    except Exception:
        _update_sync_state("ramp_bills", "error", traceback.format_exc(), 0, elapsed=time.monotonic() - t0)


def sync_news():
    t0 = time.monotonic()
    try:
        from connectors.news import sync_news as _sync_news

        count = _sync_news()
        _update_sync_state("news", "success", None, count, elapsed=time.monotonic() - t0)
    except ImportError:
        _update_sync_state("news", "error", "News connector not available", 0)
    except Exception:
        _update_sync_state("news", "error", traceback.format_exc(), 0, elapsed=time.monotonic() - t0)


def sync_drive():
    t0 = time.monotonic()
    try:
        from connectors.drive import sync_drive_files

        count = sync_drive_files()
        _update_sync_state("drive", "success", None, count, elapsed=time.monotonic() - t0)
    except ImportError:
        _update_sync_state("drive", "error", "Drive connector not available", 0)
    except Exception:
        _update_sync_state("drive", "error", traceback.format_exc(), 0, elapsed=time.monotonic() - t0)


def sync_sheets():
    t0 = time.monotonic()
    try:
        from connectors.sheets import sync_sheets_data

        count = sync_sheets_data()
        _update_sync_state("sheets", "success", None, count, elapsed=time.monotonic() - t0)
    except ImportError:
        _update_sync_state("sheets", "error", "Sheets connector not available", 0)
    except Exception:
        _update_sync_state("sheets", "error", traceback.format_exc(), 0, elapsed=time.monotonic() - t0)


def sync_docs():
    t0 = time.monotonic()
    try:
        from connectors.docs import sync_docs_data

        count = sync_docs_data()
        _update_sync_state("docs", "success", None, count, elapsed=time.monotonic() - t0)
    except ImportError:
        _update_sync_state("docs", "error", "Docs connector not available", 0)
    except Exception:
        _update_sync_state("docs", "error", traceback.format_exc(), 0, elapsed=time.monotonic() - t0)


def _is_enabled(connector_id: str) -> bool:
    """Check if a connector is enabled in the registry."""
    try:
        from connectors.registry import is_enabled

        return is_enabled(connector_id)
    except Exception:
        return True  # Default to enabled if registry not initialized


def _tracked(source_key: str, fn, *args, **kwargs):
    """Wrapper that tracks individual source as active while it runs."""
    _sync_active_sources.add(source_key)
    try:
        fn(*args, **kwargs)
    finally:
        _sync_active_sources.discard(source_key)


def _run_group(fns: list[tuple[str, callable]], max_workers: int = 3):
    """Run a list of (source_key, fn) pairs in parallel with tracking."""
    if not fns:
        return
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = [pool.submit(_tracked, key, fn) for key, fn in fns]
        for f in as_completed(futs):
            try:
                f.result()
            except Exception:
                pass


def _run_full_sync():
    global _sync_running
    _sync_cancel.clear()
    _sync_active_sources.clear()
    try:
        # Group 1: Local sources — fast, no network, run in parallel
        local_fns: list[tuple[str, callable]] = [("markdown", sync_meeting_files)]
        if _is_enabled("granola"):
            local_fns.append(("granola", sync_granola))
        _run_group(local_fns, max_workers=2)

        if _sync_cancel.is_set():
            return

        # Group 2: External APIs — independent of each other, run in parallel
        external: list[tuple[str, callable]] = []
        if _is_enabled("google"):
            external.extend([("gmail", sync_gmail), ("calendar", sync_calendar)])
        if _is_enabled("slack"):
            external.append(("slack", sync_slack))
        if _is_enabled("notion"):
            external.append(("notion", sync_notion))
        if _is_enabled("github"):
            external.append(("github", sync_github))
        if _is_enabled("ramp"):
            external.extend([("ramp", sync_ramp), ("ramp_vendors", sync_ramp_vendors)])
        if _is_enabled("google_drive"):
            external.append(("drive", sync_drive))
        _run_group(external)

        if _sync_cancel.is_set():
            return

        # Group 2.5: Sheets & Docs — depend on drive_files being populated
        if _is_enabled("google_drive"):
            _run_group([("sheets", sync_sheets), ("docs", sync_docs)], max_workers=2)

        if _sync_cancel.is_set():
            return

        # Group 3: Bills — depends on vendors being synced first
        if _is_enabled("ramp"):
            _tracked("ramp_bills", sync_ramp_bills)

        if _sync_cancel.is_set():
            return

        # Group 4: News — reads from already-synced slack/email rows, must run last
        if _is_enabled("news"):
            _tracked("news", sync_news)

        if _sync_cancel.is_set():
            return

        # Rebuild FTS indexes after all data is refreshed
        from database import rebuild_fts

        rebuild_fts()
    finally:
        _sync_active_sources.clear()
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


@router.post("/cancel")
def cancel_sync():
    global _sync_running
    with _sync_lock:
        if not _sync_running:
            return {"status": "not_running"}
        _sync_cancel.set()
    return {"status": "cancelling"}


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
        "drive": sync_drive,
        "sheets": sync_sheets,
        "docs": sync_docs,
    }
    fn = sync_map.get(source)
    if not fn:
        return {"error": f"Unknown source: {source}"}
    background_tasks.add_task(fn)
    return {"status": "started", "source": source}


@router.get("/status")
def get_sync_status():
    global _sync_running
    with get_db_connection(readonly=True) as db:
        rows = db.execute("SELECT * FROM sync_state").fetchall()
    return {
        "running": _sync_running,
        "active_sources": sorted(_sync_active_sources),
        "sources": {row["source"]: dict(row) for row in rows},
    }
