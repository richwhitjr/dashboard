"""Spending API — unified view across all spending connectors (Ramp, LunchMoney, etc.).

Replaces ramp_api.py as the canonical spending router. The old /api/ramp/* paths
are preserved as aliases by mounting this router twice in main.py.

Key endpoints:
  GET /api/spending/prioritized     — AI-ranked card transactions
  GET /api/spending/bills           — AP bills/invoices
  GET /api/spending/bills/summary   — Bills aggregated by vendor
  PATCH /api/spending/bills/{id}/project — Assign bill to project
  GET /api/spending/entries         — Unified view across ALL sources (cards + bills)
"""

import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel

from app_config import get_prompt_context
from database import get_db_connection, get_write_db
from routers._ranking_cache import compute_items_hash

logger = logging.getLogger(__name__)

router = APIRouter(tags=["spending"])


# ---------------------------------------------------------------------------
# AI ranking
# ---------------------------------------------------------------------------


def _build_spending_rank_prompt() -> str:
    ctx = get_prompt_context()
    return f"""\
You are a priority-ranking assistant {ctx}. You will receive a list of \
recent spending transactions. Your job is to rank them by importance for the user to review.

For each transaction, assign a priority_score from 1-10 where:
- 10: Requires immediate attention (policy violations, unusually large amounts, suspicious charges)
- 7-9: High priority (large expenses, new vendors, executive spending, software subscriptions)
- 4-6: Medium (recurring expenses, team dinners, standard office supplies)
- 1-3: Low (small routine charges, coffee, minor office supplies)

Consider:
1. Unusually large amounts for the category deserve higher scores
2. New or unfamiliar merchants deserve higher scores
3. Software and SaaS subscriptions are worth reviewing
4. Travel and entertainment expenses above $500 are notable
5. Expenses without receipts or memos are worth flagging
6. Recurring well-known charges (coffee, lunch) are lower priority

Return ONLY valid JSON — an array of objects with keys: id, priority_score, reason (one short sentence).
Order by priority_score descending. Return ALL transactions provided, scored."""


def _rank_spending_with_ai(transactions: list[dict]) -> list[dict]:
    """Rank spending transactions by priority using the configured AI provider."""
    from ai_client import generate

    now = datetime.now().strftime("%A, %B %d %Y, %I:%M %p")
    user_message = f"Current time: {now}\n\nTransactions to rank:\n{json.dumps(transactions, default=str)}"

    text = generate(system_prompt=_build_spending_rank_prompt(), user_message=user_message, json_mode=True)
    if not text:
        return []

    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def _dismissed_spending_ids(db) -> set[str]:
    rows = db.execute("SELECT item_id FROM dismissed_dashboard_items WHERE source = 'ramp'").fetchall()
    return {r["item_id"] for r in rows}


def _txn_within_days(txn_date: str | None, days: int) -> bool:
    if not txn_date:
        return False
    try:
        dt = datetime.fromisoformat(txn_date.replace("Z", "+00:00").replace("+00:00", ""))
        import datetime as dt_mod

        cutoff = datetime.utcnow().replace(hour=0, minute=0, second=0) - dt_mod.timedelta(days=days)
        return dt >= cutoff
    except (ValueError, TypeError):
        return True


def rerank_spending(days: int = 7) -> bool:
    """Rerank spending items — updates cache if data changed. Returns True if cache was updated."""
    from routers._ranking_cache import finish_reranking, start_reranking

    if not start_reranking("ramp"):
        return False
    try:
        return _do_rerank_spending(days)
    finally:
        finish_reranking("ramp")


# Keep old name as alias so _ranking_cache.py continues to work unchanged
rerank_ramp = rerank_spending


