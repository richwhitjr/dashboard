# Database Migrations with Alembic

This project uses [Alembic](https://alembic.sqlalchemy.org/) for database schema migrations. Migrations are automatically applied on application startup, and can also be managed via Makefile commands.

## Quick Reference

```bash
# Apply all pending migrations (run from project root)
make db-migrate

# Check current database version
make db-current

# View migration history
make db-history

# Roll back last migration
make db-downgrade

# Create a new migration
make db-revision
```

## How It Works

### Automatic Migrations on Startup

When the backend starts (`main.py`), it automatically calls `init_db()` which runs `alembic upgrade head` to apply any pending migrations. This means:

- **New installations**: The database is created from scratch with the latest schema
- **Existing installations**: Only new migrations are applied

### Migration Files

Migrations are located in `app/backend/alembic/versions/` and follow a chronological naming scheme:

```
YYYYMMDD_HHMM_<revision>_<description>.py
```

Example: `20250218_0000_add_fts_tables.py`

### Current Migration History

1. **20250101_0000**: Initial schema - all core tables
2. **20250105_0000**: Add employee metadata (is_executive, group_name, email, role_content, created_at, last_synced_at)
3. **20250110_0000**: Add relevance scoring to notion_pages
4. **20250115_0000**: Add note_employees junction table for many-to-many relationships
5. **20250120_0000**: Add issues tracking tables
6. **20250125_0000**: Add priorities caching and GitHub PR tracking
7. **20250130_0000**: Add meeting notes and dashboard dismissals
8. **20250205_0000**: Add per-source cached priorities tables
9. **20250210_0000**: Add Ramp transaction tracking
10. **20250215_0000**: Add Claude Code session tracking
11. **20250218_0000**: Add FTS5 full-text search tables

## Creating New Migrations

When you need to modify the database schema:

1. **Create a new migration file:**
   ```bash
   make db-revision
   # Enter a descriptive message when prompted
   ```

2. **Edit the generated migration file** in `alembic/versions/`:
   ```python
   def upgrade() -> None:
       # Add your schema changes here
       op.execute("ALTER TABLE table_name ADD COLUMN new_column TEXT")

   def downgrade() -> None:
       # Add rollback logic (optional for SQLite)
       pass
   ```

3. **Apply the migration:**
   ```bash
   make db-migrate
   ```

## Common Patterns

### Adding a Column

```python
def upgrade() -> None:
    op.execute("ALTER TABLE employees ADD COLUMN new_field TEXT DEFAULT ''")

def downgrade() -> None:
    # SQLite doesn't support DROP COLUMN easily
    pass
```

### Creating a Table

```python
def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS new_table (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now'))
    )
    """)

def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS new_table")
```

### Conditional Migrations (checking if column exists)

```python
from sqlalchemy import text

def upgrade() -> None:
    conn = op.get_bind()
    result = conn.execute(text("PRAGMA table_info(table_name)")).fetchall()
    cols = [row[1] for row in result]

    if 'new_column' not in cols:
        op.execute("ALTER TABLE table_name ADD COLUMN new_column TEXT")
```

## Important Notes

- **SQLite Limitations**: SQLite has limited ALTER TABLE support (no DROP COLUMN, no column type changes). For complex schema changes, you may need to recreate tables.

- **Foreign Keys**: Always enabled via `PRAGMA foreign_keys=ON` in database connections.

- **WAL Mode**: Database uses Write-Ahead Logging (`PRAGMA journal_mode=WAL`) for better concurrency.

- **FTS5 Tables**: Full-text search tables are created in the final migration and rebuilt automatically.

- **Existing Databases**: The migrations use `CREATE TABLE IF NOT EXISTS` and column existence checks to be safe when applying to databases that may already have some schema elements.

## Troubleshooting

### "No revision found" or version tracking issues

If the `alembic_version` table is empty or out of sync after running migrations:

```bash
# Check if version table is empty
sqlite3 ~/.personal-dashboard/dashboard.db "SELECT * FROM alembic_version"

# If empty, manually stamp with the latest version
sqlite3 ~/.personal-dashboard/dashboard.db "INSERT INTO alembic_version VALUES ('20250218_0000')"

# Verify
make db-current
```

**Note**: There's a known issue where Alembic's stamp command doesn't always write to the version table due to SQLite WAL mode transaction handling. The manual INSERT workaround above is reliable. This doesn't affect the actual schema migrations - all tables are created/updated correctly.

### Fresh database setup

To start with a clean database:

```bash
rm ~/.personal-dashboard/dashboard.db*
make db-migrate
```

### Viewing applied vs pending migrations

```bash
# Current version
make db-current

# All migrations
make db-history
```

## Configuration Files

- **alembic.ini**: Main Alembic configuration
- **alembic/env.py**: Migration environment (handles database connection, WAL mode, etc.)
- **alembic/script.py.mako**: Template for new migration files
- **alembic/versions/**: All migration files

## Integration with database.py

The old manual migration code in `database.py` has been replaced with Alembic. The `init_db()` function now simply calls `run_migrations()` which executes `alembic upgrade head`.

FTS (full-text search) helper functions remain available:
- `rebuild_fts()`: Rebuild all FTS indexes
- `rebuild_fts_table(table_name)`: Rebuild a specific FTS index
