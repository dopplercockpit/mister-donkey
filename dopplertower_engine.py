# dopplertower_engine.py (FIXED VERSION)
# Fixes: Added tone selector functionality (Issue #2)
# NEW: Integrated news context fetching for location-aware personality responses

import requests
from datetime import datetime, timedelta, timezone
from functools import wraps
from openai import OpenAI
import os
import math
from io import BytesIO
from PIL import Image
import time
from news_fetcher import get_location_news, format_news_for_prompt, extract_country_code
from logger_config import setup_logger, log_llm_call

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
WEATHERAPI_KEY = os.getenv("WEATHERAPI_KEY")

OPENWEATHER_URL = "http://api.openweathermap.org/data/2.5"
WEATHERAPI_URL = "http://api.weatherapi.com/v1"

from config import OPENAI_MODEL  # shared config

# ─── TTL Cache ────────────────────────────────────────────────────────────────
_CACHE_TTL = 600  # 10 minutes

_cache: dict = {}
_stats: dict = {"hits": 0, "misses": 0, "by_endpoint": {}}


def _ttl_cache(name: str, ttl: int = _CACHE_TTL):
    """Decorator: caches (lat, lon) results with a TTL, keyed by (name, round(lat,2), round(lon,2))."""
    _stats["by_endpoint"][name] = {"hits": 0, "misses": 0}

    def decorator(fn):
        @wraps(fn)
        def wrapper(lat: float, lon: float):
            key = (name, round(lat, 2), round(lon, 2))
            entry = _cache.get(key)
            if entry is not None:
                data, ts = entry
                if time.time() - ts < ttl:
                    _stats["hits"] += 1
                    _stats["by_endpoint"][name]["hits"] += 1
                    print(f"💾 Cache hit: {name} ({round(lat, 2):.2f}, {round(lon, 2):.2f})")
                    return data
                del _cache[key]
            _stats["misses"] += 1
            _stats["by_endpoint"][name]["misses"] += 1
            data = fn(lat, lon)
            _cache[key] = (data, time.time())
            return data
        return wrapper
    return decorator


def cache_stats() -> dict:
    """Return cache hit/miss counts and per-endpoint breakdown."""
    total = _stats["hits"] + _stats["misses"]
    return {
        "hits": _stats["hits"],
        "misses": _stats["misses"],
        "total_requests": total,
        "hit_rate_pct": round(_stats["hits"] / total * 100, 1) if total else 0.0,
        "cached_entries": len(_cache),
        "ttl_seconds": _CACHE_TTL,
        "by_endpoint": _stats["by_endpoint"],
    }

# ─────────────────────────────────────────────────────────────────────────────

# Setup logger
logger = setup_logger("mister_donkey.engine") 

# NEW: Tone definitions for personality selector
# Updated with news context integration instructions
NEWS_CONTEXT_INSTRUCTION = "\n\nIMPORTANT: If 'Recent News Headlines' are provided in the context, weave them seamlessly into your weather report in your unique style. If the weather is bad/challenging, compare it favorably to the news situation (e.g., 'At least the rain is more predictable than the politics'). If the weather is good, mention it's perhaps the only good thing happening there. Make it feel natural to your personality - don't announce you're referencing news, just blend it in organically."

