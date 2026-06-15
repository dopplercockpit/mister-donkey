"""Best-effort SQLite quota tracking for expensive LLM calls."""
import hashlib
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

try:
    from flask import g, has_request_context, request
except Exception:  # pragma: no cover - keeps helper importable outside Flask
    g = None
    request = None

    def has_request_context():
        return False


def _env_int(name, default):
    try:
        return int(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        return default


LLM_QUOTA_DB_PATH = os.getenv("LLM_QUOTA_DB_PATH", "llm_quota.db")
LLM_DAILY_LIMIT_PER_IP = _env_int("LLM_DAILY_LIMIT_PER_IP", 20)
LLM_BURST_LIMIT_PER_MINUTE = _env_int("LLM_BURST_LIMIT_PER_MINUTE", 5)

logger = logging.getLogger("mister_donkey.llm_quota")
_quota_db_initialized = False


def _env_name():
    return os.getenv("ENV", "prod").strip().lower()


def _env_salt():
    configured = os.getenv("RATE_LIMIT_SALT", "").strip()
    if configured:
        return configured
    if _env_name() in ("dev", "development", "local", "test"):
        return "dev-only-rate-limit-salt"
    logger.error("RATE_LIMIT_SALT is required in production; using temporary process fallback")
    return "missing-production-rate-limit-salt"


@contextmanager
def _conn():
    conn = sqlite3.connect(LLM_QUOTA_DB_PATH, timeout=5)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_quota_db():
    global _quota_db_initialized
    with _conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS llm_quota_usage (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              request_key TEXT NOT NULL UNIQUE,
              ip_hash TEXT NOT NULL,
              session_id TEXT,
              client_id TEXT,
              endpoint TEXT NOT NULL,
              date_bucket TEXT NOT NULL,
              minute_bucket TEXT NOT NULL,
              cache_key TEXT,
              created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_llm_quota_ip_date
            ON llm_quota_usage (ip_hash, date_bucket)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_llm_quota_ip_minute
            ON llm_quota_usage (ip_hash, minute_bucket)
            """
        )
    _quota_db_initialized = True


def ensure_quota_db():
    if not _quota_db_initialized:
        init_quota_db()


def utc_buckets(now=None):
    now = now or datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%dT%H:%MZ")


def hash_ip(ip_address):
    raw_ip = (ip_address or "unknown").strip() or "unknown"
    salted = f"{_env_salt()}:{raw_ip}"
    return hashlib.sha256(salted.encode("utf-8")).hexdigest()


def _client_ip_from_request():
    if not has_request_context():
        return None
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.headers.get("X-Real-IP") or request.remote_addr


def _request_json():
    if not has_request_context() or not request.is_json:
        return {}
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def quota_context_from_request(endpoint=None):
    data = _request_json()
    session_id = data.get("session_id")
    client_id = data.get("client_id") or data.get("user_id")
    request_id = getattr(g, "request_id", None) if has_request_context() else None
    endpoint_name = endpoint or (request.path if has_request_context() else "internal")

    return {
        "ip_hash": hash_ip(_client_ip_from_request()),
        "session_id": session_id,
        "client_id": client_id,
        "endpoint": endpoint_name,
        "request_id": request_id,
    }


def check_llm_quota(context=None, now=None):
    context = context or quota_context_from_request()
    date_bucket, minute_bucket = utc_buckets(now)
    ip_hash = context.get("ip_hash") or hash_ip(None)

    try:
        ensure_quota_db()
        with _conn() as conn:
            daily_count = conn.execute(
                """
                SELECT COUNT(*) FROM llm_quota_usage
                WHERE ip_hash = ? AND date_bucket = ?
                """,
                (ip_hash, date_bucket),
            ).fetchone()[0]
            minute_count = conn.execute(
                """
                SELECT COUNT(*) FROM llm_quota_usage
                WHERE ip_hash = ? AND minute_bucket = ?
                """,
                (ip_hash, minute_bucket),
            ).fetchone()[0]

        if daily_count >= LLM_DAILY_LIMIT_PER_IP:
            return {
                "allowed": False,
                "quota_status": "limited",
                "reason": "daily_limit",
                "daily_count": daily_count,
                "minute_count": minute_count,
                "daily_limit": LLM_DAILY_LIMIT_PER_IP,
                "burst_limit": LLM_BURST_LIMIT_PER_MINUTE,
            }
        if minute_count >= LLM_BURST_LIMIT_PER_MINUTE:
            return {
                "allowed": False,
                "quota_status": "limited",
                "reason": "burst_limit",
                "daily_count": daily_count,
                "minute_count": minute_count,
                "daily_limit": LLM_DAILY_LIMIT_PER_IP,
                "burst_limit": LLM_BURST_LIMIT_PER_MINUTE,
            }
        return {
            "allowed": True,
            "quota_status": "allowed",
            "reason": None,
            "daily_count": daily_count,
            "minute_count": minute_count,
            "daily_limit": LLM_DAILY_LIMIT_PER_IP,
            "burst_limit": LLM_BURST_LIMIT_PER_MINUTE,
        }
    except Exception as exc:
        logger.warning("LLM quota check failed: %s", exc)
        return {
            "allowed": True,
            "quota_status": "unavailable",
            "reason": "quota_db_error",
            "daily_limit": LLM_DAILY_LIMIT_PER_IP,
            "burst_limit": LLM_BURST_LIMIT_PER_MINUTE,
        }


def record_llm_usage(context=None, cache_key=None, now=None):
    context = context or quota_context_from_request()
    now = now or datetime.now(timezone.utc)
    date_bucket, minute_bucket = utc_buckets(now)
    ip_hash = context.get("ip_hash") or hash_ip(None)
    request_id = context.get("request_id") or f"{now.timestamp()}:{ip_hash}:{cache_key or ''}"
    request_key = hashlib.sha256(
        f"{ip_hash}:{context.get('endpoint')}:{request_id}:{cache_key or ''}".encode("utf-8")
    ).hexdigest()

    try:
        ensure_quota_db()
        with _conn() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO llm_quota_usage (
                  request_key, ip_hash, session_id, client_id, endpoint,
                  date_bucket, minute_bucket, cache_key, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_key,
                    ip_hash,
                    context.get("session_id"),
                    context.get("client_id"),
                    context.get("endpoint") or "internal",
                    date_bucket,
                    minute_bucket,
                    cache_key,
                    now.isoformat(),
                ),
            )
    except Exception as exc:
        logger.warning("LLM quota record failed: %s", exc)
