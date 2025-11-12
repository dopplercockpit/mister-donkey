# dopplertower_engine.py (FIXED VERSION)
# Fixes: Added tone selector functionality (Issue #2)

import requests
from datetime import datetime, timedelta, timezone
from openai import OpenAI
import os
import math
from io import BytesIO
from PIL import Image

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
WEATHERAPI_KEY = os.getenv("WEATHERAPI_KEY")

OPENWEATHER_URL = "http://api.openweathermap.org/data/2.5"
WEATHERAPI_URL = "http://api.weatherapi.com/v1"

from config import OPENAI_MODEL  # shared config 

# NEW: Tone definitions for personality selector
TONE_PRESETS = {
    "sarcastic": {
        "system_prompt": "You're Mister Donkey, a brutally sarcastic, emoji-loving, profanity-capable weather assistant who delivers accurate forecasts with maximum snark and sass. You roast people for asking obvious questions, make fun of weather conditions, and don't hold back. Use emojis liberally 🙄💀🌧️☀️",
        "style": "sarcastic, snarky, roasting"
    },
    "pirate": {
        "system_prompt": "You're Mister Donkey, a swashbuckling pirate weather captain who delivers forecasts in pirate speak. Use 'arr', 'matey', 'ye', 'aye', talk about the seven seas, storms on the horizon, and treasure (sunshine). Use maritime and pirate emojis 🏴‍☠️⚓🌊⛵",
        "style": "pirate speak, maritime references"
    },
    "professional": {
        "system_prompt": "You're Mister Donkey, a professional meteorologist who delivers accurate, clear weather forecasts with occasional witty observations. You're informative, helpful, and slightly playful. Use weather emojis appropriately 🌡️📊☁️",
        "style": "professional, informative, helpful"
    },
    "hippie": {
        "system_prompt": "You're Mister Donkey, a laid-back hippie weather guru who sees weather as cosmic energy and natural vibes. You use phrases like 'far out', 'groovy', 'cosmic', reference Mother Nature, the universe, good vibes, and peace. Use chill emojis ☮️🌈✌️🌻",
        "style": "hippie, cosmic, peaceful"
    },
    "drill_sergeant": {
        "system_prompt": "You're Mister Donkey, a hard-ass drill sergeant delivering weather briefings like military orders. You're tough, no-nonsense, yell in ALL CAPS sometimes, and treat weather preparation like a military operation. Use military emojis 💪🎖️⚠️",
        "style": "military, commanding, tough"
    },
    "gen_z": {
        "system_prompt": "You're Mister Donkey, a Gen Z weather assistant who speaks in current slang, references memes, uses 'bestie', 'fr fr', 'no cap', 'slay', 'vibe check', etc. You're chronically online and relate everything to TikTok trends. Heavy emoji usage 💅✨🔥",
        "style": "Gen Z slang, memes, internet culture"
    },
    "noir_detective": {
        "system_prompt": "You're Mister Donkey, a 1940s noir detective who delivers weather reports like you're investigating a crime scene. Use noir phrases, talk about shadows, mysteries, and weather 'clues'. Dark and moody. Use detective emojis 🕵️🌃🚬",
        "style": "noir detective, mysterious, dramatic"
    },
    "shakespeare": {
        "system_prompt": "You're Mister Donkey, delivering weather forecasts in Shakespearean English. Use thee, thou, art, wherefore, hath, etc. Make weather sound like poetry or tragedy. Use classical emojis 🎭📜✨",
        "style": "Shakespearean, poetic, dramatic"
    }
}

def search_city_with_weatherapi(query):
    """
    Search for a city using both OpenWeather and WeatherAPI.
    Returns city info with coordinates.
    """
    # 1) Try OpenWeather Direct Geocoding (supports state codes, etc.)
    gw_url = (
        f"http://api.openweathermap.org/geo/1.0/direct"
        f"?q={query}&limit=5&appid={OPENWEATHER_API_KEY}"
    )
    r = requests.get(gw_url)
    if r.status_code == 200:
        data = r.json()
        for c in data:
            # Filter for US or Canada if it's a US-style location (like "Rock, Michigan")
            if "country" in c and c["country"] in ["US", "CA"]:
                return {
                    "name":       c.get("name"),
                    "region":     c.get("state", ""),
                    "country":    c.get("country", ""),
                    "lat":        c.get("lat"),
                    "lon":        c.get("lon"),
                    "full_name":  ", ".join(filter(None, [c.get("name"), c.get("state"), c.get("country")]))
                }
        # fallback: just return the first one if nothing matches above
        if data:
            c = data[0]
            return {
                "name":       c.get("name"),
                "region":     c.get("state", ""),
                "country":    c.get("country", ""),
                "lat":        c.get("lat"),
                "lon":        c.get("lon"),
                "full_name":  ", ".join(filter(None, [c.get("name"), c.get("state"), c.get("country")]))
            }

    # 2) Fallback to WeatherAPI search.json
    wa_url = f"{WEATHERAPI_URL}/search.json?key={WEATHERAPI_KEY}&q={query}"
    resp = requests.get(wa_url)
    if resp.status_code == 200:
        results = resp.json()
        if results:
            city = results[0]
            return {
                "name":       city["name"],
                "region":     city["region"],
                "country":    city["country"],
                "lat":        city["lat"],
                "lon":        city["lon"],
                "full_name":  f"{city['name']}, {city['region']}, {city['country']}"
            }
    return None

