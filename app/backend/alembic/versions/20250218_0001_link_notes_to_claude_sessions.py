"""Link notes to Claude sessions

Revision ID: 20250218_0001
Revises: 20250218_0000
Create Date: 2025-02-18 00:00:01

"""

from typing import Sequence, Union

from sqlalchemy import text

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20250218_0001"
down_revision: Union[str, None] = "20250218_0000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add claude_session_id to notes table to link notes to Claude sessions
    conn = op.get_bind()
    result = conn.execute(text("PRAGMA table_info(notes)")).fetchall()
    cols = [row[1] for row in result]

    if "claude_session_id" not in cols:
        op.execute("ALTER TABLE notes ADD COLUMN claude_session_id INTEGER REFERENCES claude_sessions(id)")


def downgrade() -> None:
    # SQLite doesn't support DROP COLUMN easily, so we'd need to recreate the table
    # For now, just leave the column
    pass
