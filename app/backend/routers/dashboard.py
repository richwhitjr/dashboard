from collections import OrderedDict

from fastapi import APIRouter, Query

from database import get_db_connection, get_write_db

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _dismissed_ids(db, source: str) -> set[str]:
    """Return set of dismissed item IDs for a given source."""
    rows = db.execute("SELECT item_id FROM dismissed_dashboard_items WHERE source = ?", (source,)).fetchall()
    return {r["item_id"] for r in rows}


def _group_by_thread(emails: list[dict]) -> list[dict]:
    """Group emails by thread_id, returning one item per thread (latest first)."""
    threads: OrderedDict[str, dict] = OrderedDict()
    for email in emails:
        tid = email.get("thread_id") or email["id"]
        if tid not in threads:
            threads[tid] = {
                "id": tid,
                "thread_id": tid,
                "subject": email["subject"],
                "snippet": email["snippet"],
                "from_name": email.get("from_name", ""),
                "from_email": email.get("from_email", ""),
                "date": email["date"],
                "is_unread": bool(email.get("is_unread")),
                "message_count": 1,
            }
        else:
            threads[tid]["message_count"] += 1
            if email.get("is_unread"):
                threads[tid]["is_unread"] = True
    return list(threads.values())


@router.get("")
def get_dashboard(days: int = Query(7, ge=1, le=90)):
    with get_db_connection(readonly=True) as db:
        dismissed_slack = _dismissed_ids(db, "slack")
        dismissed_notion = _dismissed_ids(db, "notion")
        dismissed_github = _dismissed_ids(db, "github")
        dismissed_email = _dismissed_ids(db, "email")

        cutoff = f"-{days} days"

        calendar_today = [
            dict(r)
            for r in db.execute(
                "SELECT * FROM calendar_events WHERE date(start_time) = date('now') ORDER BY start_time"
            ).fetchall()
        ]

        raw_emails = [
            dict(r)
            for r in db.execute(
                "SELECT * FROM emails "
                "WHERE labels_json NOT LIKE '%CATEGORY_PROMOTIONS%' "
                "AND labels_json NOT LIKE '%CATEGORY_SOCIAL%' "
                "AND labels_json NOT LIKE '%CATEGORY_UPDATES%' "
                "AND labels_json NOT LIKE '%CATEGORY_FORUMS%' "
                "AND synced_at >= datetime('now', ?) "
                "ORDER BY date DESC LIMIT 60",
                (cutoff,),
            ).fetchall()
        ]
        emails_recent = [t for t in _group_by_thread(raw_emails) if t["id"] not in dismissed_email][:15]

        slack_recent = [
            dict(r)
            for r in db.execute(
                "SELECT * FROM slack_messages "
                "WHERE datetime(ts, 'unixepoch') >= datetime('now', ?) "
                "ORDER BY ts DESC LIMIT 50",
                (cutoff,),
            ).fetchall()
            if r["id"] not in dismissed_slack
        ][:15]

        meetings_upcoming = [
            dict(r)
            for r in db.execute(
                "SELECT * FROM calendar_events WHERE start_time > datetime('now') ORDER BY start_time LIMIT 10"
            ).fetchall()
        ]

        notion_recent = [
            dict(r)
            for r in db.execute(
                "SELECT *, "
                "(relevance_score + CASE "
                "  WHEN last_edited_time > datetime('now', '-1 day') THEN 0.15 "
                "  WHEN last_edited_time > datetime('now', '-3 days') THEN 0.10 "
                "  WHEN last_edited_time > datetime('now', '-7 days') THEN 0.05 "
                "  ELSE 0 END) AS combined_score "
                "FROM notion_pages "
                "WHERE last_edited_time >= datetime('now', ?) "
                "ORDER BY combined_score DESC, last_edited_time DESC LIMIT 30",
                (cutoff,),
            ).fetchall()
            if r["id"] not in dismissed_notion
        ][:10]

        github_review_requests = [
            dict(r)
            for r in db.execute(
                "SELECT number, title, author, html_url, created_at, updated_at, draft, labels_json "
                "FROM github_pull_requests WHERE review_requested = 1 AND state = 'open' "
                "AND updated_at >= datetime('now', ?) "
                "ORDER BY updated_at DESC LIMIT 30",
                (cutoff,),
            ).fetchall()
            if str(r["number"]) not in dismissed_github
        ][:10]

        notes_open = db.execute("SELECT COUNT(*) as count FROM notes WHERE status = 'open'").fetchone()["count"]

        sync_status = {row["source"]: dict(row) for row in db.execute("SELECT * FROM sync_state").fetchall()}

    return {
        "calendar_today": calendar_today,
        "emails_recent": emails_recent,
        "slack_recent": slack_recent,
        "meetings_upcoming": meetings_upcoming,
        "notion_recent": notion_recent,
        "github_review_requests": github_review_requests,
        "notes_open_count": notes_open,
        "sync_status": sync_status,
        "days": days,
    }


@router.post("/dismiss")
def dismiss_dashboard_item(body: dict):
    source = body.get("source", "").strip()
    item_id = body.get("item_id", "").strip()
    if not source or not item_id:
        return {"error": "source and item_id are required"}
    with get_write_db() as db:
        db.execute(
            "INSERT OR REPLACE INTO dismissed_dashboard_items (source, item_id) VALUES (?, ?)",
            (source, item_id),
        )
        db.commit()
    return {"ok": True}


@router.post("/undismiss")
def undismiss_dashboard_item(body: dict):
    source = body.get("source", "").strip()
    item_id = body.get("item_id", "").strip()
    if not source or not item_id:
        return {"error": "source and item_id are required"}
    with get_write_db() as db:
        db.execute(
            "DELETE FROM dismissed_dashboard_items WHERE source = ? AND item_id = ?",
            (source, item_id),
        )
        db.commit()
    return {"ok": True}
