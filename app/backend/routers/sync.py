import json
import logging
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks

from connectors.markdown import parse_meeting_files
from database import batch_upsert, get_db_connection, get_write_db
from utils.person_matching import rebuild_from_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sync", tags=["sync"])

_sync_lock = threading.Lock()
_sync_running = False
_sync_started_at: float | None = None  # time.monotonic() timestamp when sync began
_sync_active_sources: set[str] = set()
_sync_cancel = threading.Event()

MAX_SYNC_SECONDS = 600  # 10 minutes — force-reset if sync appears stuck (e.g. laptop sleep)

# Auto-sync background scheduler
_auto_sync_thread: threading.Thread | None = None
_auto_sync_stop = threading.Event()
DEFAULT_AUTO_SYNC_INTERVAL = 900  # 15 minutes


def _check_stale_sync_unlocked():
    """Reset _sync_running if it has been stuck too long. Must be called with _sync_lock held."""
    global _sync_running, _sync_started_at
    if _sync_running and _sync_started_at is not None:
        elapsed = time.monotonic() - _sync_started_at
        if elapsed > MAX_SYNC_SECONDS:
            logger.warning("Sync appears stuck (%.0fs elapsed); resetting sync state", elapsed)
            _sync_running = False
            _sync_started_at = None
            _sync_active_sources.clear()
            _sync_cancel.set()  # signal any surviving threads to stop


def _update_sync_state(source: str, status: str, error: str | None, items: int, elapsed: float | None = None):
    with get_write_db() as db:
        db.execute(
            """INSERT INTO sync_state
               (source, last_sync_at, last_sync_status, last_error, items_synced, duration_seconds)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(source) DO UPDATE SET
                 last_sync_at=excluded.last_sync_at,
                 last_sync_status=excluded.last_sync_status,
                 last_error=excluded.last_error,
                 items_synced=excluded.items_synced,
                 duration_seconds=excluded.duration_seconds""",
            (
                source,
                datetime.now().isoformat(),
                status,
                error,
                items,
                round(elapsed, 1) if elapsed is not None else None,
            ),
        )
        db.commit()
    if elapsed is not None:
        logger.info("Sync [%s]: %s — %d items in %.1fs", source, status, items, elapsed)


# Phrases that indicate missing credentials / setup rather than a real sync error
_SETUP_PHRASES = [
    "not configured",
    "not authenticated",
    "no google credentials",
    "click authenticate",
    "add it in settings",
    "add them in settings",
    "add google_client_id",
    "please re-authenticate",
    "gh auth login",
    "gh cli not",
    "scopes have changed",
    "no microsoft credentials",
    "add microsoft_client_id",
]


def _is_setup_error(exc: Exception) -> bool:
    """Return True if the exception indicates missing credentials/setup, not a real sync error."""
    msg = str(exc).lower()
    return any(phrase in msg for phrase in _SETUP_PHRASES)


def _handle_sync_error(source: str, exc: Exception, elapsed: float):
    """Store sync error with appropriate status — 'needs_setup' for auth issues, 'error' for real failures."""
    if _is_setup_error(exc):
        # Clean user-friendly message without traceback
        _update_sync_state(source, "needs_setup", str(exc), 0, elapsed=elapsed)
    else:
        _update_sync_state(source, "error", traceback.format_exc(), 0, elapsed=elapsed)


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
    if not _is_enabled("granola"):
        return
    t0 = time.monotonic()
    try:
        from connectors.granola import resync_missing_summaries, sync_granola_meetings

        count = sync_granola_meetings()
        # Backfill any historical meetings that are missing summaries
        resync_missing_summaries()
        _update_sync_state("granola", "success", None, count, elapsed=time.monotonic() - t0)
    except ImportError:
        _update_sync_state("granola", "error", "Granola connector not yet implemented", 0)
    except Exception as e:
        _handle_sync_error("granola", e, time.monotonic() - t0)


