"""Add personas table for Claude terminal customization

Revision ID: 20250221_0000
Revises: 20250220_0000
Create Date: 2025-02-21 00:00:00

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20250221_0000"
down_revision: Union[str, None] = "20250220_0000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS personas (
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

    # Seed built-in personas
    op.execute("""
    INSERT INTO personas (name, description, system_prompt, icon, is_default) VALUES
    ('Default', 'Standard dashboard assistant with full context', '', '🤖', 1)
    """)
    op.execute(
        "INSERT INTO personas (name, description, system_prompt, icon, is_default) VALUES"
        " ('Personal Assistant', 'Helps with scheduling, reminders, and personal tasks',"
        " 'You are a personal assistant. Focus on scheduling, task management, and"
        " practical day-to-day help. Be concise and action-oriented. Anticipate needs"
        " and suggest next steps proactively.', '📋', 0)"
    )
    op.execute(
        "INSERT INTO personas (name, description, system_prompt, icon, is_default) VALUES"
        " ('Travel Agent', 'Plans trips, finds flights, hotels, and itineraries',"
        " 'You are an expert travel planner. Help with trip planning, flight and hotel"
        " recommendations, itinerary creation, visa requirements, and travel logistics."
        " Always consider budget, preferences, and practical constraints.', '✈️', 0)"
    )
    op.execute(
        "INSERT INTO personas (name, description, system_prompt, icon, is_default) VALUES"
        " ('Scientist', 'Analyzes data, explains research, and thinks rigorously',"
        " 'You are a research scientist and analytical thinker. Approach problems with"
        " rigor, cite evidence, consider alternative hypotheses, and think in terms of"
        " data and experiments. Be precise with terminology.', '🔬', 0)"
    )
    op.execute(
        "INSERT INTO personas (name, description, system_prompt, icon, is_default) VALUES"
        " ('Writing Editor', 'Reviews and improves writing quality',"
        " 'You are a professional writing editor. Review text for clarity, conciseness,"
        " grammar, and style. Suggest specific improvements. Maintain the author''s voice"
        " while elevating quality.', '✍️', 0)"
    )
    op.execute(
        "INSERT INTO personas (name, description, system_prompt, icon, is_default) VALUES"
        " ('Code Reviewer', 'Reviews code for quality, bugs, and best practices',"
        " 'You are a senior code reviewer. Analyze code for bugs, performance issues,"
        " security vulnerabilities, and adherence to best practices. Be specific about"
        " issues and suggest concrete fixes.', '🔍', 0)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS personas")
