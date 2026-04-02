"""Add source column to spending tables and create spending_entries unified VIEW

Revision ID: 20260401_0001
Revises: 20260401_0000
Create Date: 2026-04-01 00:01:00

Adds a `source` column to ramp_transactions and ramp_bills so future connectors
(LunchMoney, NetSuite, etc.) can write into the same tables. Creates a
`spending_entries` VIEW that UNIONs both tables into a single queryable structure
with transaction_type and direction indicators for agent use.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260401_0001"
down_revision: Union[str, None] = "20260401_0000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add source column to transactions — backfills all existing Ramp rows
    op.execute("ALTER TABLE ramp_transactions ADD COLUMN source TEXT DEFAULT 'ramp'")
    op.execute("UPDATE ramp_transactions SET source = 'ramp' WHERE source IS NULL")
    op.execute("CREATE INDEX IF NOT EXISTS idx_ramp_transactions_source ON ramp_transactions(source)")

    # Add source column to bills — backfills all existing Ramp rows
    op.execute("ALTER TABLE ramp_bills ADD COLUMN source TEXT DEFAULT 'ramp'")
    op.execute("UPDATE ramp_bills SET source = 'ramp' WHERE source IS NULL")
    op.execute("CREATE INDEX IF NOT EXISTS idx_ramp_bills_source ON ramp_bills(source)")

    # Create unified spending_entries VIEW
    # This gives agents a single table to query across all spending sources.
    # transaction_type: 'card' (credit card transactions) or 'bill' (AP invoices/POs)
    # direction: 'out' for money leaving, 'in' for money received (future AR support)
    op.execute(
        """
CREATE VIEW IF NOT EXISTS spending_entries AS
SELECT
  'card_' || id          AS entry_id,
  'card'                 AS transaction_type,
  'out'                  AS direction,
  amount,
  currency,
  merchant_name          AS vendor_name,
  category,
  transaction_date       AS entry_date,
  NULL                   AS due_date,
  cardholder_name        AS person_name,
  cardholder_email       AS person_email,
  employee_id,
  memo,
  status,
  NULL                   AS payment_status,
  NULL                   AS invoice_number,
  NULL                   AS project_id,
  ramp_url               AS external_url,
  source,
  synced_at
FROM ramp_transactions

UNION ALL

SELECT
  'bill_' || id          AS entry_id,
  'bill'                 AS transaction_type,
  'out'                  AS direction,
  amount,
  currency,
  vendor_name,
  NULL                   AS category,
  COALESCE(issued_at, due_at) AS entry_date,
  due_at,
  NULL                   AS person_name,
  NULL                   AS person_email,
  NULL                   AS employee_id,
  memo,
  status,
  payment_status,
  invoice_number,
  project_id,
  ramp_url               AS external_url,
  source,
  synced_at
FROM ramp_bills
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS spending_entries")
    op.execute("DROP INDEX IF EXISTS idx_ramp_transactions_source")
    op.execute("DROP INDEX IF EXISTS idx_ramp_bills_source")
    # SQLite doesn't support DROP COLUMN — source columns remain but are harmless