def celsius_to_fahrenheit(c):
    return round((c * 9/5) + 32) if isinstance(c, (int, float)) else "N/A"

def convert_wind_speed(mps):
    return round(mps * 3.6), round(mps * 2.23694) if isinstance(mps, (int, float)) else ("N/A", "N/A")

def get_openweather_current(lat, lon):
    url = f"{OPENWEATHER_URL}/weather?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}&units=metric"
    return requests.get(url).json()

def get_openweather_forecast(lat, lon):
    url = f"{OPENWEATHER_URL}/forecast?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}&units=metric"
    return requests.get(url).json()

def get_air_quality(lat, lon):
    url = f"{OPENWEATHER_URL}/air_pollution?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}"
    data = requests.get(url).json()
    aqi_map = {1: "🟢 Good", 2: "🟡 Fair", 3: "🟠 Moderate", 4: "🔴 Poor 😷", 5: "🟣 Very Poor ☠️"}
    if data.get("list"):
        return aqi_map.get(data["list"][0]["main"]["aqi"], "Unknown")
    return "Unknown"

def get_weather_alerts(lat, lon):
    url = f"{WEATHERAPI_URL}/alerts.json?key={WEATHERAPI_KEY}&q={lat},{lon}"
    response = requests.get(url)

    try:
        data = response.json()
    except Exception as e:
        print(f"❌ Failed to parse alerts JSON for {lat},{lon}: {e}")
        return []

    print(f"🌩️ RAW ALERTS for {lat},{lon}: {data}")

    alerts = data.get("alerts", {}).get("alert", [])
    return alerts if alerts else []

def get_three_day_forecast(lat, lon):
    url = f"{WEATHERAPI_URL}/forecast.json?key={WEATHERAPI_KEY}&q={lat},{lon}&days=3"
    response = requests.get(url)
    return response.json()

def get_historical_weather(lat, lon, date_str):
    url = f"{WEATHERAPI_URL}/history.json?key={WEATHERAPI_KEY}&q={lat},{lon}&dt={date_str}"
    response = requests.get(url)
    return response.json()

def generate_summary_prompt(user_prompt, current, forecast_lines, aqi, alerts, tone="sarcastic"):
    """
    NEW: Now supports tone parameter!
    """
    tone_config = TONE_PRESETS.get(tone, TONE_PRESETS["sarcastic"])
    current_main = current.get("main", {})
    
    return (
        f"{tone_config['system_prompt']}\n\n"
        f"User prompt: {user_prompt}\n"
        f"Current: {current_main.get('temp')}°C, feels like {current_main.get('feels_like')}°C\n"
        f"Conditions: {current.get('weather',[{}])[0].get('description','')}\n"
        f"Wind: {current.get('wind',{}).get('speed')} m/s\n"
        f"AQI: {aqi}\n"
        f"Forecast: {'; '.join(forecast_lines)}\n"
        f"Alerts: {len(alerts)} active\n"
        f"Deliver your response in the style: {tone_config['style']}\n"
        f"End with your signature sign-off for this personality.\n"
    )


def detect_alert_worthy_changes(current, forecast):
    if not forecast.get("list"):
        return ""

    changes = []
    current_temp = current.get("main", {}).get("temp")
    current_conditions = current.get("weather", [{}])[0].get("main", "")

    for item in forecast["list"][:3]:
        f_temp = item.get("main", {}).get("temp")
        f_conditions = item.get("weather", [{}])[0].get("main", "")
        f_time = datetime.utcfromtimestamp(item["dt"]).strftime("%H:%M")

        if current_temp and f_temp and abs(f_temp - current_temp) >= 5:
            changes.append(f"⚠️ Temp change: {round(current_temp)}°C ➡ {round(f_temp)}°C by {f_time}")

        if current_conditions != f_conditions:
            if "Rain" in f_conditions and "Rain" not in current_conditions:
                changes.append(f"☔ Rain expected around {f_time}")
            elif "Rain" not in f_conditions and "Rain" in current_conditions:
                changes.append(f"🌤️ Rain should stop around {f_time}")

    return "\n".join(changes)

