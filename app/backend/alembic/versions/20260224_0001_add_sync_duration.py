"""Add duration_seconds column to sync_state

Revision ID: 20260224_0001
Revises: 20260224_0000
Create Date: 2026-02-24 14:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260224_0001"
down_revision: Union[str, None] = "20260224_0000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE sync_state ADD COLUMN duration_seconds REAL")


def downgrade() -> None:
    pass
