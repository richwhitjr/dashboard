"""Add avatar_filename column and drop icon column from personas

Revision ID: 20250221_0001
Revises: 20250221_0000
Create Date: 2025-02-21 01:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20250221_0001"
down_revision: Union[str, None] = "20250221_0000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite doesn't support DROP COLUMN in older versions,
    # so we recreate the table without the icon column and add avatar_filename.
    op.execute("""
    CREATE TABLE personas_new (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT DEFAULT '',
        system_prompt TEXT NOT NULL DEFAULT '',
        avatar_filename TEXT DEFAULT NULL,
        is_default BOOLEAN NOT NULL DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    )
    """)

    op.execute("""
    INSERT INTO personas_new (id, name, description, system_prompt, is_default, created_at, updated_at)
    SELECT id, name, description, system_prompt, is_default, created_at, updated_at
    FROM personas
    """)

    op.execute("DROP TABLE personas")
    op.execute("ALTER TABLE personas_new RENAME TO personas")


def downgrade() -> None:
    op.execute("""
    CREATE TABLE personas_old (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT DEFAULT '',
        system_prompt TEXT NOT NULL DEFAULT '',
        icon TEXT DEFAULT '',
        is_default BOOLEAN NOT NULL DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    )
    """)

    op.execute("""
    INSERT INTO personas_old (id, name, description, system_prompt, is_default, created_at, updated_at)
    SELECT id, name, description, system_prompt, is_default, created_at, updated_at
    FROM personas
    """)

    op.execute("DROP TABLE personas")
    op.execute("ALTER TABLE personas_old RENAME TO personas")
