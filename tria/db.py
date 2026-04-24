"""SQLite state management — runs history + classifications dedup."""
import sqlite3
from datetime import datetime, timezone
from typing import Optional


DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant TEXT NOT NULL,
    started_at TIMESTAMP NOT NULL,
    finished_at TIMESTAMP,
    emails_fetched INTEGER DEFAULT 0,
    emails_classified INTEGER DEFAULT 0,
    status TEXT DEFAULT 'running',
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS classifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    message_id TEXT NOT NULL UNIQUE,
    thread_id TEXT,
    sender TEXT,
    subject TEXT,
    snippet TEXT,
    received_at TIMESTAMP,
    category_id TEXT,
    reasoning TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(id)
);

CREATE INDEX IF NOT EXISTS idx_classifications_message ON classifications(message_id);
CREATE INDEX IF NOT EXISTS idx_classifications_run ON classifications(run_id);
CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at DESC);
"""


def get_conn(db_path: str = "tria.db") -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: str = "tria.db") -> None:
    with get_conn(db_path) as conn:
        conn.executescript(DB_SCHEMA)
        conn.commit()


def start_run(conn: sqlite3.Connection, tenant: str) -> int:
    cur = conn.execute(
        "INSERT INTO runs (tenant, started_at) VALUES (?, ?)",
        (tenant, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    return cur.lastrowid


def finish_run(
    conn: sqlite3.Connection,
    run_id: int,
    emails_fetched: int,
    emails_classified: int,
    status: str = "success",
    error_message: Optional[str] = None,
) -> None:
    conn.execute(
        """UPDATE runs
           SET finished_at = ?, emails_fetched = ?, emails_classified = ?,
               status = ?, error_message = ?
           WHERE id = ?""",
        (
            datetime.now(timezone.utc).isoformat(),
            emails_fetched,
            emails_classified,
            status,
            error_message,
            run_id,
        ),
    )
    conn.commit()


def is_processed(conn: sqlite3.Connection, message_id: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM classifications WHERE message_id = ?", (message_id,)
    )
    return cur.fetchone() is not None


def save_classification(
    conn: sqlite3.Connection,
    run_id: int,
    message_id: str,
    thread_id: str,
    sender: str,
    subject: str,
    snippet: str,
    received_at: str,
    category_id: str,
    reasoning: str,
) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO classifications
           (run_id, message_id, thread_id, sender, subject, snippet,
            received_at, category_id, reasoning)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            run_id,
            message_id,
            thread_id,
            sender,
            subject,
            snippet,
            received_at,
            category_id,
            reasoning,
        ),
    )
    conn.commit()