def _do_rerank_spending(days: int = 7) -> bool:
    cutoff = f"-{days} days"
    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            "SELECT DISTINCT t.id, t.amount, t.currency, t.merchant_name, t.category, t.transaction_date, "
            "t.cardholder_name, t.cardholder_email, t.memo, t.status, t.ramp_url, "
            "COALESCE(t.source, 'ramp') AS source "
            "FROM ramp_transactions t "
            "INNER JOIN people e ON lower(t.cardholder_name) = lower(e.name) "
            "WHERE datetime(t.transaction_date) >= datetime('now', ?) "
            "ORDER BY t.amount DESC LIMIT 200",
            (cutoff,),
        ).fetchall()

    if not rows:
        return False

    txns_for_llm = [
        {
            "id": r["id"],
            "amount": r["amount"],
            "currency": r["currency"],
            "merchant_name": r["merchant_name"],
            "category": r["category"],
            "transaction_date": r["transaction_date"],
            "cardholder_name": r["cardholder_name"],
            "memo": (r["memo"] or "")[:200],
            "source": r["source"],
        }
        for r in rows
    ]

    items_hash = compute_items_hash(txns_for_llm)
    with get_db_connection(readonly=True) as db:
        cached = db.execute("SELECT data_hash FROM cached_ramp_priorities ORDER BY id DESC LIMIT 1").fetchone()
        if cached and cached["data_hash"] == items_hash:
            return False

    logger.info("Spending rerank — calling AI (%d transactions)", len(txns_for_llm))
    try:
        ranked = _rank_spending_with_ai(txns_for_llm)
    except Exception:
        logger.error("Spending rerank failed", exc_info=True)
        return False

    if not ranked:
        return False

    txn_lookup = {r["id"]: dict(r) for r in rows}
    items = []
    for rank in ranked:
        txn_id = rank.get("id", "")
        txn = txn_lookup.get(txn_id)
        if not txn:
            continue
        items.append(
            {
                "id": txn["id"],
                "amount": txn["amount"],
                "currency": txn["currency"],
                "merchant_name": txn["merchant_name"],
                "category": txn["category"],
                "transaction_date": txn["transaction_date"],
                "cardholder_name": txn["cardholder_name"],
                "cardholder_email": txn["cardholder_email"],
                "memo": txn["memo"],
                "status": txn["status"],
                "ramp_url": txn["ramp_url"],
                "source": txn["source"],
                "priority_score": rank.get("priority_score", 5),
                "priority_reason": rank.get("reason", ""),
            }
        )

    items.sort(key=lambda x: x["priority_score"], reverse=True)
    items = items[:50]
    total = sum(i["amount"] for i in items)
    result = {"items": items, "total_amount": total}

    with get_write_db() as db:
        db.execute("DELETE FROM cached_ramp_priorities")
        db.execute(
            "INSERT INTO cached_ramp_priorities (data_json, data_hash) VALUES (?, ?)",
            (json.dumps(result, default=str), items_hash),
        )
        db.commit()

    logger.info("Spending rerank complete — %d items cached", len(items))
    return True


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/prioritized")
def get_prioritized_spending(
    refresh: bool = Query(False),
    days: int = Query(7, ge=1, le=730),
    org_only: bool = Query(True),
    background_tasks: BackgroundTasks = None,
):
    """Return spending transactions ranked by AI priority score."""
    from routers._ranking_cache import is_reranking

    with get_db_connection(readonly=True) as db:
        dismissed = _dismissed_spending_ids(db)

        cached = None
        if org_only:
            cached = db.execute(
                "SELECT data_json, generated_at FROM cached_ramp_priorities ORDER BY id DESC LIMIT 1"
            ).fetchone()

    if cached:
        data = json.loads(cached["data_json"])
        data["items"] = [
            item
            for item in data.get("items", [])
            if item["id"] not in dismissed and _txn_within_days(item.get("transaction_date"), days)
        ]
        data["total_amount"] = sum(item.get("amount", 0) for item in data["items"])

        if not refresh:
            return data

        if background_tasks and not is_reranking("ramp"):
            background_tasks.add_task(rerank_spending, days)
        data["stale"] = True
        return data

    # No cache — synchronous ranking
    cutoff = f"-{days} days"
    with get_db_connection(readonly=True) as db:
        if org_only:
            rows = db.execute(
                "SELECT DISTINCT t.id, t.amount, t.currency, t.merchant_name, t.category, t.transaction_date, "
                "t.cardholder_name, t.cardholder_email, t.memo, t.status, t.ramp_url, "
                "COALESCE(t.source, 'ramp') AS source "
                "FROM ramp_transactions t "
                "INNER JOIN people e ON lower(t.cardholder_name) = lower(e.name) "
                "WHERE datetime(t.transaction_date) >= datetime('now', ?) "
                "ORDER BY t.amount DESC LIMIT 200",
                (cutoff,),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT id, amount, currency, merchant_name, category, transaction_date, "
                "cardholder_name, cardholder_email, memo, status, ramp_url, "
                "COALESCE(source, 'ramp') AS source "
                "FROM ramp_transactions "
                "WHERE datetime(transaction_date) >= datetime('now', ?) "
                "ORDER BY amount DESC LIMIT 200",
                (cutoff,),
            ).fetchall()

    if not rows:
        return {
            "items": [],
            "total_amount": 0,
            "error": "No spending transactions synced yet — sync first or check credentials",
        }

    txns_for_llm = [
        {
            "id": r["id"],
            "amount": r["amount"],
            "currency": r["currency"],
            "merchant_name": r["merchant_name"],
            "category": r["category"],
            "transaction_date": r["transaction_date"],
            "cardholder_name": r["cardholder_name"],
            "memo": (r["memo"] or "")[:200],
            "source": r["source"],
        }
        for r in rows
    ]

    logger.info("Spending ranking — calling AI (%d transactions)", len(txns_for_llm))
    items_hash = compute_items_hash(txns_for_llm)

    try:
        ranked = _rank_spending_with_ai(txns_for_llm)
    except Exception as e:
        items = []
        for r in rows:
            d = dict(r)
            d["priority_score"] = min(10, max(1, int(d["amount"] / 100)))
            d["priority_reason"] = f"${d['amount']:.0f} charge"
            items.append(d)
        items = [i for i in items if i["id"] not in dismissed][:50]
        total = sum(i["amount"] for i in items)
        return {"items": items, "total_amount": total, "error": f"AI unavailable, sorted by amount: {e}"}

    if not ranked:
        items = []
        for r in rows:
            d = dict(r)
            d["priority_score"] = min(10, max(1, int(d["amount"] / 100)))
            d["priority_reason"] = f"${d['amount']:.0f} charge"
            items.append(d)
        items = [i for i in items if i["id"] not in dismissed][:50]
        total = sum(i["amount"] for i in items)
        return {"items": items, "total_amount": total}

    txn_lookup = {r["id"]: dict(r) for r in rows}
    items = []
    for rank in ranked:
        txn_id = rank.get("id", "")
        txn = txn_lookup.get(txn_id)
        if not txn:
            continue
        items.append(
            {
                "id": txn["id"],
                "amount": txn["amount"],
                "currency": txn["currency"],
                "merchant_name": txn["merchant_name"],
                "category": txn["category"],
                "transaction_date": txn["transaction_date"],
                "cardholder_name": txn["cardholder_name"],
                "cardholder_email": txn["cardholder_email"],
                "memo": txn["memo"],
                "status": txn["status"],
                "ramp_url": txn["ramp_url"],
                "source": txn["source"],
                "priority_score": rank.get("priority_score", 5),
                "priority_reason": rank.get("reason", ""),
            }
        )

    items.sort(key=lambda x: x["priority_score"], reverse=True)
    items = [i for i in items if i["id"] not in dismissed][:50]
    total = sum(i["amount"] for i in items)
    result = {"items": items, "total_amount": total}

    if org_only:
        with get_write_db() as db:
            db.execute("DELETE FROM cached_ramp_priorities")
            db.execute(
                "INSERT INTO cached_ramp_priorities (data_json, data_hash) VALUES (?, ?)",
                (json.dumps(result, default=str), items_hash),
            )
            db.commit()

    return result