def sync_gmail():
    if not _is_enabled("google"):
        return
    t0 = time.monotonic()
    try:
        from connectors.gmail import sync_gmail_messages

        count = sync_gmail_messages()
        _update_sync_state("gmail", "success", None, count, elapsed=time.monotonic() - t0)
    except ImportError:
        _update_sync_state("gmail", "error", "Gmail connector not yet implemented", 0)
    except Exception as e:
        _handle_sync_error("gmail", e, time.monotonic() - t0)


def sync_calendar():
    if not _is_enabled("google"):
        return
    t0 = time.monotonic()
    try:
        from connectors.calendar_sync import sync_calendar_events

        count = sync_calendar_events()
        _update_sync_state("calendar", "success", None, count, elapsed=time.monotonic() - t0)
    except ImportError:
        _update_sync_state("calendar", "error", "Calendar connector not yet implemented", 0)
    except Exception as e:
        _handle_sync_error("calendar", e, time.monotonic() - t0)


def sync_outlook_email():
    if not _is_enabled("microsoft"):
        return
    t0 = time.monotonic()
    try:
        from connectors.outlook_email import sync_outlook_messages

        count = sync_outlook_messages()
        _update_sync_state("outlook_email", "success", None, count, elapsed=time.monotonic() - t0)
    except Exception as e:
        _handle_sync_error("outlook_email", e, time.monotonic() - t0)


def sync_outlook_calendar():
    if not _is_enabled("microsoft"):
        return
    t0 = time.monotonic()
    try:
        from connectors.outlook_calendar import sync_outlook_events

        count = sync_outlook_events()
        _update_sync_state("outlook_calendar", "success", None, count, elapsed=time.monotonic() - t0)
    except Exception as e:
        _handle_sync_error("outlook_calendar", e, time.monotonic() - t0)


def sync_slack():
    if not _is_enabled("slack"):
        return
    t0 = time.monotonic()
    try:
        from connectors.slack import sync_slack_data

        count = sync_slack_data()
        _update_sync_state("slack", "success", None, count, elapsed=time.monotonic() - t0)
    except ImportError:
        _update_sync_state("slack", "error", "Slack connector not yet implemented", 0)
    except Exception as e:
        _handle_sync_error("slack", e, time.monotonic() - t0)


def sync_notion():
    if not _is_enabled("notion"):
        return
    t0 = time.monotonic()
    try:
        from connectors.notion import sync_notion_pages

        count = sync_notion_pages()
        _update_sync_state("notion", "success", None, count, elapsed=time.monotonic() - t0)
    except ImportError:
        _update_sync_state("notion", "error", "Notion connector not yet implemented", 0)
    except Exception as e:
        _handle_sync_error("notion", e, time.monotonic() - t0)


def sync_notion_meetings():
    """Sync meeting notes from Notion (if Notion is the meeting notes provider)."""
    if not _is_enabled("notion"):
        return
    t0 = time.monotonic()
    try:
        from connectors.notion_meetings import sync_notion_meeting_notes

        count = sync_notion_meeting_notes()
        _update_sync_state("notion_meetings", "success", None, count, elapsed=time.monotonic() - t0)
    except ImportError:
        _update_sync_state("notion_meetings", "error", "Notion meetings connector not available", 0)
    except Exception as e:
        _handle_sync_error("notion_meetings", e, time.monotonic() - t0)


def sync_github():
    if not _is_enabled("github"):
        return
    t0 = time.monotonic()
    try:
        from connectors.github import sync_github_prs

        count = sync_github_prs()
        _update_sync_state("github", "success", None, count, elapsed=time.monotonic() - t0)
    except ImportError:
        _update_sync_state("github", "error", "GitHub connector not available", 0)
    except Exception as e:
        _handle_sync_error("github", e, time.monotonic() - t0)


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
    if not _is_enabled("ramp"):
        return
    t0 = time.monotonic()
    try:
        from connectors.ramp import sync_ramp_transactions

        # Use last sync time for incremental fetch instead of full 90-day window
        from_date = _get_last_sync_date("ramp")
        count = sync_ramp_transactions(org_only=org_only, from_date=from_date)
        _update_sync_state("ramp", "success", None, count, elapsed=time.monotonic() - t0)
    except ImportError:
        _update_sync_state("ramp", "error", "Ramp connector not available", 0)
    except Exception as e:
        _handle_sync_error("ramp", e, time.monotonic() - t0)


