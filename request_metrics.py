import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

try:
    from flask import g, has_request_context, request
except Exception:  # pragma: no cover - keeps module importable outside Flask
    g = None
    request = None

    def has_request_context():
        return False

REQUEST_METRICS_DB_PATH = os.getenv("REQUEST_METRICS_DB_PATH", "request_metrics.db")


@contextmanager
def _connect():
    conn = sqlite3.connect(REQUEST_METRICS_DB_PATH, timeout=5)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS event_metrics (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              timestamp TEXT NOT NULL,
              event_name TEXT NOT NULL,
              endpoint TEXT,
              ip_hash TEXT,
              session_id TEXT,
              client_id TEXT,
              location TEXT,
              tone TEXT,
              cache_status TEXT,
              quota_status TEXT,
              fallback_reason TEXT,
              request_id TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_event_metrics_name_time
            ON event_metrics (event_name, timestamp)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_event_metrics_session_time
            ON event_metrics (session_id, timestamp)
            """
        )


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


def _request_payload():
    if not has_request_context() or not request.is_json:
        return {}
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _request_ip_hash():
    if not has_request_context():
        return None
    try:
        from llm_quota import hash_ip

        forwarded = request.headers.get("X-Forwarded-For", "")
        raw_ip = forwarded.split(",")[0].strip() if forwarded else request.headers.get("X-Real-IP") or request.remote_addr
        return hash_ip(raw_ip)
    except Exception:
        return None


def _request_context_defaults():
    if not has_request_context():
        return {}
    data = _request_payload()
    location_data = data.get("location") if isinstance(data.get("location"), dict) else {}
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    return {
        "endpoint": request.path,
        "ip_hash": _request_ip_hash(),
        "session_id": data.get("session_id") or getattr(g, "session_id", None),
        "client_id": data.get("client_id") or data.get("user_id"),
        "location": data.get("city") or location_data.get("city") or location_data.get("name") or metadata.get("location") or getattr(g, "location", None),
        "tone": data.get("tone"),
        "request_id": getattr(g, "request_id", None),
    }


def record_event_metric(
    event_name,
    endpoint=None,
    ip_hash=None,
    session_id=None,
    client_id=None,
    location=None,
    tone=None,
    cache_status=None,
    quota_status=None,
    fallback_reason=None,
    request_id=None,
):
    """Best-effort event metric; never raises into request handling."""
    try:
        defaults = _request_context_defaults()
        timestamp = datetime.now(timezone.utc).isoformat()
        with _connect() as conn:
            conn.execute(
                """
                INSERT INTO event_metrics (
                  timestamp, event_name, endpoint, ip_hash, session_id, client_id,
                  location, tone, cache_status, quota_status, fallback_reason, request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    timestamp,
                    event_name,
                    endpoint or defaults.get("endpoint"),
                    ip_hash or defaults.get("ip_hash"),
                    session_id or defaults.get("session_id"),
                    client_id or defaults.get("client_id"),
                    location or defaults.get("location"),
                    tone or defaults.get("tone"),
                    cache_status,
                    quota_status,
                    fallback_reason,
                    request_id or defaults.get("request_id"),
                ),
            )
    except Exception as exc:
        if os.getenv("ENV", "prod").strip().lower() in ("dev", "development", "local", "test"):
            print(f"Event metrics recording failed: {exc}")


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
        conn.execute("DELETE FROM event_metrics WHERE timestamp < ?", (cutoff,))
