"""Add data_hash column to all ranking cache tables

Revision ID: 20260224_0002
Revises: 20260224_0001
Create Date: 2026-02-24 15:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260224_0002"
down_revision: Union[str, None] = "20260224_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in [
        "cached_email_priorities",
        "cached_slack_priorities",
        "cached_notion_priorities",
        "cached_drive_priorities",
        "cached_ramp_priorities",
        "cached_news_priorities",
        "cached_briefing_summary",
    ]:
        op.execute(f"ALTER TABLE {table} ADD COLUMN data_hash TEXT")


def downgrade() -> None:
    pass
