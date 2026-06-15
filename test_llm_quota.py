#!/usr/bin/env python3
"""Small standard-library verification for LLM quota tracking.

Manual verification checklist:
1. First cache-miss weather request returns metadata.llm_called=true and writes one quota row.
2. Repeat request with the same weather/cache key returns metadata.cache_status="hit" and does not add a quota row.
3. With LLM_DAILY_LIMIT_PER_IP=1, a second uncached request returns metadata.quota_status="limited",
   metadata.llm_called=false, and metadata.fallback_used=true.
4. A cache hit still returns after quota is exceeded because cache lookup happens before quota check.
"""
import os
import sqlite3
import tempfile
from datetime import datetime, timezone


def main():
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["ENV"] = "test"
        os.environ["RATE_LIMIT_SALT"] = "quota-test-salt"
        os.environ["LLM_QUOTA_DB_PATH"] = os.path.join(tmpdir, "llm_quota_test.db")

        import llm_quota

        llm_quota.LLM_QUOTA_DB_PATH = os.environ["LLM_QUOTA_DB_PATH"]
        llm_quota.LLM_DAILY_LIMIT_PER_IP = 2
        llm_quota.LLM_BURST_LIMIT_PER_MINUTE = 2
        llm_quota.init_quota_db()

        ip_hash = llm_quota.hash_ip("203.0.113.10")
        assert ip_hash != "203.0.113.10"
        assert len(ip_hash) == 64

        context = {
            "ip_hash": ip_hash,
            "session_id": "session-1",
            "client_id": "client-1",
            "endpoint": "/prompt",
            "request_id": "request-1",
        }
        now = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)

        allowed = llm_quota.check_llm_quota(context, now=now)
        assert allowed["allowed"] is True
        assert allowed["daily_count"] == 0
        assert allowed["minute_count"] == 0

        llm_quota.record_llm_usage(context, cache_key="cache-a", now=now)
        llm_quota.record_llm_usage(context, cache_key="cache-a", now=now)

        conn = sqlite3.connect(llm_quota.LLM_QUOTA_DB_PATH)
        try:
            rows = conn.execute(
                "SELECT ip_hash, session_id, client_id, endpoint FROM llm_quota_usage"
            ).fetchall()
        finally:
            conn.close()
        assert len(rows) == 1
        assert rows[0][0] == ip_hash
        assert rows[0][0] != "203.0.113.10"
        assert rows[0][1:] == ("session-1", "client-1", "/prompt")

        context["request_id"] = "request-2"
        llm_quota.record_llm_usage(context, cache_key="cache-b", now=now)

        limited = llm_quota.check_llm_quota(context, now=now)
        assert limited["allowed"] is False
        assert limited["quota_status"] == "limited"
        assert limited["reason"] == "daily_limit"

        llm_quota.LLM_DAILY_LIMIT_PER_IP = 10
        burst_limited = llm_quota.check_llm_quota(context, now=now)
        assert burst_limited["allowed"] is False
        assert burst_limited["reason"] == "burst_limit"

    print("LLM quota test passed")


if __name__ == "__main__":
    main()
