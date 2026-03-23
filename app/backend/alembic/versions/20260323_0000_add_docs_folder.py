"""Add folder column to longform_posts and migrate statuses to active/archived

Revision ID: 20260323_0000
Revises: 20260318_0000
Create Date: 2026-03-23 00:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260323_0000"
down_revision: Union[str, None] = "20260318_0000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add folder column
    op.execute("ALTER TABLE longform_posts ADD COLUMN folder TEXT")

    # Migrate statuses: draft → active, published → active
    op.execute("UPDATE longform_posts SET status = 'active' WHERE status IN ('draft', 'published')")


def downgrade() -> None:
    # Revert statuses (map active → draft, archived → published)
    op.execute("UPDATE longform_posts SET status = 'draft' WHERE status = 'active'")
    op.execute("UPDATE longform_posts SET status = 'published' WHERE status = 'archived'")
    # SQLite doesn't support DROP COLUMN in older versions, so we skip it
