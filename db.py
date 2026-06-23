"""
Database layer — connection + versioned migration system.
Replaces the old migrate_db() in server.py.
"""
import sqlite3
from pathlib import Path

MONITOR_DIR = Path(__file__).parent
DB_PATH = MONITOR_DIR / "monitor.db"
FRONTEND_DIR = MONITOR_DIR / "frontend"
MIGRATIONS_DIR = MONITOR_DIR / "migrations"


def get_db():
    """Return a sqlite3 connection with row_factory set."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def migrate():
    """Run unapplied migrations in version order.

    Creates schema_version table if missing, then executes
    each .sql file in migrations/ whose version > current max.
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version "
        "(version INTEGER PRIMARY KEY, applied_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.commit()

    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    current = row[0] or 0

    if MIGRATIONS_DIR.exists():
        for m in sorted(MIGRATIONS_DIR.glob("*.sql")):
            try:
                version = int(m.stem.split("_")[0])
            except (ValueError, IndexError):
                continue
            if version > current:
                sql = m.read_text(encoding="utf-8")
                conn.executescript(sql)
                conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)", (version,)
                )
                conn.commit()

    conn.close()
