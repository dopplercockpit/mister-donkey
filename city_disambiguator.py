# city_disambiguator.py 🧠🌍
# Smart disambiguation of fuzzy/multi-region city names
import requests
import os
from geo_utils_helper import calculate_distance

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
WEATHERAPI_KEY = os.getenv("WEATHERAPI_KEY")

def disambiguate_city(query: str, lat: float = None, lon: float = None) -> dict | None:
    """
    Disambiguates fuzzy city queries like 'London' or 'Windsor' by checking both
    OpenWeather and WeatherAPI, scoring results by proximity and keyword match.
    """
    open_results = fetch_openweather_candidates(query)
    weatherapi_results = fetch_weatherapi_candidates(query)

    all_candidates = open_results + weatherapi_results
    if not all_candidates:
        return None

    def score_candidate(c):
        score = 0
        if "region" in c and any(k in c["region"].lower() for k in ["ontario", "michigan", "rhône", "auvergne"]):
            score += 2
        if "country" in c and c["country"] in ["CA", "US", "FR"]:
            score += 1
        if lat and lon:
            dist = calculate_distance(lat, lon, c["lat"], c["lon"])
            if dist < 100:
                score += 3
            elif dist < 300:
                score += 1
        return score

    best = sorted(all_candidates, key=score_candidate, reverse=True)[0]
    return best

def fetch_openweather_candidates(query):
    try:
        url = f"http://api.openweathermap.org/geo/1.0/direct?q={query}&limit=5&appid={OPENWEATHER_API_KEY}"
        r = requests.get(url, timeout=5)
        r.raise_for_status()
        return [
            {
                "name": c.get("name"),
                "region": c.get("state", ""),
                "country": c.get("country", ""),
                "lat": c.get("lat"),
                "lon": c.get("lon"),
                "source": "openweather"
            }
            for c in r.json()
        ]
    except Exception as e:
        print(f"🌩️ OpenWeather error: {e}")
        return []

def fetch_weatherapi_candidates(query):
    try:
        url = f"http://api.weatherapi.com/v1/search.json?key={WEATHERAPI_KEY}&q={query}"
        r = requests.get(url, timeout=5)
        r.raise_for_status()
        return [
            {
                "name": c.get("name"),
                "region": c.get("region", ""),
                "country": c.get("country", ""),
                "lat": c.get("lat"),
                "lon": c.get("lon"),
                "source": "weatherapi"
            }
            for c in r.json()
        ]
    except Exception as e:
        print(f"🌦️ WeatherAPI error: {e}")
        return []