def sync_ramp_vendors():
    if not _is_enabled("ramp"):
        return
    t0 = time.monotonic()
    try:
        from connectors.ramp import sync_ramp_vendors as _sync_vendors

        count = _sync_vendors()
        _update_sync_state("ramp_vendors", "success", None, count, elapsed=time.monotonic() - t0)
    except ImportError:
        _update_sync_state("ramp_vendors", "error", "Ramp connector not available", 0)
    except Exception as e:
        _handle_sync_error("ramp_vendors", e, time.monotonic() - t0)


def sync_ramp_bills():
    if not _is_enabled("ramp"):
        return
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
    except Exception as e:
        _handle_sync_error("ramp_bills", e, time.monotonic() - t0)


def sync_lunchmoney():
    if not _is_enabled("lunchmoney"):
        return
    t0 = time.monotonic()
    try:
        from connectors.lunchmoney import sync_lunchmoney_transactions

        from_date = _get_last_sync_date("lunchmoney")
        count = sync_lunchmoney_transactions(from_date=from_date)
        _update_sync_state("lunchmoney", "success", None, count, elapsed=time.monotonic() - t0)
    except ImportError:
        _update_sync_state("lunchmoney", "error", "LunchMoney connector not available", 0)
    except Exception as e:
        _handle_sync_error("lunchmoney", e, time.monotonic() - t0)


def sync_news():
    if not _is_enabled("news"):
        return
    t0 = time.monotonic()
    try:
        from connectors.news import sync_news as _sync_news

        count = _sync_news()
        _update_sync_state("news", "success", None, count, elapsed=time.monotonic() - t0)
    except ImportError:
        _update_sync_state("news", "error", "News connector not available", 0)
    except Exception as e:
        _handle_sync_error("news", e, time.monotonic() - t0)


def sync_obsidian():
    if not _is_enabled("obsidian"):
        return
    t0 = time.monotonic()
    try:
        from connectors.obsidian import sync_obsidian_notes

        count = sync_obsidian_notes()
        _update_sync_state("obsidian", "success", None, count, elapsed=time.monotonic() - t0)
    except ImportError:
        _update_sync_state("obsidian", "error", "Obsidian connector not available", 0)
        return
    except Exception as e:
        _handle_sync_error("obsidian", e, time.monotonic() - t0)
        return
    # Rerank after sync so LLM priority is fresh
    try:
        from routers.obsidian_api import rerank_obsidian

        rerank_obsidian()
    except Exception:
        pass


def sync_drive():
    if not _is_enabled("google_drive"):
        return
    t0 = time.monotonic()
    try:
        from connectors.drive import sync_drive_files

        count = sync_drive_files()
        _update_sync_state("drive", "success", None, count, elapsed=time.monotonic() - t0)
    except ImportError:
        _update_sync_state("drive", "error", "Drive connector not available", 0)
    except Exception as e:
        _handle_sync_error("drive", e, time.monotonic() - t0)


def sync_sheets():
    if not _is_enabled("google_drive"):
        return
    t0 = time.monotonic()
    try:
        from connectors.sheets import sync_sheets_data

        count = sync_sheets_data()
        _update_sync_state("sheets", "success", None, count, elapsed=time.monotonic() - t0)
    except ImportError:
        _update_sync_state("sheets", "error", "Sheets connector not available", 0)
    except Exception as e:
        _handle_sync_error("sheets", e, time.monotonic() - t0)


def sync_docs():
    if not _is_enabled("google_drive"):
        return
    t0 = time.monotonic()
    try:
        from connectors.docs import sync_docs_data

        count = sync_docs_data()
        _update_sync_state("docs", "success", None, count, elapsed=time.monotonic() - t0)
    except ImportError:
        _update_sync_state("docs", "error", "Docs connector not available", 0)
    except Exception as e:
        _handle_sync_error("docs", e, time.monotonic() - t0)


