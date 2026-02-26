"""Add longform posts, tags, comments, and FTS tables

Revision ID: 20260225_0000
Revises: 20260224_0002
Create Date: 2026-02-25 00:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260225_0000"
down_revision: Union[str, None] = "20260224_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS longform_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL DEFAULT 'Untitled',
            body TEXT DEFAULT '',
            status TEXT DEFAULT 'draft',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            published_at TEXT,
            word_count INTEGER DEFAULT 0,
            claude_session_id INTEGER,
            FOREIGN KEY (claude_session_id) REFERENCES claude_sessions(id) ON DELETE SET NULL
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS longform_tags (
            post_id INTEGER NOT NULL,
            tag TEXT NOT NULL,
            PRIMARY KEY (post_id, tag),
            FOREIGN KEY (post_id) REFERENCES longform_posts(id) ON DELETE CASCADE
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS longform_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            is_thought INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (post_id) REFERENCES longform_posts(id) ON DELETE CASCADE
        )
    """)

    op.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS fts_longform USING fts5(
            title, body,
            content='longform_posts',
            content_rowid='id'
        )
    """)

    op.execute("INSERT INTO fts_longform(fts_longform) VALUES('rebuild')")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS fts_longform")
    op.execute("DROP TABLE IF EXISTS longform_comments")
    op.execute("DROP TABLE IF EXISTS longform_tags")
    op.execute("DROP TABLE IF EXISTS longform_posts")