TONE_PRESETS = {
    "sarcastic": {
        "name": "Mister Donkey",
        "short_description": "Blunt, sharp, weather with attitude.",
        "system_prompt": f"You're Mister Donkey, a brutally sarcastic, emoji-loving, profanity-prone weather assistant who delivers accurate forecasts with maximum snark and sass. You roast people for asking obvious questions, make fun of weather conditions, and don't hold back. Use emojis liberally 🙄💀🌧️☀️{NEWS_CONTEXT_INSTRUCTION}",
        "style": "sarcastic, sassy, snarky, roasting"
    },
    "pirate": {
        "name": "Buccaneer Donkey",
        "short_description": "Ahoy! Weather on the high seas.",
        "system_prompt": f"You're Buccaneer Donkey, a swashbuckling buccaneer sea captain who delivers forecasts in funny pirate speak. Use words like 'ahoy', 'matey', 'aye', talk about the seven seas, storms on the horizon, and treasure (sunshine). Use maritime and pirate references and emojis 🏴‍☠️⚓🌊⛵{NEWS_CONTEXT_INSTRUCTION}",
        "style": "pirate speak, maritime references, humorous"
    },
    "professional": {
        "name": "Executive Donkey",
        "short_description": "Clear forecasts, boardroom confidence.",
        "system_prompt": f"You're Executive Donkey, a humorous professional business executive who delivers accurate, clear weather forecasts with occasional witty observations. You're informative, helpful, and slightly playful. Use weather emojis appropriately 🌡️📊☁️{NEWS_CONTEXT_INSTRUCTION}",
        "style": "professional, business, informative, helpful"
    },
    "hippie": {
        "name": "Far Out Donkey",
        "short_description": "Cosmic vibes, groovy forecasts.",
        "system_prompt": f"You're Far Out Donkey, a laid-back hippie weather guru who sees weather as cosmic energy and natural vibes. You use phrases like 'far out', 'groovy', 'cosmic', reference Mother Nature, the universe, good vibes, and peace. Use chill emojis ☮️🌈✌️🌻{NEWS_CONTEXT_INSTRUCTION}",
        "style": "hippie, cosmic, peaceful"
    },
    "drill_sergeant": {
        "name": "Drill Sergeant Donkey",
        "short_description": "Weather briefings like military orders.",
        "system_prompt": f"You're Drill Sergeant Donkey, a hard-ass drill sergeant delivering weather briefings like military orders. You're tough, no-nonsense, yell in ALL CAPS sometimes, and treat weather preparation like a military operation. Use military emojis 💪🎖️⚠️{NEWS_CONTEXT_INSTRUCTION}",
        "style": "military, commanding, tough"
    },
    "gen_z": {
        "name": "Fluid Donkey",
        "short_description": "No cap, this forecast slaps fr fr.",
        "system_prompt": f"You're Fluid Donkey, a Gen Z weather assistant who speaks in current slang, references memes, uses 'bestie', 'fr fr', 'no cap', 'slay', 'vibe check', etc. You're chronically online and relate everything to TikTok trends. Heavy emoji usage 💅✨🔥{NEWS_CONTEXT_INSTRUCTION}",
        "style": "Gen Z slang, memes, internet culture"
    },
    "noir_detective": {
        "name": "Detective Donkey",
        "short_description": "Moody, shadowy, weather as a crime scene.",
        "system_prompt": f"You're Detective Donkey, a 1940s noir detective who delivers weather reports like you're investigating a crime scene. Use noir phrases, talk about shadows, mysteries, and weather 'clues'. Dark and moody. Use detective emojis 🕵️🌃🚬{NEWS_CONTEXT_INSTRUCTION}",
        "style": "noir detective, mysterious, dramatic"
    },
    "shakespeare": {
        "name": "Theatre Donkey",
        "short_description": "Hark! The forecast speaketh in verse.",
        "system_prompt": f"You're Theatre Donkey, a stage director delivering weather forecasts in Shakespearean English. Use thee, thou, art, wherefore, hath, etc. Make weather sound like poetry or tragedy. Use classical emojis 🎭📜✨{NEWS_CONTEXT_INSTRUCTION}",
        "style": "Shakespearean, poetic, dramatic"
    }
}

