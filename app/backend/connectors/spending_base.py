"""Shared utilities for spending connectors.

## Connector Interface Convention

Spending connectors write rows into:
  - `ramp_transactions` (card charges, personal transactions) with `source` = connector ID
  - `ramp_bills` (AP invoices, POs, bills payable) with `source` = connector ID (optional)

The `spending_entries` SQLite VIEW automatically merges both tables into a unified
queryable structure with `transaction_type` ('card' | 'bill') and `direction` ('out' | 'in').

### Expected connector module exports:

    def sync_{connector}_transactions(from_date: str | None = None) -> int:
        '''Fetch and upsert transactions. Returns count of rows synced.'''

    def check_{connector}_connection() -> dict:
        '''Test connectivity. Returns {"connected": bool, "error": str | None, "detail": str | None}'''

### ID convention to avoid collisions:
  - Ramp:       raw Ramp UUID                (e.g. "abc-123")
  - LunchMoney: "lm_{id}"                    (e.g. "lm_98765")
  - NetSuite:   "ns_{id}"                    (e.g. "ns_TXN-001")
"""

from typing import TypedDict


class SpendingTransactionRow(TypedDict, total=False):
    """Schema for a row in ramp_transactions. All spending connectors use this shape."""

    id: str  # Required — unique, prefixed to avoid cross-source collision
    amount: float  # Required — absolute value (always positive)
    currency: str  # Default 'USD'
    merchant_name: str  # Payee / vendor name
    category: str  # Human-readable category label
    category_code: int | None  # Numeric code (Ramp-specific, NULL for others)
    transaction_date: str  # ISO date string (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
    cardholder_name: str | None  # Person who made the charge (NULL for non-card sources)
    cardholder_email: str | None  # Email of cardholder (NULL for non-card sources)
    employee_id: str | None  # FK to people table (NULL if not matched)
    memo: str | None  # Note / description
    receipt_urls: str | None  # JSON array of receipt URLs (Ramp-specific)
    status: str | None  # Transaction status
    ramp_url: str | None  # Deep link to source app (NULL for non-Ramp sources)
    source: str  # Required — connector ID: 'ramp', 'lunchmoney', etc.


def normalize_amount(raw) -> float:
    """Normalize an amount value to a positive float.

    Handles both scalar numbers and dict shapes (e.g. {"amount": "150.00", "currency_iso": "USD"}).
    Always returns abs() so stored amounts are consistently positive.
    """
    if isinstance(raw, dict):
        raw = raw.get("amount", 0) or raw.get("value", 0)
    try:
        return abs(float(raw))
    except (TypeError, ValueError):
        return 0.0
