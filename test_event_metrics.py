#!/usr/bin/env python3
"""Small standard-library verification for event metrics."""
import os
import sqlite3
import tempfile


def main():
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["REQUEST_METRICS_DB_PATH"] = os.path.join(tmpdir, "request_metrics_test.db")

        import request_metrics

        request_metrics.REQUEST_METRICS_DB_PATH = os.environ["REQUEST_METRICS_DB_PATH"]
        request_metrics.init_metrics_db()
        request_metrics.record_event_metric(
            "cache_hit",
            endpoint="/prompt",
            ip_hash="hashed-ip-only",
            session_id="session-1",
            client_id="client-1",
            location="Test City",
            tone="sarcastic",
            cache_status="hit",
            quota_status="not_counted_cache_hit",
            fallback_reason=None,
            request_id="request-1",
        )
        request_metrics.record_event_metric(
            "fallback_used",
            endpoint="/prompt",
            ip_hash="hashed-ip-only",
            location="Test City",
            tone="sarcastic",
            cache_status="miss",
            quota_status="limited",
            fallback_reason="quota_exceeded",
        )

        conn = sqlite3.connect(request_metrics.REQUEST_METRICS_DB_PATH)
        try:
            rows = conn.execute(
                """
                SELECT event_name, endpoint, ip_hash, location, tone,
                       cache_status, quota_status, fallback_reason
                FROM event_metrics
                ORDER BY id
                """
            ).fetchall()
        finally:
            conn.close()

        assert len(rows) == 2
        assert rows[0] == (
            "cache_hit",
            "/prompt",
            "hashed-ip-only",
            "Test City",
            "sarcastic",
            "hit",
            "not_counted_cache_hit",
            None,
        )
        assert rows[1][0] == "fallback_used"
        assert rows[1][7] == "quota_exceeded"

    print("Event metrics test passed")


if __name__ == "__main__":
    main()
