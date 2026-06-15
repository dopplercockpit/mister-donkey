#!/usr/bin/env python3
"""Small standard-library verification for the LLM SQLite cache helper."""
import os
import tempfile


def main():
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["LLM_CACHE_DB_PATH"] = os.path.join(tmpdir, "llm_cache_test.db")
        os.environ["LLM_CACHE_TTL_SECONDS"] = "10800"

        import llm_cache

        llm_cache.LLM_CACHE_DB_PATH = os.environ["LLM_CACHE_DB_PATH"]
        llm_cache.init_cache_db()

        current = {
            "main": {"temp": 18.2},
            "weather": [{"id": 800, "main": "Clear"}],
        }
        cache_key, parts = llm_cache.build_cache_key(
            location_label="Paris, Ile-de-France, France",
            lat=48.8566,
            lon=2.3522,
            current=current,
            tone="sarcastic",
            prompt_version=llm_cache.PROMPT_VERSION,
        )

        assert parts["location"] == "paris, ile-de-france, france"
        assert parts["country"] == "france"
        assert parts["region"] == "ile-de-france"
        assert parts["lat"] == 48.86
        assert parts["lon"] == 2.35
        assert parts["weather"] == "800"
        assert parts["temp_band"] == "15to19c"
        assert parts["tone"] == "sarcastic"

        assert llm_cache.get_cached_response(cache_key) is None

        llm_cache.save_cached_response(
            cache_key=cache_key,
            location_label="Paris, Ile-de-France, France",
            tone="sarcastic",
            weather_summary="800 / clear",
            weather_id="800",
            response_text="Cached weather roast",
            prompt_version=llm_cache.PROMPT_VERSION,
            ttl_seconds=10800,
        )

        cached = llm_cache.get_cached_response(cache_key)
        assert cached is not None
        assert cached["response_text"] == "Cached weather roast"

    print("LLM cache test passed")


if __name__ == "__main__":
    main()