@router.get("/bills")
def get_spending_bills(
    days: int = Query(30, ge=1, le=1095),
    status: Optional[str] = Query(None),
    project_id: Optional[int] = Query(None),
    vendor_id: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
):
    """Return bills/invoices ordered by due date descending."""
    conditions = ["datetime(b.issued_at) >= datetime('now', ?)"]
    params: list = [f"-{days} days"]

    if status:
        conditions.append("b.status = ?")
        params.append(status)
    if project_id is not None:
        conditions.append("b.project_id = ?")
        params.append(project_id)
    if vendor_id:
        conditions.append("b.vendor_id = ?")
        params.append(vendor_id)
    if source:
        conditions.append("COALESCE(b.source, 'ramp') = ?")
        params.append(source)

    where = " AND ".join(conditions)
    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            f"""SELECT b.id, b.vendor_id, b.vendor_name, b.amount, b.currency,
                   b.due_at, b.issued_at, b.paid_at, b.invoice_number, b.memo,
                   b.status, b.approval_status, b.payment_status, b.payment_method,
                   b.project_id, b.ramp_url,
                   COALESCE(b.source, 'ramp') AS source,
                   p.name as project_name
               FROM ramp_bills b
               LEFT JOIN projects p ON p.id = b.project_id
               WHERE {where}
               ORDER BY b.due_at DESC, b.issued_at DESC
               LIMIT 500""",
            params,
        ).fetchall()
    return {"bills": [dict(r) for r in rows], "total": len(rows)}


