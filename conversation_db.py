"""SQLite-backed conversation history.

Separate from the in-memory conversation_manager — this module owns durable
message storage.  conversation_manager still handles session metadata.
"""
import sqlite3
import os
from datetime import datetime, timezone
from contextlib import contextmanager

DB_PATH = os.getenv("CONVERSATION_DB_PATH", "conversation_history.db")
MAX_MESSAGES_PER_SESSION = 50   # FIFO eviction cap (messages, not exchanges)


def init_db() -> None:
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversation_history (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT    NOT NULL,
                role       TEXT    NOT NULL CHECK(role IN ('user', 'assistant')),
                content    TEXT    NOT NULL,
                timestamp  TEXT    NOT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_session "
            "ON conversation_history (session_id)"
        )


@contextmanager
def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def store_exchange(session_id: str, user_msg: str, assistant_msg: str) -> None:
    """Persist one user+assistant exchange; evict oldest messages when over cap."""
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO conversation_history "
            "(session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (session_id, "user", user_msg, now),
        )
        conn.execute(
            "INSERT INTO conversation_history "
            "(session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (session_id, "assistant", assistant_msg, now),
        )
        # FIFO eviction
        count = conn.execute(
            "SELECT COUNT(*) FROM conversation_history WHERE session_id = ?",
            (session_id,),
        ).fetchone()[0]
        if count > MAX_MESSAGES_PER_SESSION:
            to_delete = count - MAX_MESSAGES_PER_SESSION
            conn.execute(
                """
                DELETE FROM conversation_history
                WHERE id IN (
                    SELECT id FROM conversation_history
                    WHERE session_id = ?
                    ORDER BY id ASC
                    LIMIT ?
                )
                """,
                (session_id, to_delete),
            )


def get_history_for_openai(session_id: str, exchanges: int = 6) -> list:
    """Return last N exchanges as OpenAI-formatted messages, oldest-first."""
    limit = exchanges * 2
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT role, content FROM (
                SELECT id, role, content
                FROM conversation_history
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
            )
            ORDER BY id ASC
            """,
            (session_id, limit),
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def get_history_raw(session_id: str, exchanges: int = 20) -> list:
    """Return last N exchanges as plain dicts for the /history endpoint."""
    limit = exchanges * 2
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT role, content, timestamp FROM (
                SELECT id, role, content, timestamp
                FROM conversation_history
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
            )
            ORDER BY id ASC
            """,
            (session_id, limit),
        ).fetchall()
    return [
        {"role": r["role"], "content": r["content"], "timestamp": r["timestamp"]}
        for r in rows
    ]
