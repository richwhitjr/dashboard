"""Add saved column to agent_conversations for save-on-demand

Revision ID: 20260316_0001
Revises: 20260316_0000
Create Date: 2026-03-16 00:01:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260316_0001"
down_revision: Union[str, None] = "20260316_0000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE agent_conversations ADD COLUMN saved INTEGER NOT NULL DEFAULT 0")


def downgrade() -> None:
    # SQLite doesn't support DROP COLUMN before 3.35; recreate table if needed.
    # For simplicity, this is a no-op since the column is harmless if unused.
    pass