def parse_weather_alerts(alerts):
    if not alerts or "alert" not in alerts or not alerts["alert"]:
        return ""

    summaries = []
    for alert in alerts["alert"]:
        event = alert.get("event", "⚠️ Weather Alert")
        area = alert.get("area", "")
        desc = alert.get("desc", "")
        effective = alert.get("effective", "")
        summaries.append(f"🚨 {event} in {area} starting {effective}: {desc[:200]}...")

    return "\n".join(summaries)

def get_full_weather_summary_by_coords(
    lat: float, 
    lon: float, 
    display_name: str = None, 
    user_prompt: str = "", 
    timezone_offset: int = 0,
    tone: str = "sarcastic",  # NEW: Tone parameter
    conversation_history: list = None  # NEW: For conversation continuity
) -> dict:
    """
    The 'no bullshit' path: you give me lat/lon, I fetch everything precisely for that point.
    NEW: Supports tone selection and conversation history!
    """
    from geo_utils_helper import reverse_geolocate

    # Validate
    if lat is None or lon is None:
        return {"error": "Missing coordinates."}

    # Pull data by coords
    current = get_openweather_current(lat, lon)
    forecast = get_openweather_forecast(lat, lon)
    aqi = get_air_quality(lat, lon)
    alerts = get_weather_alerts(lat, lon)
    forecast_text = get_three_day_forecast(lat, lon)
    hist_date = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
    history = get_historical_weather(lat, lon, hist_date)

    # Pretty location name
    if not display_name:
        try:
            display_name = reverse_geolocate(lat, lon)
        except Exception:
            display_name = f"{lat:.3f}, {lon:.3f}"

    # Build text for GPT
    alerts_summary_forecast = "\n".join(forecast_text) if isinstance(forecast_text, list) else str(forecast_text)
    alerts_summary_severe = parse_weather_alerts({"alert": alerts})
    alerts_summary = "\n".join(filter(None, [alerts_summary_severe, alerts_summary_forecast]))

    summary_input = f"""Location: {display_name}
Lat/Lon: {lat}, {lon}

Current:
{current}

Forecast (5-day):
{forecast}

Air Quality:
{aqi}

Alerts:
{alerts}

Recent History (yesterday):
{history}

User prompt context:
{user_prompt}
"""

    client = OpenAI(api_key=OPENAI_API_KEY)

    # Get tone configuration
    tone_config = TONE_PRESETS.get(tone, TONE_PRESETS["sarcastic"])
    
    # Build messages with conversation history if provided
    messages = [
        {"role": "system", "content": tone_config["system_prompt"]}
    ]
    
    # Add conversation history if it exists
    if conversation_history:
        messages.extend(conversation_history)
    
    # Add current request
    messages.append({"role": "user", "content": summary_input})

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        max_tokens=906
    )
    gpt_summary = response.choices[0].message.content

    return {
        "location": display_name,
        "coords": {"lat": lat, "lon": lon},
        "current": current,
        "forecast": forecast,
        "air_quality": aqi,
        "alerts": alerts,
        "history": history,
        "summary": gpt_summary,
        "tone": tone  # Return the tone that was used
    }


def get_full_weather_summary(
    city_query, 
    user_prompt="", 
    timezone_offset=0, 
    tone="sarcastic",  # NEW
    conversation_history=None  # NEW
):
    """
    Legacy function - redirects to coordinate-based version for consistency.
    """
    city_info = search_city_with_weatherapi(city_query)
    if not city_info:
        return {"error": f"City not found: {city_query}"}
    
    lat, lon = city_info["lat"], city_info["lon"]
    display = city_info.get("full_name") or city_query
    
    # Delegate to the coordinate-based function
    result = get_full_weather_summary_by_coords(
        lat, lon, 
        display_name=display, 
        user_prompt=user_prompt, 
        timezone_offset=timezone_offset,
        tone=tone,  # Pass tone through
        conversation_history=conversation_history  # Pass conversation through
    )
    
    # Add city info
    result["city"] = city_info["full_name"]
    
    return result


# NEW: Helper function to get available tones
def get_available_tones():
    """Returns list of available tone presets with descriptions"""
    return {
        key: {
            "name": key.replace("_", " ").title(),
            "description": config["system_prompt"][:100] + "..."
        }
        for key, config in TONE_PRESETS.items()
    }