import os
import sqlite3
from datetime import datetime, timedelta, timezone

REQUEST_METRICS_DB_PATH = os.getenv("REQUEST_METRICS_DB_PATH", "request_metrics.db")


def _connect():
    return sqlite3.connect(REQUEST_METRICS_DB_PATH, timeout=5)


def init_metrics_db():
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS request_metrics (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              timestamp TEXT NOT NULL,
              method TEXT NOT NULL,
              path TEXT NOT NULL,
              status INTEGER NOT NULL,
              duration_ms REAL NOT NULL,
              session_id TEXT,
              location TEXT,
              request_id TEXT,
              error INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.commit()


def record_request_metric(method, path, status, duration_ms, session_id=None, location=None, request_id=None):
    error = 1 if int(status) >= 500 else 0
    timestamp = datetime.now(timezone.utc).isoformat()

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO request_metrics (
              timestamp, method, path, status, duration_ms, session_id, location, request_id, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (timestamp, method, path, int(status), float(duration_ms), session_id, location, request_id, error),
        )
        conn.commit()


def get_metrics_summary(days=7):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT duration_ms, error
            FROM request_metrics
            WHERE timestamp >= ?
            ORDER BY duration_ms ASC
            """,
            (cutoff,),
        ).fetchall()

    if not rows:
        return {
            "avg_response_time_7d": 0,
            "p95_response_time": 0,
            "error_rate_7d": 0,
            "request_count_7d": 0,
        }

    durations = [float(row[0]) for row in rows]
    count = len(durations)
    p95_index = max(0, min(count - 1, int(count * 0.95 + 0.999999) - 1))
    error_count = sum(int(row[1]) for row in rows)

    return {
        "avg_response_time_7d": round(sum(durations) / count, 2),
        "p95_response_time": round(durations[p95_index], 2),
        "error_rate_7d": round((error_count / count) * 100, 2),
        "request_count_7d": count,
    }


def prune_old_metrics(days=7):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    with _connect() as conn:
        conn.execute("DELETE FROM request_metrics WHERE timestamp < ?", (cutoff,))
        conn.commit()
