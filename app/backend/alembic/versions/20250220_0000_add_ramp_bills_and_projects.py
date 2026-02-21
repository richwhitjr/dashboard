"""Add Ramp bills, vendors, and projects tables

Revision ID: 20250220_0000
Revises: 20250218_0001
Create Date: 2025-02-20 00:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20250220_0000"
down_revision: Union[str, None] = "20250218_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS ramp_vendors (
        id TEXT PRIMARY KEY,
        name TEXT,
        is_active INTEGER DEFAULT 1,
        synced_at TEXT DEFAULT (datetime('now'))
    )
    """)

    op.execute("""
    CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT,
        budget_amount REAL DEFAULT 0,
        currency TEXT DEFAULT 'USD',
        status TEXT DEFAULT 'active',
        vendor_id TEXT,
        notes TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    )
    """)

    op.execute("""
    CREATE TABLE IF NOT EXISTS ramp_bills (
        id TEXT PRIMARY KEY,
        vendor_id TEXT,
        vendor_name TEXT,
        amount REAL,
        currency TEXT DEFAULT 'USD',
        due_at TEXT,
        issued_at TEXT,
        paid_at TEXT,
        invoice_number TEXT,
        memo TEXT,
        status TEXT,
        approval_status TEXT,
        payment_status TEXT,
        payment_method TEXT,
        line_items_json TEXT,
        project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
        ramp_url TEXT,
        synced_at TEXT DEFAULT (datetime('now'))
    )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ramp_bills")
    op.execute("DROP TABLE IF EXISTS projects")
    op.execute("DROP TABLE IF EXISTS ramp_vendors")
