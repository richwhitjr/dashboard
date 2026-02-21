import sqlite3
import subprocess
from pathlib import Path

from config import DATABASE_PATH


def get_db() -> sqlite3.Connection:
    """Get a database connection with WAL mode and foreign keys enabled."""
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DATABASE_PATH), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def run_migrations():
    """Run Alembic migrations to upgrade database to latest version."""
    backend_dir = Path(__file__).parent
    alembic_ini = backend_dir / "alembic.ini"

    if not alembic_ini.exists():
        raise FileNotFoundError(f"Alembic config not found at {alembic_ini}")

    # Ensure database directory exists
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Find alembic executable in venv
    import sys

    alembic_path = Path(sys.executable).parent / "alembic"
    if not alembic_path.exists():
        # Fallback to system alembic
        alembic_path = "alembic"

    # Run alembic upgrade head
    result = subprocess.run(
        [str(alembic_path), "-c", str(alembic_ini), "upgrade", "head"],
        cwd=backend_dir,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"Migration error: {result.stderr}")
        raise RuntimeError(f"Database migration failed: {result.stderr}")

    print("Database migrations completed successfully")


def init_db():
    """Initialize database and run all migrations."""
    run_migrations()


# FTS (Full-Text Search) helper functions
FTS_TABLES = [
    "fts_employees",
    "fts_notes",
    "fts_granola",
    "fts_meeting_files",
    "fts_one_on_one",
    "fts_issues",
    "fts_emails",
]


def rebuild_fts():
    """Rebuild all FTS5 indexes from source tables."""
    conn = get_db()
    for table in FTS_TABLES:
        try:
            conn.execute(f"INSERT INTO {table}({table}) VALUES('rebuild')")
        except sqlite3.OperationalError:
            # Table doesn't exist yet, skip
            pass
    conn.commit()
    conn.close()


def rebuild_fts_table(table_name: str):
    """Rebuild a single FTS5 index."""
    if table_name not in FTS_TABLES:
        raise ValueError(f"Unknown FTS table: {table_name}")

    conn = get_db()
    try:
        conn.execute(f"INSERT INTO {table_name}({table_name}) VALUES('rebuild')")
        conn.commit()
    except sqlite3.OperationalError as e:
        print(f"Failed to rebuild {table_name}: {e}")
    finally:
        conn.close()
