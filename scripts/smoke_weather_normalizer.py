import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from weather_normalizer import normalize_openweather_current, normalize_weatherapi_current


def test_openweather():
    snapshot = normalize_openweather_current({
        "main": {"temp": 12.4, "feels_like": 10.1, "humidity": 82, "pressure": 1014},
        "weather": [{"id": 500, "main": "Rain", "description": "light rain", "icon": "10d"}],
        "wind": {"speed": 3.5, "deg": 210},
        "visibility": 9000,
        "clouds": {"all": 75},
        "rain": {"1h": 0.6},
    }).to_dict()

    assert snapshot["source"] == "openweather"
    assert snapshot["temp_c"] == 12.4
    assert snapshot["condition_code"] == 500
    assert snapshot["condition_main"] == "Rain"
    assert snapshot["conditions_code"] == "Rain"
    assert snapshot["wind_kph"] == 12.6
    assert snapshot["wind_speed_kmh"] == 12.6
    assert snapshot["precip_mm"] == 0.6


def test_weatherapi():
    snapshot = normalize_weatherapi_current({
        "current": {
            "temp_c": 18.2,
            "temp_f": 64.8,
            "feelslike_c": 17.7,
            "feelslike_f": 63.9,
            "humidity": 60,
            "wind_kph": 14.8,
            "wind_mph": 9.2,
            "wind_degree": 180,
            "condition": {"text": "Partly cloudy", "code": 1003, "icon": "//cdn.weatherapi.com/icon.png"},
            "precip_mm": 0,
            "uv": 4,
            "vis_km": 10,
            "cloud": 35,
            "pressure_mb": 1012,
        }
    }).to_dict()

    assert snapshot["source"] == "weatherapi"
    assert snapshot["temp_c"] == 18.2
    assert snapshot["condition_code"] == 1003
    assert snapshot["conditions"] == "Partly cloudy"
    assert snapshot["wind_kph"] == 14.8
    assert snapshot["wind_speed_kmh"] == 14.8
    assert snapshot["cloud_pct"] == 35
    assert snapshot["clouds_percent"] == 35


if __name__ == "__main__":
    test_openweather()
    test_weatherapi()
    print("weather_normalizer smoke test passed")
