"""LunchMoney connector — personal finance transactions via LunchMoney API.

Syncs transactions from the LunchMoney API into ramp_transactions with
source='lunchmoney'. IDs are prefixed with 'lm_' to avoid collision with Ramp IDs.

API docs: https://lunchmoney.dev
Auth: Bearer token from my.lunchmoney.app/developers
"""

import logging
from datetime import datetime, timedelta

import httpx

logger = logging.getLogger(__name__)

LUNCHMONEY_BASE = "https://dev.lunchmoney.app"


def _get_token() -> str:
    from app_config import get_secret

    token = get_secret("LUNCHMONEY_TOKEN") or ""
    if not token:
        raise ValueError("LUNCHMONEY_TOKEN not configured — add it in Settings")
    return token


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_get_token()}",
        "Accept": "application/json",
    }


def check_lunchmoney_connection() -> dict:
    """Test LunchMoney connectivity by calling /v1/me."""
    result = {"connected": False, "error": None, "detail": None}
    try:
        resp = httpx.get(f"{LUNCHMONEY_BASE}/v1/me", headers=_headers(), timeout=10)
        resp.raise_for_status()
        data = resp.json()
        user_name = data.get("user_name") or data.get("email", "unknown")
        result["connected"] = True
        result["detail"] = f"Authenticated as {user_name}"
    except ValueError as e:
        result["error"] = str(e)
    except httpx.HTTPStatusError as e:
        result["error"] = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
    except Exception as e:
        result["error"] = str(e)
    return result


def sync_lunchmoney_transactions(from_date: str | None = None) -> int:
    """Fetch transactions from LunchMoney and upsert into ramp_transactions.

    Args:
        from_date: ISO date string to fetch from (inclusive). Defaults to 90 days ago.

    Returns:
        Number of transactions upserted.
    """
    from database import get_write_db

    # Determine date range
    if from_date:
        # Use provided date, truncate to date portion
        start_date = from_date[:10]
    else:
        start_date = (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d")
    end_date = datetime.utcnow().strftime("%Y-%m-%d")

    logger.info("LunchMoney sync: fetching transactions from %s to %s", start_date, end_date)

    # Fetch all pages
    all_transactions = []
    try:
        resp = httpx.get(
            f"{LUNCHMONEY_BASE}/v1/transactions",
            headers=_headers(),
            params={
                "start_date": start_date,
                "end_date": end_date,
                "limit": 1000,
                "debit_as_negative": False,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        all_transactions = data.get("transactions", [])
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"LunchMoney API error: HTTP {e.response.status_code}") from e

    if not all_transactions:
        logger.info("LunchMoney sync: no transactions returned")
        return 0

    # Map to ramp_transactions schema
    rows = []
    for txn in all_transactions:
        txn_id = txn.get("id")
        if not txn_id:
            continue

        amount = abs(float(txn.get("amount", 0) or 0))
        currency = (txn.get("currency") or "USD").upper()
        merchant_name = txn.get("payee") or txn.get("original_name") or ""
        category = txn.get("category_name") or ""
        transaction_date = txn.get("date") or ""
        memo = txn.get("notes") or ""
        status = txn.get("status") or ""

        rows.append(
            (
                f"lm_{txn_id}",  # id — prefixed to avoid collision with Ramp IDs
                amount,
                currency,
                merchant_name,
                category,
                None,  # category_code — not available in LunchMoney
                transaction_date,
                None,  # cardholder_name — not applicable
                None,  # cardholder_email — not applicable
                None,  # employee_id — will be linked later by person_linker
                memo,
                None,  # receipt_urls — not available
                status,
                None,  # ramp_url — LunchMoney has no per-transaction deep link
                "lunchmoney",  # source
            )
        )

    if not rows:
        return 0

    with get_write_db() as db:
        db.executemany(
            """INSERT INTO ramp_transactions
               (id, amount, currency, merchant_name, category, category_code,
                transaction_date, cardholder_name, cardholder_email, employee_id,
                memo, receipt_urls, status, ramp_url, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 amount=excluded.amount,
                 currency=excluded.currency,
                 merchant_name=excluded.merchant_name,
                 category=excluded.category,
                 transaction_date=excluded.transaction_date,
                 memo=excluded.memo,
                 status=excluded.status,
                 source=excluded.source""",
            rows,
        )
        db.commit()

    logger.info("LunchMoney sync: upserted %d transactions", len(rows))
    return len(rows)
