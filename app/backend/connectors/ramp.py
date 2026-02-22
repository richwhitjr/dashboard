"""Ramp expense connector — OAuth 2.0 Client Credentials, sync transactions to SQLite."""

import json
import logging
import time
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx

from config import RAMP_TRANSACTION_SYNC_DAYS
from database import batch_upsert, get_db_connection, get_write_db

logger = logging.getLogger(__name__)

RAMP_BASE_URL = "https://api.ramp.com"
TOKEN_URL = f"{RAMP_BASE_URL}/developer/v1/token"
TRANSACTIONS_URL = f"{RAMP_BASE_URL}/developer/v1/transactions"
VENDORS_URL = f"{RAMP_BASE_URL}/developer/v1/accounting/vendors"
BILLS_URL = f"{RAMP_BASE_URL}/developer/v1/bills"

# In-memory token cache (reset expiry so new scope is fetched on next call)
_cached_token: str | None = None
_token_expires_at: float = 0  # set to 0 to force re-auth with updated scopes


def _get_ramp_credentials() -> tuple[str, str]:
    from app_config import get_secret

    client_id = get_secret("RAMP_CLIENT_ID") or ""
    client_secret = get_secret("RAMP_CLIENT_SECRET") or ""
    if not client_id or not client_secret:
        raise ValueError("RAMP_CLIENT_ID and RAMP_CLIENT_SECRET not configured. Add them in Settings.")
    return client_id, client_secret


def _get_access_token() -> str:
    """Get a valid access token, refreshing if needed."""
    global _cached_token, _token_expires_at

    if _cached_token and time.time() < _token_expires_at:
        return _cached_token

    client_id, client_secret = _get_ramp_credentials()
    resp = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "scope": "transactions:read bills:read accounting:read",
        },
        auth=(client_id, client_secret),
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    _cached_token = data["access_token"]
    # Ramp tokens last 10 days; refresh after 9
    _token_expires_at = time.time() + 9 * 86400
    return _cached_token


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_get_access_token()}",
        "Accept": "application/json",
    }


def _get_org_names() -> set[str]:
    """Return lowercase full names of all employees in the DB."""
    with get_db_connection(readonly=True) as db:
        rows = db.execute("SELECT name FROM employees WHERE name IS NOT NULL AND name != ''").fetchall()
    return {row["name"].lower() for row in rows}