def search_city_with_weatherapi(query, user_lat=None, user_lon=None):
    """
    Search for a city using intelligent disambiguation.
    Returns city info with coordinates.

    Args:
        query: City name to search for
        user_lat: User's latitude for proximity scoring (optional)
        user_lon: User's longitude for proximity scoring (optional)

    NEW: Uses city_disambiguator for smart city resolution instead of
    blindly returning first US/CA result!
    """
    # Import the smart disambiguator
    from city_disambiguator import disambiguate_city

    # Use the disambiguator which properly scores results by:
    # - Exact name match
    # - Proximity to user (if lat/lon provided)
    # - Country/region popularity
    # - Source reliability
    result = disambiguate_city(query, lat=user_lat, lon=user_lon, return_all=False)

    if result:
        return {
            "name":       result.get("name"),
            "region":     result.get("region", ""),
            "country":    result.get("country", ""),
            "lat":        result.get("lat"),
            "lon":        result.get("lon"),
            "full_name":  ", ".join(filter(None, [result.get("name"), result.get("region"), result.get("country")])),
            "score":      result.get("score"),  # Include score for debugging
            "source":     result.get("source")   # Include source for debugging
        }

    return None

def celsius_to_fahrenheit(c):
    return round((c * 9/5) + 32) if isinstance(c, (int, float)) else "N/A"

def convert_wind_speed(mps):
    return round(mps * 3.6), round(mps * 2.23694) if isinstance(mps, (int, float)) else ("N/A", "N/A")

@_ttl_cache("openweather_current")
def get_openweather_current(lat, lon):
    url = f"{OPENWEATHER_URL}/weather?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}&units=metric"
    return requests.get(url).json()

@_ttl_cache("openweather_forecast")
def get_openweather_forecast(lat, lon):
    url = f"{OPENWEATHER_URL}/forecast?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}&units=metric"
    return requests.get(url).json()

@_ttl_cache("air_quality")
def get_air_quality(lat, lon):
    url = f"{OPENWEATHER_URL}/air_pollution?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}"
    data = requests.get(url).json()
    aqi_map = {1: "🟢 Good", 2: "🟡 Fair", 3: "🟠 Moderate", 4: "🔴 Poor 😷", 5: "🟣 Very Poor ☠️"}
    if data.get("list"):
        return aqi_map.get(data["list"][0]["main"]["aqi"], "Unknown")
    return "Unknown"

@_ttl_cache("weather_alerts")
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

@_ttl_cache("weatherapi_forecast")
def get_three_day_forecast(lat, lon):
    url = f"{WEATHERAPI_URL}/forecast.json?key={WEATHERAPI_KEY}&q={lat},{lon}&days=3"
    try:
        return requests.get(url, timeout=8).json()
    except Exception:
        return {}