@router.get("/bills/summary")
def get_spending_bills_summary(days: int = Query(365, ge=1, le=1095)):
    """Return bills aggregated by vendor."""
    with get_db_connection(readonly=True) as db:
        rows = db.execute(
            """SELECT b.vendor_id, b.vendor_name,
                   COALESCE(b.source, 'ramp') AS source,
                   COUNT(*) as bill_count,
                   COALESCE(SUM(b.amount), 0) as total_amount,
                   COALESCE(SUM(CASE WHEN b.payment_status IN ('PAID','PAYMENT_COMPLETED')
                       THEN b.amount ELSE 0 END), 0) as paid_amount,
                   COALESCE(SUM(CASE WHEN b.payment_status NOT IN ('PAID','PAYMENT_COMPLETED')
                       THEN b.amount ELSE 0 END), 0) as pending_amount
               FROM ramp_bills b
               WHERE datetime(b.issued_at) >= datetime('now', ?)
               GROUP BY b.vendor_id, b.vendor_name, COALESCE(b.source, 'ramp')
               ORDER BY total_amount DESC""",
            (f"-{days} days",),
        ).fetchall()
    return {"vendors": [dict(r) for r in rows]}


class BillProjectAssignment(BaseModel):
    project_id: Optional[int] = None


@router.patch("/bills/{bill_id}/project")
def assign_spending_bill_project(bill_id: str, body: BillProjectAssignment):
    """Assign or unassign a bill to a project."""
    with get_write_db() as db:
        row = db.execute("SELECT id FROM ramp_bills WHERE id = ?", (bill_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Bill not found")
        db.execute("UPDATE ramp_bills SET project_id = ? WHERE id = ?", (body.project_id, bill_id))
        db.commit()
    return {"ok": True, "bill_id": bill_id, "project_id": body.project_id}


@router.get("/entries/vendors")
def get_spending_entry_vendors(
    q: Optional[str] = Query(None, description="Search vendor name"),
    limit: int = Query(30, ge=1, le=200),
):
    """Return distinct vendor names ordered by transaction frequency, for autocomplete."""
    if q:
        sql = """SELECT vendor_name, COUNT(*) as txn_count
                 FROM spending_entries
                 WHERE vendor_name IS NOT NULL AND lower(vendor_name) LIKE ?
                 GROUP BY vendor_name ORDER BY txn_count DESC LIMIT ?"""
        params: list = [f"%{q.lower()}%", limit]
    else:
        sql = """SELECT vendor_name, COUNT(*) as txn_count
                 FROM spending_entries
                 WHERE vendor_name IS NOT NULL
                 GROUP BY vendor_name ORDER BY txn_count DESC LIMIT ?"""
        params = [limit]
    with get_db_connection(readonly=True) as db:
        rows = db.execute(sql, params).fetchall()
    return {"vendors": [r["vendor_name"] for r in rows]}


@router.get("/entries/people")
def get_spending_entry_people(
    q: Optional[str] = Query(None, description="Search person name"),
    limit: int = Query(50, ge=1, le=200),
):
    """Return distinct person names (cardholders) ordered by transaction frequency, for autocomplete."""
    if q:
        sql = """SELECT person_name, COUNT(*) as txn_count
                 FROM spending_entries
                 WHERE person_name IS NOT NULL AND lower(person_name) LIKE ?
                 GROUP BY person_name ORDER BY txn_count DESC LIMIT ?"""
        params: list = [f"%{q.lower()}%", limit]
    else:
        sql = """SELECT person_name, COUNT(*) as txn_count
                 FROM spending_entries
                 WHERE person_name IS NOT NULL
                 GROUP BY person_name ORDER BY txn_count DESC LIMIT ?"""
        params = [limit]
    with get_db_connection(readonly=True) as db:
        rows = db.execute(sql, params).fetchall()
    return {"people": [r["person_name"] for r in rows]}


@router.get("/entries")
def get_spending_entries(
    days: int = Query(90, ge=1, le=1095),
    from_date: Optional[str] = Query(None, description="ISO date YYYY-MM-DD, inclusive"),
    to_date: Optional[str] = Query(None, description="ISO date YYYY-MM-DD, inclusive"),
    transaction_type: Optional[str] = Query(None, description="Comma-separated: card,bill,po"),
    direction: Optional[str] = Query(None, description="'in' or 'out'"),
    person: Optional[str] = Query(None, description="Comma-separated person names"),
    source: Optional[str] = Query(None, description="Comma-separated: ramp,lunchmoney"),
    project_id: Optional[int] = Query(None),
    q: Optional[str] = Query(None, description="Search vendor/merchant name"),
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """Unified view of all spending entries across sources and types.

    Queries the spending_entries VIEW which unions card transactions and AP bills.
    Designed for agent use and the unified All tab — returns enough context to
    summarize spend, identify trends, and join against people/projects.

    Example queries:
      /api/spending/entries?days=30&transaction_type=card
      /api/spending/entries?from_date=2026-01-01&to_date=2026-03-31
      /api/spending/entries?days=90&source=lunchmoney
      /api/spending/entries?q=aws&days=365
      /api/spending/entries?project_id=5
    """
    conditions: list[str] = []
    params: list = []

    if from_date or to_date:
        if from_date:
            conditions.append("entry_date >= ?")
            params.append(from_date)
        if to_date:
            conditions.append("entry_date <= ?")
            params.append(to_date)
    else:
        conditions.append("entry_date >= date('now', ?)")
        params.append(f"-{days} days")

    if transaction_type:
        types = [t.strip() for t in transaction_type.split(",") if t.strip()]
        if types:
            placeholders = ",".join("?" * len(types))
            conditions.append(f"transaction_type IN ({placeholders})")
            params.extend(types)

    if direction:
        conditions.append("direction = ?")
        params.append(direction)

    if source:
        sources = [s.strip() for s in source.split(",") if s.strip()]
        if sources:
            placeholders = ",".join("?" * len(sources))
            conditions.append(f"source IN ({placeholders})")
            params.extend(sources)

    if project_id is not None:
        conditions.append("project_id = ?")
        params.append(project_id)

    if person:
        people = [p.strip() for p in person.split(",") if p.strip()]
        if people:
            placeholders = ",".join("?" * len(people))
            conditions.append(f"person_name IN ({placeholders})")
            params.extend(people)

    if q:
        conditions.append("lower(vendor_name) LIKE ?")
        params.append(f"%{q.lower()}%")

    where = " AND ".join(conditions)

    with get_db_connection(readonly=True) as db:
        # Total count (for pagination metadata)
        count_row = db.execute(f"SELECT COUNT(*) as n FROM spending_entries WHERE {where}", params).fetchone()
        total_count = count_row["n"] if count_row else 0

        rows = db.execute(
            f"""SELECT entry_id, transaction_type, direction, amount, currency,
                   vendor_name, category, entry_date, due_date,
                   person_name, person_email, memo, status, payment_status,
                   invoice_number, project_id, external_url, source
               FROM spending_entries
               WHERE {where}
               ORDER BY entry_date DESC
               LIMIT ? OFFSET ?""",
            params + [limit, offset],
        ).fetchall()

    entries = [dict(r) for r in rows]
    total_out = sum(e["amount"] for e in entries if e["direction"] == "out")
    total_in = sum(e["amount"] for e in entries if e["direction"] == "in")

    return {
        "entries": entries,
        "total_count": total_count,
        "has_more": (offset + len(entries)) < total_count,
        "total_amount_out": total_out,
        "total_amount_in": total_in,
    }
