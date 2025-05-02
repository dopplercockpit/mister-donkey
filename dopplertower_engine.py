# dopplertower_engine.py
# Main weather engine for Doppler Tower

import requests
from datetime import datetime, timedelta, timezone
from openai import OpenAI
import os
import math
from io import BytesIO
from PIL import Image
from nlpprepro import preprocess_with_gpt


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
WEATHERAPI_KEY = os.getenv("WEATHERAPI_KEY")

OPENWEATHER_URL = "http://api.openweathermap.org/data/2.5"
WEATHERAPI_URL = "http://api.weatherapi.com/v1"

def search_city_with_weatherapi(query):
#    url = f"{WEATHERAPI_URL}/search.json?key={WEATHERAPI_KEY}&q={query}"
#   resp = requests.get(url)
#    if resp.status_code == 200:
#        results = resp.json()
#        if results:
#            city = results[0]
#            return {
#                "name": city["name"],
#                "region": city["region"],
#                "country": city["country"],
#                "lat": city["lat"],
#                "lon": city["lon"],
#                "full_name": f"{city['name']}, {city['region']}, {city['country']}"
#            }
#    return None

    # 1) Try OpenWeather Direct Geocoding (supports state codes, etc.)
    gw_url = (
        f"http://api.openweathermap.org/geo/1.0/direct"
        f"?q={query}&limit=1&appid={OPENWEATHER_API_KEY}"
    )
    r = requests.get(gw_url)
    if r.status_code == 200:
        data = r.json()
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

def generate_summary_prompt(user_prompt, current, forecast_lines, aqi, alerts):
    current_main = current.get("main", {})
    return (
        f"You're Mister Donkey, a sarcastic, emoji-loving, profanity-capable weather assistant "
        f"who delivers helpful and accurate forecasts with a wild sense of humor, swagger, and grit. "
        f"You're cheeky but kind, and you don't talk like a robot. Always inject personality, "
        f"slang, dark humor, and plenty of weather-relevant emojis like 🌧️❄️☀️💨🌪️🌈.\n\n"

        f"User prompt: {user_prompt}\n"
        f"Current: {current_main.get('temp')}°C, feels like {current_main.get('feels_like')}°C\n"
        f"Conditions: {current.get('weather',[{}])[0].get('description','')}\n"
        f"Wind: {current.get('wind',{}).get('speed')} m/s\n"
        f"AQI: {aqi}\n"
        f"Forecast: {'; '.join(forecast_lines)}\n"
        f"Alerts: {len(alerts)} active\n"
        f"Always end with a short piece of sarcastic advice or comment, in your voice.\n"
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

def get_full_weather_summary(city_query, user_prompt="", timezone_offset=0):
    city_info = search_city_with_weatherapi(city_query)
    if not city_info:
        return {"error": "City not found."}

    lat, lon = city_info["lat"], city_info["lon"]
    current = get_openweather_current(lat, lon)
    forecast = get_openweather_forecast(lat, lon)
    aqi = get_air_quality(lat, lon)
    alerts = get_weather_alerts(lat, lon)
    forecast_text = get_three_day_forecast(lat, lon)
    hist_date = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
    history = get_historical_weather(lat, lon, hist_date)

    forecast_lines = []
    if forecast.get("list"):
        for item in forecast["list"][:3]:
            dt = datetime.utcfromtimestamp(item["dt"] + timezone_offset).strftime("%Y-%m-%d %H:%M")
            temp = item.get("main", {}).get("temp", "N/A")
            desc = item.get("weather", [{}])[0].get("description", "unknown")
            forecast_lines.append(f"{dt}: {temp}°C, {desc}")

    summary_input = generate_summary_prompt(user_prompt, current, forecast_lines, aqi, alerts)

    alerts_summary_forecast = detect_alert_worthy_changes(current, forecast)
    alerts_summary_severe = parse_weather_alerts({"alert": alerts})
    alerts_summary = "\n".join(filter(None, [alerts_summary_severe, alerts_summary_forecast]))

    client = OpenAI(api_key=OPENAI_API_KEY)
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are Mister Donkey — a wildly sarcastic, emoji-obsessed, smartass weather assistant who delivers accurate forecasts with humor, swearing (within reason), charm, and style. Inject your personality into everything. You're not a robot, you're a meteorological jackass."},
                {"role": "user", "content": summary_input}
            ],
            max_tokens=300
        )
        gpt_summary = response.choices[0].message.content
    except Exception as e:
        gpt_summary = f"GPT error: {str(e)}"

    return {
        "city": city_info["full_name"],
        "current": current,
        "forecast": forecast,
        "aqi": aqi,
        "alerts": alerts,
        "three_day_forecast": forecast_text,
        "historical": history,
        "summary": gpt_summary,
        "alerts_summary": alerts_summary
    }
