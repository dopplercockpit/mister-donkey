import re
from dopplertower_engine import get_full_weather_summary
from geo_utils_helper import get_geolocation, reverse_geolocate
from nlpprepro import preprocess_with_gpt
from agent_dkmanager import check_and_create_agent

def normalize_city_name(city: str) -> str:
    return " ".join(w.capitalize() for w in city.strip().split())

def extract_city_from_prompt(prompt: str) -> str | None:
    # capture "in CITY" or "at CITY" or "for CITY"
    m = re.search(r"(?:in|at|for)\s+([A-Za-z\s]+)", prompt)
    if m:
        # strip trailing punctuation
        return re.sub(r"[^\w\s]", "", m.group(1)).strip()
    return None

def process_prompt_from_app(prompt_text: str, location: dict | None = None) -> dict:
    city_query = None
    prompt_metadata = {}

    # Step 0: NLP Preprocessing
    parsed = preprocess_with_gpt(prompt_text)
    print("🤖 GPT preprocessor returned:", parsed)

    city_from_gpt = parsed.get("city")
    time_context = parsed.get("time_context")
    intent = parsed.get("intent")

    # Step 1: Try GPT
    if city_from_gpt:
        city_query = normalize_city_name(city_from_gpt)
        print(f"🎯 Using city from GPT: {city_query}")

    # Step 2: Try regex extraction from user prompt
    if not city_query:
        raw = extract_city_from_prompt(prompt_text)
        if raw:
            city_query = normalize_city_name(raw)
            print(f"🎯 Found city in prompt: {city_query}")

    # Step 3: Use frontend location as fallback *only* if above didn't yield a good result
    if location and (not city_query or len(city_query.split()) > 3):
        print("🔧 Using fallback location from frontend because city_from_prompt is empty or looks invalid")
        city_name = location.get("name")
        if city_name:
            prompt_metadata["city"] = city_name
            prompt_metadata["timezone"] = location.get("tz_id")
            prompt_metadata["lat"] = location.get("lat")
            prompt_metadata["lon"] = location.get("lon")
            prompt_metadata["location_used"] = "fallback:frontend_location"
            city_query = city_name
            city_from_gpt = None
            print(f"📍 Fallback city_query from frontend: {city_query}")
        else:
            print("⚠️ Location object present but missing 'name'")

    # Step 4: Reverse-geocode lat/lon if still no valid city
    if not city_query and location:
        lat, lon = location.get("lat"), location.get("lon")
        if lat is not None and lon is not None:
            city_query = reverse_geolocate(lat, lon)
            print(f"🎯 Using reverse geocoded location: {city_query}")

    # Step 5: Full geocoding fallback using full prompt
    if not city_query:
        lat, lon, full = get_geolocation(prompt_text)
        if lat and lon:
            city_query = full
            print(f"🎯 Fallback geocoding result: {city_query}")

    # Step 6: Error out if no city found
    if not city_query:
        return {"error": "City not found."}

    print(f"🌍 Final city_query: {city_query}")

    # Step 7: Agent creation (stubbed)
    agent_msg = check_and_create_agent(parsed, location, user_id="anon123")
    if agent_msg:
        print(agent_msg)

    # Step 8: Get weather data
    result = get_full_weather_summary(city_query, user_prompt=prompt_text, timezone_offset=0)
    result["parsed_prompt"] = parsed
    return result
