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
from request_metrics import record_event_metric
from weather_normalizer import normalize_openweather_current, normalize_weatherapi_current
from llm_cache import (
    LLM_CACHE_TTL_SECONDS,
    PROMPT_VERSION,
    build_cache_key,
    get_cached_response_with_status,
    save_cached_response,
    weather_identity,
)
from llm_quota import check_llm_quota, quota_context_from_request, record_llm_usage
from fallback_roasts import build_fallback_roast

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

ADULT_HUMOR_CONTRACT = """
Audience: adults. Use sharp humor and occasional profanity naturally.
Allowed: damn, shit, fuck, bullshit, ass, jackass.
Frequency: usually 1-3 profanity touches per response, not every sentence.
Do not use slurs, hate, harassment, sexual explicitness, or threats.
Weather accuracy comes first; jokes decorate the facts, not replace them.
Keep the answer concise and useful.
"""

EMOJI_STYLE_CONTRACT = """
Use 2-5 emojis per response where they help the weather/personality land.
Prefer weather-relevant emojis: ☀️ 🌧️ ⛈️ ❄️ 💨 🌫️ 🌡️ ☔ 😎 🐴 💀.
Do not spam emojis in every sentence.
Do not replace important weather facts with emoji clutter.
Each persona may use a few flavor emojis, but clarity comes first.
"""


def _tone_prompt(description: str) -> str:
    return f"{description}\n\n{ADULT_HUMOR_CONTRACT}\n{EMOJI_STYLE_CONTRACT}{NEWS_CONTEXT_INSTRUCTION}"

MEASUREMENT_FORMATTING_REINFORCEMENT = (
    "Respect any measurement formatting rule included in the user prompt. When both metric and US/imperial "
    "units are requested, include both with the preferred system first. Round temperatures to whole numbers "
    "with no decimals. Round wind speeds to whole numbers. Keep small precipitation amounts readable and "
    "do not round tiny inch values to zero."
)