def get_hourly_forecast(lat: float, lon: float) -> list:
    """Return the next 12 hours of WeatherAPI hourly data as processed dicts.

    Re-uses the cached get_three_day_forecast result so no extra HTTP call.
    """
    data = get_three_day_forecast(lat, lon)
    now = datetime.now()
    now_epoch = int(now.timestamp())

    all_hours: list = []
    for day in data.get("forecast", {}).get("forecastday", [])[:2]:
        all_hours.extend(day.get("hour", []))

    # Keep only hours from the current hour onward (allow 30-min past)
    future = [h for h in all_hours if h.get("time_epoch", 0) >= now_epoch - 1800]

    result = []
    for h in future[:12]:
        cond = h.get("condition", {})
        time_str = h.get("time", "")
        try:
            dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
            hi = dt.hour
            if hi == 0:
                label = "12am"
            elif hi < 12:
                label = f"{hi}am"
            elif hi == 12:
                label = "12pm"
            else:
                label = f"{hi - 12}pm"
            is_current = -1800 < (dt - now).total_seconds() < 3600
        except Exception:
            label = time_str[-5:] if len(time_str) >= 5 else "?"
            is_current = False

        precip = max(int(h.get("chance_of_rain", 0)), int(h.get("chance_of_snow", 0)))
        result.append({
            "time": time_str,
            "hour_label": label,
            "temp_c": h.get("temp_c"),
            "temp_f": h.get("temp_f"),
            "conditions": cond.get("text", ""),
            "condition_code": cond.get("code"),
            "precip_chance": precip,
            "is_current": is_current,
        })

    return result

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
    conversation_history: list = None,  # NEW: For conversation continuity
    structured: bool = False  # NEW: Return structured format if True
) -> dict:
    """
    The 'no bullshit' path: you give me lat/lon, I fetch everything precisely for that point.
    NEW: Supports tone selection, conversation history, and structured responses!

    Args:
        structured: If True, returns format_structured_weather_response() output
                   If False, returns legacy format (backward compatible)
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

    # NEW: Fetch news context for location
    country_code = extract_country_code(display_name)
    news_articles = get_location_news(display_name, country_code=country_code, max_results=3)
    news_context = format_news_for_prompt(news_articles)

    # Build text for GPT
    alerts_summary_forecast = "\n".join(forecast_text) if isinstance(forecast_text, list) else str(forecast_text)
    alerts_summary_severe = parse_weather_alerts({"alert": alerts})
    alerts_summary = "\n".join(filter(None, [alerts_summary_severe, alerts_summary_forecast]))

    # Build GPT prompt with news context if available
    news_section = f"\n\nRecent News Headlines:\n{news_context}" if news_context else ""

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
{history}{news_section}

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

    # Call OpenAI with logging
    start_time = time.time()
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        max_tokens=906
    )
    duration_ms = (time.time() - start_time) * 1000

    gpt_summary = response.choices[0].message.content

    # Log LLM call with token usage
    total_tokens = response.usage.total_tokens if response.usage else 0
    # Rough cost estimate for gpt-4o-mini: $0.15/1M input, $0.60/1M output tokens
    cost_estimate = (total_tokens / 1_000_000) * 0.30  # Average cost
    log_llm_call(OPENAI_MODEL, total_tokens, cost_estimate, "success", f"{display_name} | {tone} | {duration_ms:.0f}ms")

    # Build raw response
    raw_response = {
        "location": display_name,
        "coords": {"lat": lat, "lon": lon},
        "current": current,
        "forecast": forecast,
        "air_quality": aqi,
        "alerts": alerts,
        "history": history,
        "news": news_articles,
        "summary": gpt_summary,
        "tone": tone,
        "hourly": get_hourly_forecast(lat, lon),  # next 12 hours from WeatherAPI cache
    }

    # Return structured format if requested, otherwise return legacy format
    if structured:
        return format_structured_weather_response(raw_response)
    else:
        return raw_response


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


def generate_summary_stream(
    lat: float,
    lon: float,
    display_name: str = None,
    user_prompt: str = "",
    tone: str = "sarcastic",
    conversation_history: list = None,
):
    """Stream the GPT weather summary as raw text tokens.

    All upstream API calls use the TTL cache so there's no duplicate fetching
    when this is called shortly after get_full_weather_summary_by_coords.

    Yields: str tokens (not SSE-wrapped — the route handles formatting).
    """
    from geo_utils_helper import reverse_geolocate

    current = get_openweather_current(lat, lon)
    forecast = get_openweather_forecast(lat, lon)
    aqi = get_air_quality(lat, lon)
    alerts = get_weather_alerts(lat, lon)
    forecast_text = get_three_day_forecast(lat, lon)
    hist_date = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
    history = get_historical_weather(lat, lon, hist_date)

    if not display_name:
        try:
            display_name = reverse_geolocate(lat, lon)
        except Exception:
            display_name = f"{lat:.3f}, {lon:.3f}"

    country_code = extract_country_code(display_name)
    news_articles = get_location_news(display_name, country_code=country_code, max_results=3)
    news_context = format_news_for_prompt(news_articles)

    alerts_summary_forecast = "\n".join(forecast_text) if isinstance(forecast_text, list) else str(forecast_text)
    alerts_summary_severe = parse_weather_alerts({"alert": alerts})
    alerts_summary = "\n".join(filter(None, [alerts_summary_severe, alerts_summary_forecast]))
    news_section = f"\n\nRecent News Headlines:\n{news_context}" if news_context else ""

    summary_input = f"""Location: {display_name}
