"""Add issue discovery runs and proposed issues tables

Revision ID: 20260226_0000
Revises: 20260225_0000
Create Date: 2026-02-26 00:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260226_0000"
down_revision: Union[str, None] = "20260225_0000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS issue_discovery_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT DEFAULT (datetime('now')),
            completed_at TEXT,
            status TEXT DEFAULT 'running',
            items_found INTEGER DEFAULT 0,
            items_accepted INTEGER DEFAULT 0,
            items_rejected INTEGER DEFAULT 0,
            error TEXT,
            since_timestamp TEXT
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS proposed_issues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            priority INTEGER DEFAULT 1,
            tshirt_size TEXT DEFAULT 'm',
            source TEXT NOT NULL DEFAULT '',
            source_context TEXT DEFAULT '',
            suggested_tags TEXT DEFAULT '[]',
            suggested_people TEXT DEFAULT '[]',
            status TEXT DEFAULT 'pending',
            created_issue_id INTEGER,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (run_id) REFERENCES issue_discovery_runs(id) ON DELETE CASCADE,
            FOREIGN KEY (created_issue_id) REFERENCES issues(id) ON DELETE SET NULL
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS proposed_issues")
    op.execute("DROP TABLE IF EXISTS issue_discovery_runs")