def sync_onedrive():
    if not _is_enabled("microsoft_drive"):
        return
    t0 = time.monotonic()
    try:
        from connectors.onedrive import sync_onedrive_files

        count = sync_onedrive_files()
        _update_sync_state("onedrive", "success", None, count, elapsed=time.monotonic() - t0)
    except ImportError:
        _update_sync_state("onedrive", "error", "OneDrive connector not available", 0)
    except Exception as e:
        _handle_sync_error("onedrive", e, time.monotonic() - t0)


def _is_enabled(connector_id: str) -> bool:
    """Check if a connector is enabled in the registry."""
    try:
        from connectors.registry import is_enabled

        return is_enabled(connector_id)
    except Exception:
        return False


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
    global _sync_running, _sync_started_at
    _sync_cancel.clear()
    _sync_active_sources.clear()
    try:
        # Group 1: Local sources — fast, no network, run in parallel
        local_fns: list[tuple[str, callable]] = [("markdown", sync_meeting_files)]
        if _is_enabled("granola"):
            local_fns.append(("granola", sync_granola))
        if _is_enabled("obsidian"):
            local_fns.append(("obsidian", sync_obsidian))
        _run_group(local_fns, max_workers=3)

        if _sync_cancel.is_set():
            return

        # Group 2: External APIs — independent of each other, run in parallel
        external: list[tuple[str, callable]] = []
        # Email/Calendar: dispatch based on active provider
        from app_config import get_email_calendar_provider

        email_cal_provider = get_email_calendar_provider()
        if email_cal_provider == "microsoft" and _is_enabled("microsoft"):
            external.extend([("outlook_email", sync_outlook_email), ("outlook_calendar", sync_outlook_calendar)])
        elif _is_enabled("google"):
            external.extend([("gmail", sync_gmail), ("calendar", sync_calendar)])
        if _is_enabled("slack"):
            external.append(("slack", sync_slack))
        if _is_enabled("notion"):
            external.append(("notion", sync_notion))
            # Also sync Notion meeting notes if Notion is the meeting notes provider
            from app_config import get_profile

            if get_profile().get("meeting_notes_provider") == "notion":
                external.append(("notion_meetings", sync_notion_meetings))
        if _is_enabled("github"):
            external.append(("github", sync_github))
        if _is_enabled("ramp"):
            external.extend([("ramp", sync_ramp), ("ramp_vendors", sync_ramp_vendors)])
        if _is_enabled("lunchmoney"):
            external.append(("lunchmoney", sync_lunchmoney))
        if _is_enabled("google_drive"):
            external.append(("drive", sync_drive))
        if _is_enabled("microsoft_drive"):
            external.append(("onedrive", sync_onedrive))
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

        # Group 5: Person linking — connect synced data to people via knowledge graph
        from utils.person_linker import link_all

        _tracked("person_linking", link_all)

        # Rebuild FTS indexes after all data is refreshed
        from database import rebuild_fts

        rebuild_fts()

        if _sync_cancel.is_set():
            return

        # Group 6: Build compressed status context for Claude sessions
        from routers.status_context import build_status_context

        _tracked("status_context", build_status_context)

        # Group 7: Create memory entry from synced data
        from routers.memory import create_memory_entry

        _tracked("memory", lambda: create_memory_entry(trigger="sync"))

        if _sync_cancel.is_set():
            return

        # Group 8: Re-rank stale AI rankings in parallel
        from routers._ranking_cache import rerank_stale_sources

        _tracked("rerank", rerank_stale_sources)
    finally:
        _sync_active_sources.clear()
        _sync_running = False
        _sync_started_at = None


# ---------------------------------------------------------------------------
# Auto-sync scheduler
# ---------------------------------------------------------------------------


def _get_auto_sync_interval() -> int | None:
    """Read auto_sync_interval_seconds from profile config.

    Returns None if auto-sync is disabled (interval == 0).
    """
    from app_config import get_profile

    profile = get_profile()
    interval = profile.get("auto_sync_interval_seconds", DEFAULT_AUTO_SYNC_INTERVAL)
    if interval is None or interval <= 0:
        return None
    return max(60, int(interval))