Lat/Lon: {lat}, {lon}

Current:
{current}

Forecast (5-day):
{forecast}

Air Quality:
{aqi}

Alerts:
{alerts_summary}

Recent History (yesterday):
{history}{news_section}

User prompt context:
{user_prompt}
"""

    tone_config = TONE_PRESETS.get(tone, TONE_PRESETS["sarcastic"])
    messages = [{"role": "system", "content": tone_config["system_prompt"]}]
    if conversation_history:
        messages.extend(conversation_history)
    messages.append({"role": "user", "content": summary_input})

    client = OpenAI(api_key=OPENAI_API_KEY)
    stream = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        max_tokens=906,
        stream=True,
    )
    for chunk in stream:
        token = chunk.choices[0].delta.content
        if token is not None:
            yield token


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


# NEW: Structured response formatter for Phase 3
def format_structured_weather_response(raw_response: dict) -> dict:
    """
    Transform raw weather response into structured JSON format.
    Provides both text summary AND structured data for rich UI.

    Args:
        raw_response: Output from get_full_weather_summary_by_coords()

    Returns:
        Structured response with separate sections for text, weather, news, metadata
    """
    current = raw_response.get("current", {})
    forecast = raw_response.get("forecast", {})
    alerts = raw_response.get("alerts", [])
    news_articles = raw_response.get("news", [])

    # Extract simplified current conditions
    current_main = current.get("main", {})
    current_weather = current.get("weather", [{}])[0]
    current_wind = current.get("wind", {})

    # Extract 3-day simplified forecast
    forecast_list = forecast.get("list", [])
    forecast_3day = extract_3day_forecast(forecast_list)

    # Format alerts
    formatted_alerts = format_alerts_structured(alerts)

    return {
        "text_summary": raw_response.get("summary", ""),
        "summary": raw_response.get("summary", ""),       # legacy alias
        "weather": {
            "hourly": raw_response.get("hourly", []),
            "current": {
                "temp_c": current_main.get("temp"),
                "temp_f": celsius_to_fahrenheit(current_main.get("temp")),
                "feels_like_c": current_main.get("feels_like"),
                "feels_like_f": celsius_to_fahrenheit(current_main.get("feels_like")),
                "conditions": current_weather.get("description", "").title(),
                "conditions_code": current_weather.get("main", ""),
                "icon": map_weather_icon(current_weather.get("main", "")),
                "humidity": current_main.get("humidity"),
                "pressure": current_main.get("pressure"),
                "wind_speed_ms": current_wind.get("speed"),
                "wind_speed_kmh": round(current_wind.get("speed", 0) * 3.6, 1),
                "wind_speed_mph": round(current_wind.get("speed", 0) * 2.237, 1),
                "wind_direction": current_wind.get("deg"),
                "visibility_m": current.get("visibility"),
                "clouds_percent": current.get("clouds", {}).get("all")
            },
            "forecast_3day": forecast_3day,
            "alerts": formatted_alerts,
            "air_quality": raw_response.get("air_quality", "Unknown")
        },
        "news": {
            "articles": news_articles[:3],  # Top 3 articles
            "has_context": len(news_articles) > 0,
            "count": len(news_articles)
        },
        "metadata": {
            "location": raw_response.get("location", ""),
            "coords": raw_response.get("coords", {}),
            "tone": raw_response.get("tone", "sarcastic"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "has_alerts": len(formatted_alerts) > 0,
            "has_news": len(news_articles) > 0
        },
        # Keep raw data for debugging/advanced use
        "raw": {
            "current": current,
            "forecast": forecast,
            "alerts": alerts,
            "history": raw_response.get("history")
        }
    }


def extract_3day_forecast(forecast_list: list) -> list:
    """
    Extract simplified 3-day forecast from OpenWeather 5-day/3-hour forecast.

    Args:
        forecast_list: List of forecast entries from OpenWeather API

    Returns:
        List of 3 daily forecast dicts with high/low temps, conditions, icon
    """
    if not forecast_list:
        return []

    # Group by day
    daily_data = {}

    for entry in forecast_list[:24]:  # Look at next 72 hours (3 days)
        dt = datetime.fromtimestamp(entry["dt"], tz=timezone.utc)
        date_key = dt.strftime("%Y-%m-%d")

        if date_key not in daily_data:
            daily_data[date_key] = {
                "date": date_key,
                "day_name": dt.strftime("%A"),
                "temps": [],
                "conditions": [],
                "weather_codes": []
            }

        daily_data[date_key]["temps"].append(entry["main"]["temp"])
        daily_data[date_key]["conditions"].append(entry["weather"][0]["description"])
        daily_data[date_key]["weather_codes"].append(entry["weather"][0]["main"])

    # Build 3-day forecast
    result = []
    for date_key in sorted(daily_data.keys())[:3]:
        day = daily_data[date_key]

        # Most common condition for the day
        most_common_code = max(set(day["weather_codes"]), key=day["weather_codes"].count)
        most_common_desc = max(set(day["conditions"]), key=day["conditions"].count)

        result.append({
            "date": day["date"],
            "day": day["day_name"],
            "temp_high_c": round(max(day["temps"]), 1),
            "temp_high_f": celsius_to_fahrenheit(max(day["temps"])),
            "temp_low_c": round(min(day["temps"]), 1),
            "temp_low_f": celsius_to_fahrenheit(min(day["temps"])),
            "conditions": most_common_desc.title(),
            "conditions_code": most_common_code,
            "icon": map_weather_icon(most_common_code)
        })

    return result


def format_alerts_structured(alerts: list) -> list:
    """
    Format weather alerts into structured format.

    Args:
        alerts: Raw alerts from WeatherAPI

    Returns:
        List of formatted alert dicts
    """
    if not alerts:
        return []

    formatted = []
    for alert in alerts[:5]:  # Limit to 5 most important
        formatted.append({
            "type": alert.get("event", "Weather Alert"),
            "severity": determine_alert_severity(alert.get("event", "")),
            "headline": alert.get("headline", alert.get("event", "")),
            "description": alert.get("desc", "")[:300],  # Truncate long descriptions
            "start": alert.get("effective", ""),
            "end": alert.get("expires", ""),
            "area": alert.get("area", ""),
            "urgency": alert.get("urgency", "Unknown")
        })

    return formatted


def determine_alert_severity(event_name: str) -> str:
    """Determine severity level from alert event name."""
    event_lower = event_name.lower()

    if any(word in event_lower for word in ["warning", "tornado", "hurricane", "severe"]):
        return "high"
    elif any(word in event_lower for word in ["watch", "advisory", "flood"]):
        return "moderate"
    else:
        return "low"


def map_weather_icon(weather_code: str) -> str:
    """
    Map OpenWeather condition codes to emoji icons.

    Args:
        weather_code: OpenWeather main weather condition (e.g., "Rain", "Clear")

    Returns:
        Emoji representing the weather condition
    """
    icon_map = {
        "Clear": "☀️",
        "Clouds": "☁️",
        "Rain": "🌧️",
        "Drizzle": "🌦️",
        "Thunderstorm": "⛈️",
        "Snow": "❄️",
        "Mist": "🌫️",
        "Smoke": "💨",
        "Haze": "🌫️",
        "Dust": "💨",
        "Fog": "🌫️",
        "Sand": "💨",
        "Ash": "🌋",
        "Squall": "💨",
        "Tornado": "🌪️"
    }

    return icon_map.get(weather_code, "🌤️")