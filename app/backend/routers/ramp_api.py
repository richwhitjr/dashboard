"""Ramp expenses API — prioritized transaction list with Gemini ranking."""

import json
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from database import get_db

router = APIRouter(prefix="/api/ramp", tags=["ramp"])


_RAMP_RANK_PROMPT = """\
You are a priority-ranking assistant for Rich, the CTO of Osmo. You will receive a list of \
recent company expenses from Ramp. Your job is to rank them by importance for Rich to review.

For each expense, assign a priority_score from 1-10 where:
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
Order by priority_score descending. Return ALL expenses provided, scored."""


def _rank_ramp_with_gemini(transactions: list[dict]) -> list[dict]:
    """Call Gemini to rank Ramp transactions by priority."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return []

    from google import genai

    client = genai.Client(api_key=api_key)
    now = datetime.now().strftime("%A, %B %d %Y, %I:%M %p")
    user_message = f"Current time: {now}\n\nRamp expenses to rank:\n{json.dumps(transactions, default=str)}"

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=user_message,
        config={
            "system_instruction": _RAMP_RANK_PROMPT,
            "temperature": 0.2,
            "response_mime_type": "application/json",
        },
    )

    try:
        items = json.loads(response.text)
        if isinstance(items, list):
            return items
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def _dismissed_ramp_ids(db) -> set[str]:
    rows = db.execute("SELECT item_id FROM dismissed_dashboard_items WHERE source = 'ramp'").fetchall()
    return {r["item_id"] for r in rows}


def _txn_within_days(txn_date: str | None, days: int) -> bool:
    """Check if a transaction date string is within N days of now."""
    if not txn_date:
        return False
    try:
        dt = datetime.fromisoformat(txn_date.replace("Z", "+00:00").replace("+00:00", ""))
        cutoff = datetime.utcnow().replace(hour=0, minute=0, second=0) - __import__("datetime").timedelta(days=days)
        return dt >= cutoff
    except (ValueError, TypeError):
        return True  # If we can't parse, include it


@router.get("/prioritized")
def get_prioritized_ramp(
    refresh: bool = Query(False),
    days: int = Query(7, ge=1, le=730),
    org_only: bool = Query(True),
):
    """Return Ramp transactions ranked by Gemini priority score."""
    db = get_db()
    dismissed = _dismissed_ramp_ids(db)
    cutoff = f"-{days} days"

    # Check cache first (only for org_only=True, the default view)
    if not refresh and org_only:
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
            db.close()
            return data

    # Fetch recent transactions from DB
    if org_only:
        rows = db.execute(
            "SELECT DISTINCT t.id, t.amount, t.currency, t.merchant_name, t.category, t.transaction_date, "
            "t.cardholder_name, t.cardholder_email, t.memo, t.status, t.ramp_url "
            "FROM ramp_transactions t "
            "INNER JOIN employees e ON lower(t.cardholder_name) = lower(e.name) "
            "WHERE datetime(t.transaction_date) >= datetime('now', ?) "
            "ORDER BY t.amount DESC LIMIT 200",
            (cutoff,),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT id, amount, currency, merchant_name, category, transaction_date, "
            "cardholder_name, cardholder_email, memo, status, ramp_url "
            "FROM ramp_transactions "
            "WHERE datetime(transaction_date) >= datetime('now', ?) "
            "ORDER BY amount DESC LIMIT 200",
            (cutoff,),
        ).fetchall()

    if not rows:
        db.close()
        return {
            "items": [],
            "total_amount": 0,
            "error": "No Ramp transactions synced yet — sync first or check credentials",
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
        }
        for r in rows
    ]

    try:
        ranked = _rank_ramp_with_gemini(txns_for_llm)
    except Exception as e:
        # Fallback: sort by amount descending with default scores
        items = []
        for r in rows:
            d = dict(r)
            d["priority_score"] = min(10, max(1, int(d["amount"] / 100)))
            d["priority_reason"] = f"${d['amount']:.0f} charge"
            items.append(d)
        items = [i for i in items if i["id"] not in dismissed][:50]
        total = sum(i["amount"] for i in items)
        db.close()
        return {"items": items, "total_amount": total, "error": f"Gemini unavailable, sorted by amount: {e}"}

    # If Gemini returned nothing, fallback to amount sort
    if not ranked:
        items = []
        for r in rows:
            d = dict(r)
            d["priority_score"] = min(10, max(1, int(d["amount"] / 100)))
            d["priority_reason"] = f"${d['amount']:.0f} charge"
            items.append(d)
        items = [i for i in items if i["id"] not in dismissed][:50]
        total = sum(i["amount"] for i in items)
        db.close()
        return {"items": items, "total_amount": total}

    # Build lookup of full transaction data
    txn_lookup = {r["id"]: dict(r) for r in rows}

    # Merge rankings with full transaction data
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
                "priority_score": rank.get("priority_score", 5),
                "priority_reason": rank.get("reason", ""),
            }
        )

    # Sort by score desc, filter dismissed, take top 50
    items.sort(key=lambda x: x["priority_score"], reverse=True)
    items = [i for i in items if i["id"] not in dismissed][:50]
    total = sum(i["amount"] for i in items)

    result = {"items": items, "total_amount": total}

    # Cache result (only for the default org_only view)
    if org_only:
        db.execute("DELETE FROM cached_ramp_priorities")
        db.execute(
            "INSERT INTO cached_ramp_priorities (data_json) VALUES (?)",
            (json.dumps(result, default=str),),
        )
        db.commit()
    db.close()

    return result


@router.get("/bills")
def get_ramp_bills(
    days: int = Query(30, ge=1, le=1095),
    status: Optional[str] = Query(None),
    project_id: Optional[int] = Query(None),
    vendor_id: Optional[str] = Query(None),
):
    """Return Ramp bills ordered by due date descending."""
    db = get_db()
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

    where = " AND ".join(conditions)
    rows = db.execute(
        f"""SELECT b.id, b.vendor_id, b.vendor_name, b.amount, b.currency,
               b.due_at, b.issued_at, b.paid_at, b.invoice_number, b.memo,
               b.status, b.approval_status, b.payment_status, b.payment_method,
               b.project_id, b.ramp_url,
               p.name as project_name
           FROM ramp_bills b
           LEFT JOIN projects p ON p.id = b.project_id
           WHERE {where}
           ORDER BY b.due_at DESC, b.issued_at DESC
           LIMIT 500""",
        params,
    ).fetchall()
    db.close()
    return {"bills": [dict(r) for r in rows], "total": len(rows)}


@router.get("/bills/summary")
def get_ramp_bills_summary(days: int = Query(365, ge=1, le=1095)):
    """Return bills aggregated by vendor."""
    db = get_db()
    rows = db.execute(
        """SELECT b.vendor_id, b.vendor_name,
               COUNT(*) as bill_count,
               COALESCE(SUM(b.amount), 0) as total_amount,
               COALESCE(SUM(CASE WHEN b.payment_status IN ('PAID','PAYMENT_COMPLETED')
                   THEN b.amount ELSE 0 END), 0) as paid_amount,
               COALESCE(SUM(CASE WHEN b.payment_status NOT IN ('PAID','PAYMENT_COMPLETED')
                   THEN b.amount ELSE 0 END), 0) as pending_amount
           FROM ramp_bills b
           WHERE datetime(b.issued_at) >= datetime('now', ?)
           GROUP BY b.vendor_id, b.vendor_name
           ORDER BY total_amount DESC""",
        (f"-{days} days",),
    ).fetchall()
    db.close()
    return {"vendors": [dict(r) for r in rows]}


class BillProjectAssignment(BaseModel):
    project_id: Optional[int] = None


@router.patch("/bills/{bill_id}/project")
def assign_bill_project(bill_id: str, body: BillProjectAssignment):
    """Assign or unassign a bill to a project."""
    db = get_db()
    row = db.execute("SELECT id FROM ramp_bills WHERE id = ?", (bill_id,)).fetchone()
    if not row:
        db.close()
        raise HTTPException(status_code=404, detail="Bill not found")
    db.execute("UPDATE ramp_bills SET project_id = ? WHERE id = ?", (body.project_id, bill_id))
    db.commit()
    db.close()
    return {"ok": True, "bill_id": bill_id, "project_id": body.project_id}