def _should_skip_auto_sync(interval: int) -> bool:
    """Return True if the most recent sync is too recent to warrant another cycle."""
    try:
        with get_db_connection(readonly=True) as db:
            row = db.execute(
                "SELECT MAX(last_sync_at) as latest FROM sync_state WHERE last_sync_status IS NOT NULL"
            ).fetchone()
            if not row or not row["latest"]:
                return False
            latest = datetime.fromisoformat(row["latest"])
            elapsed = (datetime.now() - latest).total_seconds()
            return elapsed < (interval - 30)
    except Exception:
        return False


def _auto_sync_loop():
    """Background thread: wait for interval, then trigger full sync."""
    global _sync_running, _sync_started_at
    logger.info("Auto-sync thread started")
    while not _auto_sync_stop.is_set():
        interval = _get_auto_sync_interval()
        if interval is None:
            # Auto-sync disabled; sleep briefly and re-check
            _auto_sync_stop.wait(30)
            continue

        # Sleep for the interval (interruptible via _auto_sync_stop)
        if _auto_sync_stop.wait(interval):
            break  # Stop event was set

        # Re-read interval in case user changed it while sleeping
        interval = _get_auto_sync_interval()
        if interval is None:
            continue

        if _should_skip_auto_sync(interval):
            logger.debug("Auto-sync skipped — recent sync detected")
            continue

        with _sync_lock:
            _check_stale_sync_unlocked()
            if _sync_running:
                logger.debug("Auto-sync skipped — sync already in progress")
                continue
            _sync_running = True
            _sync_started_at = time.monotonic()

        logger.info("Auto-sync starting")
        try:
            _run_full_sync()
        except Exception:
            logger.exception("Auto-sync failed")
            _sync_running = False
    logger.info("Auto-sync thread stopped")


def start_auto_sync():
    """Start the background auto-sync thread. Called from app startup."""
    global _auto_sync_thread
    if _auto_sync_thread and _auto_sync_thread.is_alive():
        return
    _auto_sync_stop.clear()
    _auto_sync_thread = threading.Thread(target=_auto_sync_loop, daemon=True, name="auto-sync")
    _auto_sync_thread.start()


def stop_auto_sync():
    """Signal the auto-sync thread to stop. Called on app shutdown."""
    _auto_sync_stop.set()


@router.post("")
def trigger_sync(background_tasks: BackgroundTasks):
    global _sync_running, _sync_started_at
    with _sync_lock:
        _check_stale_sync_unlocked()
        if _sync_running:
            return {"status": "already_running"}
        _sync_running = True
        _sync_started_at = time.monotonic()
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
        "outlook_email": sync_outlook_email,
        "outlook_calendar": sync_outlook_calendar,
        "slack": sync_slack,
        "notion": sync_notion,
        "github": sync_github,
        "news": sync_news,
        "ramp_vendors": sync_ramp_vendors,
        "ramp_bills": sync_ramp_bills,
        "lunchmoney": sync_lunchmoney,
        "drive": sync_drive,
        "obsidian": sync_obsidian,
        "sheets": sync_sheets,
        "docs": sync_docs,
        "onedrive": sync_onedrive,
        "notion_meetings": sync_notion_meetings,
    }
    fn = sync_map.get(source)
    if not fn:
        return {"error": f"Unknown source: {source}"}
    background_tasks.add_task(fn)
    return {"status": "started", "source": source}


@router.get("/status")
def get_sync_status():
    with _sync_lock:
        _check_stale_sync_unlocked()
        running = _sync_running
        started_at = _sync_started_at
        active = sorted(_sync_active_sources)

    elapsed = round(time.monotonic() - started_at) if started_at is not None else None
    with get_db_connection(readonly=True) as db:
        rows = db.execute("SELECT * FROM sync_state").fetchall()
    interval = _get_auto_sync_interval()
    return {
        "running": running,
        "active_sources": active,
        "elapsed_seconds": elapsed,
        "sources": {row["source"]: dict(row) for row in rows},
        "auto_sync": {
            "enabled": interval is not None,
            "interval_seconds": interval or DEFAULT_AUTO_SYNC_INTERVAL,
        },
    }