def sync_ramp_transactions(org_only: bool = False, from_date: str | None = None) -> int:
    """Fetch transactions from Ramp and store in SQLite. Returns count.

    Args:
        org_only: If True, only store transactions from employees in the org DB.
        from_date: ISO date string (e.g. '2024-01-01') to pull from. Defaults to
                   RAMP_TRANSACTION_SYNC_DAYS ago.
    """
    if from_date:
        cutoff_iso = f"{from_date}T00:00:00Z"
    else:
        cutoff = datetime.utcnow() - timedelta(days=RAMP_TRANSACTION_SYNC_DAYS)
        cutoff_iso = cutoff.strftime("%Y-%m-%dT00:00:00Z")

    org_names = _get_org_names() if org_only else None
    logger.info("Ramp sync: org_only=%s, org members=%d", org_only, len(org_names) if org_names else -1)

    # Phase 1: Fetch all transactions from API (no DB connection held)
    all_transactions = []
    params: dict = {
        "from_date": cutoff_iso,
        "page_size": 100,
        "order_by_date_desc": "true",
    }

    url = TRANSACTIONS_URL
    while True:
        resp = httpx.get(url, headers=_headers(), params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        transactions = data.get("data", data.get("results", []))
        if isinstance(transactions, list):
            all_transactions.extend(transactions)
        else:
            break

        page = data.get("page", {})
        next_url = page.get("next")
        if not next_url:
            break
        parsed = urlparse(next_url)
        qs = parse_qs(parsed.query)
        start_cursor = qs.get("start", [None])[0]
        if not start_cursor:
            break
        url = TRANSACTIONS_URL
        params = {
            "from_date": cutoff_iso,
            "page_size": 100,
            "order_by_date_desc": "true",
            "start": start_cursor,
        }

    # Filter to org members if requested
    if org_names is not None:
        before = len(all_transactions)
        ch = None
        all_transactions = [
            t
            for t in all_transactions
            if (
                (ch := t.get("card_holder") or {})
                and f"{ch.get('first_name', '')} {ch.get('last_name', '')}".strip().lower() in org_names
            )
        ]
        logger.info("Ramp org filter: %d → %d transactions", before, len(all_transactions))

    # Phase 2: Build rows
    rows = []
    for txn in all_transactions:
        txn_id = txn.get("id", "")
        if not txn_id:
            continue

        amount = txn.get("amount", 0)
        if isinstance(amount, dict):
            amount = amount.get("amount", 0)
        amount = abs(float(amount)) if amount else 0

        currency = txn.get("currency_code", txn.get("currency", "USD"))
        if isinstance(txn.get("amount"), dict):
            currency = txn["amount"].get("currency_code", currency)

        merchant = (
            txn.get("merchant_name") or txn.get("merchant_descriptor") or txn.get("merchant", {}).get("name", "Unknown")
        )

        category = txn.get("sk_category_name", txn.get("category", ""))
        category_code = txn.get("sk_category_id", txn.get("category_code"))

        txn_date = txn.get("user_transaction_time") or txn.get("transaction_date") or txn.get("created_at", "")

        cardholder = txn.get("card_holder", {})
        if isinstance(cardholder, dict):
            ch_name = f"{cardholder.get('first_name', '')} {cardholder.get('last_name', '')}".strip() or cardholder.get(
                "name", ""
            )
            ch_email = cardholder.get("email", "")
        else:
            ch_name = ""
            ch_email = ""

        memo = txn.get("memo", txn.get("merchant_category_code_description", ""))
        receipts = txn.get("receipts", [])
        receipt_urls = (
            ",".join(r.get("receipt_url", "") for r in receipts if isinstance(r, dict))
            if isinstance(receipts, list)
            else ""
        )
        status = txn.get("state", txn.get("status", ""))

        rows.append(
            (
                txn_id,
                amount,
                currency,
                merchant,
                category,
                category_code,
                txn_date,
                ch_name,
                ch_email,
                memo,
                receipt_urls,
                status,
                None,
                datetime.utcnow().isoformat(),
            )
        )

    # Phase 3: Write in batches
    with get_write_db() as db:
        batch_upsert(
            db,
            """INSERT OR REPLACE INTO ramp_transactions
               (id, amount, currency, merchant_name, category, category_code,
                transaction_date, cardholder_name, cardholder_email, memo,
                receipt_urls, status, ramp_url, synced_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )

    return len(rows)


def sync_ramp_vendors() -> int:
    """Fetch vendors from Ramp accounting/vendors and store in ramp_vendors. Returns count."""
    # Phase 1: Fetch all vendors from API
    all_vendors = []
    params: dict = {"page_size": 100}
    url = VENDORS_URL
    while True:
        resp = httpx.get(url, headers=_headers(), params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        vendors = data.get("data", data.get("results", []))
        if isinstance(vendors, list):
            all_vendors.extend(vendors)
        else:
            break

        page = data.get("page", {})
        next_url = page.get("next")
        if not next_url:
            break
        parsed = urlparse(next_url)
        qs = parse_qs(parsed.query)
        start_cursor = qs.get("start", [None])[0]
        if not start_cursor:
            break
        params = {"page_size": 100, "start": start_cursor}

    # Phase 2: Build rows
    rows = []
    for v in all_vendors:
        vid = v.get("id", "")
        if not vid:
            continue
        rows.append((vid, v.get("name", ""), 1 if v.get("is_active", True) else 0, datetime.utcnow().isoformat()))

    # Phase 3: Write in batches
    with get_write_db() as db:
        batch_upsert(
            db,
            """INSERT OR REPLACE INTO ramp_vendors (id, name, is_active, synced_at)
               VALUES (?, ?, ?, ?)""",
            rows,
        )

    logger.info("Ramp vendors synced: %d", len(rows))
    return len(rows)


def sync_ramp_bills(from_date: str | None = None, wipe: bool = True) -> int:
    """Fetch bills from Ramp and store in ramp_bills. Returns count.

    Args:
        from_date: ISO date string (e.g. '2024-01-01') to pull from. Defaults to
                   RAMP_TRANSACTION_SYNC_DAYS ago.
        wipe: If True, delete all existing bills before inserting (full refresh).
              If False, upsert only (useful for historical backfill).
    """
    if from_date:
        cutoff_iso = f"{from_date}T00:00:00Z"
    else:
        cutoff = datetime.utcnow() - timedelta(days=RAMP_TRANSACTION_SYNC_DAYS)
        cutoff_iso = cutoff.strftime("%Y-%m-%dT00:00:00Z")

    # Phase 1: Fetch all bills from API
    all_bills = []
    params: dict = {"from_created_at": cutoff_iso, "page_size": 100}
    url = BILLS_URL
    while True:
        resp = httpx.get(url, headers=_headers(), params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        bills = data.get("data", data.get("results", []))
        if isinstance(bills, list):
            all_bills.extend(bills)
        else:
            break

        page = data.get("page", {})
        next_url = page.get("next")
        if not next_url:
            break
        parsed = urlparse(next_url)
        qs = parse_qs(parsed.query)
        start_cursor = qs.get("start", [None])[0]
        if not start_cursor:
            break
        params = {"from_created_at": cutoff_iso, "page_size": 100, "start": start_cursor}

    # Phase 2: Read vendor names and build rows
    with get_db_connection(readonly=True) as db:
        vendor_rows = db.execute("SELECT id, name FROM ramp_vendors").fetchall()
    vendor_names = {r["id"]: r["name"] for r in vendor_rows}

    rows = []
    for bill in all_bills:
        bill_id = bill.get("id", "")
        if not bill_id:
            continue

        vendor_id = bill.get("vendor", {}).get("id", "") or bill.get("vendor_id", "")
        vendor_name = bill.get("vendor", {}).get("name", "") or vendor_names.get(vendor_id, "")

        amount_obj = bill.get("amount", {})
        if isinstance(amount_obj, dict):
            amount = float(amount_obj.get("amount", 0) or 0)
            currency = amount_obj.get("currency_code", "USD")
        else:
            amount = float(amount_obj or 0)
            currency = bill.get("currency", "USD")

        line_items = bill.get("line_items", bill.get("line_items_data", []))

        rows.append(
            (
                bill_id,
                vendor_id,
                vendor_name,
                amount,
                currency,
                bill.get("due_at") or bill.get("due_date"),
                bill.get("issued_at") or bill.get("invoice_date"),
                bill.get("paid_at"),
                bill.get("invoice_number") or bill.get("invoice_id"),
                bill.get("memo", ""),
                bill.get("status") or bill.get("status_summary", ""),
                bill.get("approval_status", ""),
                bill.get("payment_status", ""),
                bill.get("payment_method", ""),
                json.dumps(line_items) if line_items else None,
                bill.get("ramp_url") or bill.get("canonical_url"),
                datetime.utcnow().isoformat(),
            )
        )

    # Phase 3: Write — wipe first if requested, then batch insert
    with get_write_db() as db:
        if wipe:
            db.execute("DELETE FROM ramp_bills")
            db.commit()
        batch_upsert(
            db,
            """INSERT OR REPLACE INTO ramp_bills
               (id, vendor_id, vendor_name, amount, currency, due_at, issued_at, paid_at,
                invoice_number, memo, status, approval_status, payment_status, payment_method,
                line_items_json, ramp_url, synced_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )

    logger.info("Ramp bills synced: %d (from %s, wipe=%s)", len(rows), cutoff_iso, wipe)
    return len(rows)


def seed_projects_from_vendors() -> int:
    """Create stub projects for vendors that have bills but no project yet. Idempotent."""
    with get_write_db() as db:
        rows = db.execute(
            """SELECT DISTINCT b.vendor_id, b.vendor_name
               FROM ramp_bills b
               WHERE b.vendor_id != '' AND b.vendor_id IS NOT NULL
                 AND NOT EXISTS (
                   SELECT 1 FROM projects p WHERE p.vendor_id = b.vendor_id
                 )"""
        ).fetchall()

        count = 0
        for row in rows:
            vendor_id = row["vendor_id"]
            vendor_name = row["vendor_name"] or vendor_id
            db.execute(
                """INSERT OR IGNORE INTO projects (name, vendor_id, budget_amount, status)
                   VALUES (?, ?, 0, 'active')""",
                (vendor_name, vendor_id),
            )
            count += 1

        db.commit()

    logger.info("Seeded %d projects from Ramp vendors", count)
    return count


def check_ramp_connection() -> dict:
    """Test Ramp API connectivity. Returns status dict."""
    result = {"configured": False, "connected": False, "error": None, "detail": None}
    try:
        client_id, client_secret = _get_ramp_credentials()
        result["configured"] = True
        token = _get_access_token()
        if token:
            result["connected"] = True
            result["detail"] = "Authenticated via OAuth client credentials"
    except ValueError as e:
        result["detail"] = str(e)
    except Exception as e:
        result["configured"] = True
        result["error"] = str(e)
    return result
