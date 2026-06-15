"""SQLite cache for final LLM weather responses.

The cache is intentionally local and best-effort: failures are logged and the
weather endpoint continues through the normal LLM path.
"""
import hashlib
import json
import logging
import math
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone


def _env_int(name, default):
    try:
        return int(os.getenv(name, str(default)) or default)
    except (TypeError, ValueError):
        return default


LLM_CACHE_DB_PATH = os.getenv("LLM_CACHE_DB_PATH", "llm_response_cache.db")
LLM_CACHE_TTL_SECONDS = _env_int("LLM_CACHE_TTL_SECONDS", 10800)
LLM_CACHE_CLEANUP_INTERVAL_SECONDS = _env_int("LLM_CACHE_CLEANUP_INTERVAL_SECONDS", 3600)
PROMPT_VERSION = os.getenv("LLM_CACHE_PROMPT_VERSION", "weather_roast_v1").strip() or "weather_roast_v1"

logger = logging.getLogger("mister_donkey.llm_cache")
_last_cleanup_ts = 0.0
_cache_db_initialized = False


@contextmanager
def _conn():
    conn = sqlite3.connect(LLM_CACHE_DB_PATH, timeout=5)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_cache_db():
    global _cache_db_initialized
    with _conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS llm_response_cache (
              cache_key TEXT PRIMARY KEY,
              location_label TEXT,
              tone TEXT,
              weather_summary TEXT,
              weather_id TEXT,
              response_text TEXT NOT NULL,
              created_at TEXT NOT NULL,
              expires_at TEXT NOT NULL,
              prompt_version TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_llm_response_cache_expires_at
            ON llm_response_cache (expires_at)
            """
        )
    _cache_db_initialized = True


def ensure_cache_db():
    if not _cache_db_initialized:
        init_cache_db()


def normalize_location_label(location_label):
    return " ".join(str(location_label or "").strip().lower().split())


def split_region_country(location_label):
    parts = [part.strip().lower() for part in str(location_label or "").split(",") if part.strip()]
    country = parts[-1] if len(parts) >= 2 else ""
    region = parts[-2] if len(parts) >= 3 else ""
    return region, country


def rounded_coord(value):
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def temperature_band(temp_c):
    try:
        temp = float(temp_c)
    except (TypeError, ValueError):
        return ""
    lower = math.floor(temp / 5.0) * 5
    upper = lower + 4
    return f"{lower}to{upper}c"


def weather_identity(current):
    weather_items = current.get("weather") if isinstance(current, dict) else None
    first_weather = weather_items[0] if isinstance(weather_items, list) and weather_items else {}
    weather_id = first_weather.get("id")
    weather_main = first_weather.get("main") or first_weather.get("description") or ""
    return str(weather_id or weather_main or "").lower(), str(weather_main or "").lower()


def time_bucket(now=None, ttl_seconds=None):
    now = now or datetime.now(timezone.utc)
    ttl = int(ttl_seconds or LLM_CACHE_TTL_SECONDS)
    ttl = max(ttl, 1)
    epoch = int(now.timestamp())
    bucket_start = epoch - (epoch % ttl)
    return datetime.fromtimestamp(bucket_start, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_cache_key(
    *,
    location_label,
    lat=None,
    lon=None,
    current=None,
    tone=None,
    prompt_version=None,
    now=None,
):
    current = current if isinstance(current, dict) else {}
    main = current.get("main") if isinstance(current.get("main"), dict) else {}
    weather_id, weather_main = weather_identity(current)
    region, country = split_region_country(location_label)

    key_parts = {
        "location": normalize_location_label(location_label),
        "region": region,
        "country": country,
        "lat": rounded_coord(lat),
        "lon": rounded_coord(lon),
        "weather": weather_id or weather_main,
        "temp_band": temperature_band(main.get("temp")),
        "tone": str(tone or "").strip().lower(),
        "bucket": time_bucket(now=now),
        "prompt_version": prompt_version or PROMPT_VERSION,
    }
    encoded = json.dumps(key_parts, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest(), key_parts


def maybe_cleanup_expired_cache():
    global _last_cleanup_ts
    now_ts = time.time()
    if now_ts - _last_cleanup_ts < LLM_CACHE_CLEANUP_INTERVAL_SECONDS:
        return
    _last_cleanup_ts = now_ts
    try:
        delete_expired_cache_rows()
    except Exception as exc:
        logger.warning("LLM cache cleanup failed: %s", exc)


def delete_expired_cache_rows(now=None):
    cutoff = (now or datetime.now(timezone.utc)).isoformat()
    with _conn() as conn:
        conn.execute("DELETE FROM llm_response_cache WHERE expires_at <= ?", (cutoff,))


def get_cached_response_with_status(cache_key):
    try:
        ensure_cache_db()
        maybe_cleanup_expired_cache()
        now = datetime.now(timezone.utc).isoformat()
        with _conn() as conn:
            row = conn.execute(
                """
                SELECT response_text, location_label, tone, weather_summary, weather_id,
                       created_at, expires_at, prompt_version
                FROM llm_response_cache
                WHERE cache_key = ? AND expires_at > ?
                """,
                (cache_key, now),
            ).fetchone()
        if not row:
            return None, None
        return {
            "response_text": row[0],
            "location_label": row[1],
            "tone": row[2],
            "weather_summary": row[3],
            "weather_id": row[4],
            "created_at": row[5],
            "expires_at": row[6],
            "prompt_version": row[7],
        }, None
    except Exception as exc:
        logger.warning("LLM cache read failed: %s", exc)
        return None, str(exc)


def get_cached_response(cache_key):
    cached, _error = get_cached_response_with_status(cache_key)
    return cached


def save_cached_response(
    *,
    cache_key,
    location_label,
    tone,
    weather_summary,
    weather_id,
    response_text,
    prompt_version=None,
    ttl_seconds=None,
):
    try:
        ensure_cache_db()
        created_at = datetime.now(timezone.utc)
        ttl = int(ttl_seconds or LLM_CACHE_TTL_SECONDS)
        expires_at = created_at + timedelta(seconds=max(ttl, 1))
        with _conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO llm_response_cache (
                  cache_key, location_label, tone, weather_summary, weather_id,
                  response_text, created_at, expires_at, prompt_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cache_key,
                    location_label,
                    tone,
                    weather_summary,
                    str(weather_id or ""),
                    response_text,
                    created_at.isoformat(),
                    expires_at.isoformat(),
                    prompt_version or PROMPT_VERSION,
                ),
            )
    except Exception as exc:
        logger.warning("LLM cache write failed: %s", exc)
