# process_app_prompt.py
import re
from dopplertower_engine import get_full_weather_summary
from geo_utils_helper import get_geolocation, reverse_geolocate
from nlpprepro import preprocess_with_gpt

def normalize_city_name(city: str) -> str:
    return " ".join(w.capitalize() for w in city.strip().split())

def extract_city_from_prompt(prompt: str) -> str | None:
    # capture “in CITY” or “at CITY” or “for CITY”
    m = re.search(r"(?:in|at|for)\s+([A-Za-z\s]+)", prompt)
    if m:
        # strip trailing punctuation
        return re.sub(r"[^\w\s]", "", m.group(1)).strip()
    return None

def process_prompt_from_app(prompt_text: str, location: dict | None = None) -> dict:
    """
    1) If front-end passed lat/lon and we didn’t already name a city in the text,
       reverse‑lookup via OpenCage.
    2) Otherwise, try extracting “in CITY” from the prompt.
    3) Fallback: use OpenCage geocode on the entire prompt.
    """
    city_query = None

        # 🧠 NLP Preprocessor via GPT
    parsed = preprocess_with_gpt(prompt_text)
    print("🤖 GPT preprocessor returned:", parsed)

    city_from_gpt = parsed.get("city")
    time_context = parsed.get("time_context")  # you’ll use this later for agent stuff
    intent = parsed.get("intent")

    # 1) location override
    if city_from_gpt:
        city_query = normalize_city_name(city_from_gpt)

    if location and not city_query:
        lat, lon = location.get("lat"), location.get("lon")
        if lat is not None and lon is not None and not extract_city_from_prompt(prompt_text):
            city_query = reverse_geolocate(lat, lon)


    # 2) extraction from prompt text
    if not city_query:
        raw = extract_city_from_prompt(prompt_text)
        if raw:
            city_query = normalize_city_name(raw)

    # 3) fallback geocode on full prompt (if user typed a city name without “in”)
    if not city_query:
        lat, lon, full = get_geolocation(prompt_text)
        if lat and lon:
            city_query = full

    if not city_query:
        return {"error": "City not found."}

    # now call your engine
    # return get_full_weather_summary(city_query, user_prompt=prompt_text, timezone_offset=0)
    result = get_full_weather_summary(city_query, user_prompt=prompt_text, timezone_offset=0)
    result["parsed_prompt"] = parsed  # 🧠 Smart add-on: lets frontend see GPT extraction
    return result