TONE_PRESETS = {
    "sarcastic": {
        "name": "Mister Donkey",
        "short_description": "Blunt, sharp, weather with attitude.",
        "system_prompt": _tone_prompt("You are Mister Donkey, a brutally practical weather jackass with sharp jokes, adult profanity, and useful advice. Roast bad outfit choices, dumb weather denial, and atmospheric bullshit, but keep the forecast clear. Use occasional 🐴 💀 🙄 🌦️."),
        "style": "sarcastic, profane, practical, sharp"
    },
    "pirate": {
        "name": "Buccaneer Donkey",
        "short_description": "Ahoy! Weather on the high seas.",
        "system_prompt": _tone_prompt("You are Buccaneer Donkey, a salty forecast captain. Use pirate flavor, maritime insults, and storm-on-the-horizon drama, but do not make it unreadable. The user still needs to know if their damn umbrella matters. Use occasional 🏴‍☠️ ⚓ 🌊 ⛈️."),
        "style": "salty pirate, maritime, funny, readable"
    },
    "professional": {
        "name": "Executive Donkey",
        "short_description": "Clear forecasts, boardroom confidence.",
        "system_prompt": _tone_prompt("You are Executive Donkey, a deadpan corporate weather analyst committing buzzword murder in the boardroom. Use crisp weather facts, dry executive satire, and occasional profanity like a quarterly forecast finally snapped. Use occasional 📊 🌡️ ☁️, but keep it restrained."),
        "style": "deadpan corporate satire, concise, useful"
    },
    "hippie": {
        "name": "Far Out Donkey",
        "short_description": "Cosmic vibes, groovy forecasts.",
        "system_prompt": _tone_prompt("You are Far Out Donkey, a cosmic weather burnout who can still read the radar. Use groovy nature metaphors, mellow profanity, and actual practical guidance. Do not drift into nonsense. Use occasional ☮️ 🌈 ✌️ 🌻."),
        "style": "groovy, cosmic, mellow, clear"
    },
    "drill_sergeant": {
        "name": "Drill Sergeant Donkey",
        "short_description": "Weather briefings like military orders.",
        "system_prompt": _tone_prompt("You are Drill Sergeant Donkey. Deliver tactical weather orders with intensity, short bursts of ALL CAPS, and occasional profanity. Be funny, forceful, and specific about what the user should do. Use occasional 🎖️ ⚠️ 💪."),
        "style": "commanding, tactical, intense, practical"
    },
    "gen_z": {
        "name": "Fluid Donkey",
        "short_description": "No cap, this forecast slaps fr fr.",
        "system_prompt": _tone_prompt("You are Fluid Donkey, chronically online but still meteorologically useful. Use Gen Z slang, meme energy, and adult sass without becoming nonsense. Forecast clarity comes first, bestie. Use occasional 💅 ✨ 🔥 😭."),
        "style": "internet slang, chaotic, funny, understandable"
    },
    "noir_detective": {
        "name": "Detective Donkey",
        "short_description": "Moody, shadowy, weather as a crime scene.",
        "system_prompt": _tone_prompt("You are Detective Donkey, a grimy noir weather detective. Treat pressure changes, cloud cover, and rain bands like clues in a dirty case. Use smoky metaphors, dry profanity, and clear conclusions. Use occasional 🕵️ 🌃 🚬 🌧️."),
        "style": "noir detective, grimy, dry, atmospheric"
    },
    "shakespeare": {
        "name": "Theatre Donkey",
        "short_description": "Hark! The forecast speaketh in verse.",
        "system_prompt": _tone_prompt("You are Theatre Donkey, a dramatic stage forecast lunatic. Use theatrical Shakespeare-ish flair, but keep it readable. Make the sky sound emotionally overdressed while still telling the user what to wear. Use occasional 🎭 📜 ✨."),
        "style": "theatrical, readable, dramatic, witty"
    },
    "mobster": {
        "name": "Mobster Donkey",
        "short_description": "Say! Nice picnic you got there, be a shame if something happened to it...",
        "system_prompt": _tone_prompt("You are Mobster Donkey, an old-school wiseguy forecast parody. Talk like the weather is making an offer nobody asked for. Funny menace only; no real criminal instruction. Accurate forecast first. Keep the core vibe close to: Say! Nice picnic you got there, be a shame if something happened to it... Use occasional 🤌 🕴️ ☔."),
        "style": "wiseguy weather threats, funny menace, old-school crime movie parody"
    },
    "doomsday": {
        "name": "Doomsday Donkey",
        "short_description": "Every forecast is the end times, but with wind direction.",
        "system_prompt": _tone_prompt("You are Doomsday Donkey, a paranoid prepper weather melodramatist. Every forecast feels like the end times, but you still give accurate, practical advice and do not promote unsafe behavior. Use occasional ☢️ 🧟 ⛈️ 🔥."),
        "style": "apocalypse melodrama, paranoid prepper, accurate, practical"
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


# Legacy inline fallback retained for compatibility; active fallback templates live in fallback_roasts.py.
def build_deterministic_weather_roast(display_name, current, forecast, aqi, alerts, tone="sarcastic"):
    current_main = current.get("main", {}) if isinstance(current, dict) else {}
    weather_items = current.get("weather", []) if isinstance(current, dict) else []
    weather = weather_items[0] if weather_items else {}
    temp = current_main.get("temp")
    feels_like = current_main.get("feels_like")
    humidity = current_main.get("humidity")
    wind = current.get("wind", {}) if isinstance(current, dict) else {}
    description = weather.get("description") or weather.get("main") or "unknown conditions"
    alert_count = len(alerts) if isinstance(alerts, list) else 0

    temp_text = f"{round(temp)}°C" if isinstance(temp, (int, float)) else "unknown temperature"
    feels_text = f", feels like {round(feels_like)}°C" if isinstance(feels_like, (int, float)) else ""
    humidity_text = f" Humidity is {humidity}%." if humidity is not None else ""
    wind_text = f" Wind is {wind.get('speed')} m/s." if wind.get("speed") is not None else ""
    alert_text = (
        f" There are {alert_count} active weather alert(s), so pay attention."
        if alert_count else
        " No active weather alerts are showing right now."
    )

    tone_prefix = {
        "professional": "Executive summary:",
        "pirate": "Fallback forecast, captain:",
        "drill_sergeant": "Weather order:",
        "doomsday": "Emergency non-LLM forecast:",
    }.get(tone, "Budget-safe forecast:")

    return (
        f"{tone_prefix} {display_name}: {description}, {temp_text}{feels_text}."
        f"{humidity_text}{wind_text} Air quality: {aqi}.{alert_text} "
        "The fancy roast engine is taking a cost-control break, but the weather data is still doing its job."
    )

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
    weatherapi_current = {}
    if isinstance(forecast_text, dict):
        weatherapi_current = forecast_text.get("current") or {}
    hist_date = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
    history = get_historical_weather(lat, lon, hist_date)

    # Pretty location name
    if not display_name:
        try:
            display_name = reverse_geolocate(lat, lon)
        except Exception:
            display_name = f"{lat:.3f}, {lon:.3f}"

    record_event_metric(
        "weather_data_fetched",
        location=display_name,
        tone=tone,
    )

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

    cache_key, cache_key_parts = build_cache_key(
        location_label=display_name,
        lat=lat,
        lon=lon,
        current=current,
        tone=tone,
        prompt_version=PROMPT_VERSION,
    )
    cached, cache_error = get_cached_response_with_status(cache_key)
    cache_status = "miss"
    quota_status = "not_checked"
    quota_details = None
    llm_called = False
    fallback_used = False
    fallback_reason = None

    # Get tone configuration
    tone_config = TONE_PRESETS.get(tone, TONE_PRESETS["sarcastic"])
    
    # Build messages with conversation history if provided
    messages = [
        {"role": "system", "content": f"{tone_config['system_prompt']}\n\n{MEASUREMENT_FORMATTING_REINFORCEMENT}"}
    ]
    
    # Add conversation history if it exists
    if conversation_history:
        messages.extend(conversation_history)
    
    # Add current request
    messages.append({"role": "user", "content": summary_input})

    if cached:
        cache_status = "hit"
        quota_status = "not_counted_cache_hit"
        gpt_summary = cached["response_text"]
        record_event_metric(
            "cache_hit",
            location=display_name,
            tone=tone,
            cache_status=cache_status,
            quota_status=quota_status,
        )
        logger.info("LLM cache hit | %s | %s | %s", display_name, tone, cache_key[:12])
    elif cache_error:
        cache_status = "error"
        fallback_used = True
        fallback_reason = "cache_error"
        gpt_summary = build_fallback_roast(
            display_name,
            current,
            forecast=forecast,
            alerts=alerts,
            tone=tone,
            reason=fallback_reason,
        )
        record_event_metric(
            "fallback_used",
            location=display_name,
            tone=tone,
            cache_status=cache_status,
            quota_status=quota_status,
            fallback_reason=fallback_reason,
        )
        logger.warning("LLM cache error fallback | %s | %s | %s", display_name, tone, cache_error)
    else:
        record_event_metric(
            "cache_miss",
            location=display_name,
            tone=tone,
            cache_status=cache_status,
        )
        quota_context = quota_context_from_request()
        quota_details = check_llm_quota(quota_context)
        quota_status = quota_details.get("quota_status", "unknown")
        if quota_status == "unavailable":
            fallback_used = True
            fallback_reason = "cache_error"
            gpt_summary = build_fallback_roast(
                display_name,
                current,
                forecast=forecast,
                alerts=alerts,
                tone=tone,
                reason=fallback_reason,
            )
            record_event_metric(
                "fallback_used",
                location=display_name,
                tone=tone,
                cache_status=cache_status,
                quota_status=quota_status,
                fallback_reason=fallback_reason,
            )
            logger.warning("LLM quota database fallback | %s | %s", display_name, tone)
        elif not quota_details.get("allowed", True):
            fallback_used = True
            fallback_reason = "quota_exceeded"
            gpt_summary = build_fallback_roast(
                display_name,
                current,
                forecast=forecast,
                alerts=alerts,
                tone=tone,
                reason=fallback_reason,
            )
            record_event_metric(
                "quota_limited",
                location=display_name,
                tone=tone,
                cache_status=cache_status,
                quota_status=quota_status,
                fallback_reason=fallback_reason,
            )
            record_event_metric(
                "fallback_used",
                location=display_name,
                tone=tone,
                cache_status=cache_status,
                quota_status=quota_status,
                fallback_reason=fallback_reason,
            )
            logger.warning(
                "LLM quota limited | %s | %s | reason=%s",
                display_name,
                tone,
                quota_details.get("reason"),
            )
        elif os.getenv("DISABLE_LLM", "").strip().lower() == "true" or not OPENAI_API_KEY:
            fallback_used = True
            fallback_reason = "llm_disabled"
            gpt_summary = build_fallback_roast(
                display_name,
                current,
                forecast=forecast,
                alerts=alerts,
                tone=tone,
                reason=fallback_reason,
            )
            record_event_metric(
                "fallback_used",
                location=display_name,
                tone=tone,
                cache_status=cache_status,
                quota_status=quota_status,
                fallback_reason=fallback_reason,
            )
            logger.warning("LLM disabled fallback | %s | %s", display_name, tone)
        else:
            try:
                client = OpenAI(api_key=OPENAI_API_KEY)

                # Call OpenAI with logging
                start_time = time.time()
                response = client.chat.completions.create(
                    model=OPENAI_MODEL,
                    messages=messages,
                    max_tokens=906
                )
                duration_ms = (time.time() - start_time) * 1000
                llm_called = True

                gpt_summary = response.choices[0].message.content

                # Log LLM call with token usage
                total_tokens = response.usage.total_tokens if response.usage else 0
                # Rough cost estimate for gpt-4o-mini: $0.15/1M input, $0.60/1M output tokens
                cost_estimate = (total_tokens / 1_000_000) * 0.30  # Average cost
                log_llm_call(OPENAI_MODEL, total_tokens, cost_estimate, "success", f"{display_name} | {tone} | {duration_ms:.0f}ms")
                record_llm_usage(quota_context, cache_key=cache_key)
                record_event_metric(
                    "llm_called",
                    location=display_name,
                    tone=tone,
                    cache_status=cache_status,
                    quota_status=quota_status,
                )

                weather_id, weather_main = weather_identity(current)
                weather_summary = " / ".join(filter(None, [weather_id, weather_main]))
                save_cached_response(
                    cache_key=cache_key,
                    location_label=display_name,
                    tone=tone,
                    weather_summary=weather_summary,
                    weather_id=weather_id,
                    response_text=gpt_summary,
                    prompt_version=PROMPT_VERSION,
                    ttl_seconds=LLM_CACHE_TTL_SECONDS,
                )
            except Exception as exc:
                fallback_used = True
                fallback_reason = "llm_error"
                llm_called = False
                gpt_summary = build_fallback_roast(
                    display_name,
                    current,
                    forecast=forecast,
                    alerts=alerts,
                    tone=tone,
                    reason=fallback_reason,
                )
                record_event_metric(
                    "llm_error",
                    location=display_name,
                    tone=tone,
                    cache_status=cache_status,
                    quota_status=quota_status,
                    fallback_reason=fallback_reason,
                )
                record_event_metric(
                    "fallback_used",
                    location=display_name,
                    tone=tone,
                    cache_status=cache_status,
                    quota_status=quota_status,
                    fallback_reason=fallback_reason,
                )
                log_llm_call(OPENAI_MODEL, 0, 0.0, "error", f"{display_name} | {tone} | {type(exc).__name__}: {exc}")

    # Build raw response
    raw_response = {
        "location": display_name,
        "coords": {"lat": lat, "lon": lon},
        "current": current,
        "weatherapi_current": weatherapi_current,
        "forecast": forecast,
        "air_quality": aqi,
        "alerts": alerts,
        "history": history,
        "news": news_articles,
        "summary": gpt_summary,
        "tone": tone,
        "hourly": get_hourly_forecast(lat, lon),  # next 12 hours from WeatherAPI cache
        "cache_status": cache_status,
        "cache_key": cache_key,
        "cache_key_parts": cache_key_parts,
        "prompt_version": PROMPT_VERSION,
        "quota_status": quota_status,
        "quota_details": quota_details,
        "llm_called": llm_called,
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason,
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
    messages = [{"role": "system", "content": f"{tone_config['system_prompt']}\n\n{MEASUREMENT_FORMATTING_REINFORCEMENT}"}]
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
    openweather_current = raw_response.get("current", {})
    weatherapi_current = raw_response.get("weatherapi_current") or {}
    forecast = raw_response.get("forecast", {})
    alerts = raw_response.get("alerts", [])
    news_articles = raw_response.get("news", [])

    if isinstance(weatherapi_current, dict) and weatherapi_current:
        normalized_current = normalize_weatherapi_current(weatherapi_current).to_dict()
        normalized_current["source"] = "weatherapi"
    else:
        normalized_current = normalize_openweather_current(openweather_current).to_dict()
        normalized_current["source"] = "openweather"

    # Extract 3-day simplified forecast
    forecast_list = forecast.get("list", [])
    forecast_3day = extract_3day_forecast(forecast_list)

    # Format alerts
    formatted_alerts = format_alerts_structured(alerts)

    hourly = raw_response.get("hourly", [])
    first_hour = hourly[0] if hourly else {}
    try:
        first_hour_code = int(first_hour.get("condition_code"))
    except (TypeError, ValueError):
        first_hour_code = None
    try:
        first_hour_precip = int(first_hour.get("precip_chance") or 0)
    except (TypeError, ValueError):
        first_hour_precip = 0
    first_hour_rain_or_thunder = (
        first_hour_code in (1063, 1072, 1087) or
        (1150 <= first_hour_code <= 1201 if first_hour_code is not None else False) or
        (1240 <= first_hour_code <= 1246 if first_hour_code is not None else False) or
        (1273 <= first_hour_code <= 1282 if first_hour_code is not None else False)
    )
    current_hourly_conflict = (
        normalized_current.get("source") == "openweather" and
        "clear" in (normalized_current.get("conditions") or "").lower() and
        (first_hour_precip >= 70 or first_hour_rain_or_thunder)
    )

    return {
        "text_summary": raw_response.get("summary", ""),
        "summary": raw_response.get("summary", ""),       # legacy alias
        "weather": {
            "hourly": hourly,
            "current": normalized_current,
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
            "cache_status": raw_response.get("cache_status"),
            "cache_key": raw_response.get("cache_key"),
            "cache_key_parts": raw_response.get("cache_key_parts"),
            "prompt_version": raw_response.get("prompt_version"),
            "quota_status": raw_response.get("quota_status"),
            "quota_details": raw_response.get("quota_details"),
            "llm_called": raw_response.get("llm_called"),
            "fallback_used": raw_response.get("fallback_used"),
            "fallback_reason": raw_response.get("fallback_reason"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "has_alerts": len(formatted_alerts) > 0,
            "has_news": len(news_articles) > 0,
            "current_source": normalized_current.get("source"),
            **({"current_hourly_conflict": True} if current_hourly_conflict else {})
        },
        # Keep raw data for debugging/advanced use
        "raw": {
            "current": openweather_current,
            "weatherapi_current": weatherapi_current,
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
                "weather_codes": [],
                "weather_ids": []
            }

        daily_data[date_key]["temps"].append(entry["main"]["temp"])
        weather = entry.get("weather", [{}])[0]
        daily_data[date_key]["conditions"].append(weather.get("description", ""))
        daily_data[date_key]["weather_codes"].append(weather.get("main", ""))
        daily_data[date_key]["weather_ids"].append(weather.get("id"))

    # Build 3-day forecast
    result = []
    for date_key in sorted(daily_data.keys())[:3]:
        day = daily_data[date_key]

        # Most common condition for the day
        most_common_code = max(set(day["weather_codes"]), key=day["weather_codes"].count)
        condition_ids = [code for code in day["weather_ids"] if code is not None]
        most_common_id = max(set(condition_ids), key=condition_ids.count) if condition_ids else None
        most_common_desc = max(set(day["conditions"]), key=day["conditions"].count)

        result.append({
            "date": day["date"],
            "day": day["day_name"],
            "temp_high_c": round(max(day["temps"]), 1),
            "temp_high_f": celsius_to_fahrenheit(max(day["temps"])),
            "temp_low_c": round(min(day["temps"]), 1),
            "temp_low_f": celsius_to_fahrenheit(min(day["temps"])),
            "conditions": most_common_desc.title(),
            "condition_main": most_common_code,
            "condition_code": most_common_id,
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
