#!/usr/bin/env python3
"""Example-output checks for deterministic fallback weather roasts."""
from fallback_roasts import build_fallback_roast


def sample_current(weather_id, main, temp=18, wind=2):
    return {
        "main": {"temp": temp, "feels_like": temp - 1, "humidity": 61},
        "wind": {"speed": wind},
        "weather": [{"id": weather_id, "main": main, "description": main.lower()}],
    }


def main():
    examples = {
        "clear": sample_current(800, "Clear", temp=24),
        "rain": sample_current(501, "Rain", temp=13),
        "snow": sample_current(601, "Snow", temp=-2),
        "thunderstorm": sample_current(211, "Thunderstorm", temp=19),
        "unknown": {"main": {}, "weather": [{"main": "Odd"}]},
    }

    for name, current in examples.items():
        text = build_fallback_roast(
            "Test City",
            current,
            alerts=[],
            tone="sarcastic",
            reason="llm_error",
        )
        assert "Test City" in text
        assert "LLM" in text
        assert len(text) < 400
        print(f"{name}: {text}")

    print("Fallback roast test passed")


if __name__ == "__main__":
    main()
