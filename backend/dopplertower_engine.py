# dopplertower_engine.py
# Main weather engine for Doppler Tower
# A clean, modular, weather engine for web, app and agent use

import requests
from datetime import datetime, timedelta, timezone
from openai import OpenAI
import os
import math
from io import BytesIO
from PIL import Image

# Load keys from environment or dotenv (you can adapt this for Flask config later)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
WEATHERAPI_KEY = os.getenv("WEATHERAPI_KEY")

OPENWEATHER_URL = "http://api.openweathermap.org/data/2.5"
WEATHERAPI_URL = "http://api.weatherapi.com/v1"

### ------------------ GEO + HELPER UTILS ------------------ ###
def search_city_with_weatherapi(query):
    url = f"{WEATHERAPI_URL}/search.json?key={WEATHERAPI_KEY}&q={query}"
    resp = requests.get(url)
    if resp.status_code == 200:
        results = resp.json()
        if results:
            city = results[0]
            return {
                "name": city["name"],
                "region": city["region"],
                "country": city["country"],
                "lat": city["lat"],
                "lon": city["lon"],
                "full_name": f"{city['name']}, {city['region']}, {city['country']}"
            }
    return None

def celsius_to_fahrenheit(c):
    return round((c * 9/5) + 32) if isinstance(c, (int, float)) else "N/A"

def convert_wind_speed(mps):
    return round(mps * 3.6), round(mps * 2.23694) if isinstance(mps, (int, float)) else ("N/A", "N/A")

### ------------------ WEATHER CALLS ------------------ ###
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

def get_weather_alerts(city_name):
    url = f"{WEATHERAPI_URL}/alerts.json?key={WEATHERAPI_KEY}&q={city_name}"
    response = requests.get(url)
    data = response.json()
    alerts = data.get("alerts", {}).get("alert", [])
    return alerts if alerts else []

def get_three_day_forecast(city_name):
    url = f"{WEATHERAPI_URL}/forecast.json?key={WEATHERAPI_KEY}&q={city_name}&days=3"
    response = requests.get(url)
    return response.json()

def get_historical_weather(city_name, date_str):
    url = f"{WEATHERAPI_URL}/history.json?key={WEATHERAPI_KEY}&q={city_name}&dt={date_str}"
    response = requests.get(url)
    return response.json()

### ------------------ MAIN ENGINE FUNCTION ------------------ ###
def get_full_weather_summary(city_query, user_prompt="", timezone_offset=0):
    city_info = search_city_with_weatherapi(city_query)
    if not city_info:
        return {"error": "City not found."}

    lat, lon = city_info["lat"], city_info["lon"]
    current = get_openweather_current(lat, lon)
    forecast = get_openweather_forecast(lat, lon)
    aqi = get_air_quality(lat, lon)
    alerts = get_weather_alerts(city_info["name"])
    forecast_text = get_three_day_forecast(city_info["name"])
    hist_date = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
    history = get_historical_weather(city_info["name"], hist_date)

    forecast_lines = []
    if forecast.get("list"):
        for item in forecast["list"][:3]:
            dt = datetime.utcfromtimestamp(item["dt"] + timezone_offset).strftime("%Y-%m-%d %H:%M")
            temp = item.get("main", {}).get("temp", "N/A")
            desc = item.get("weather", [{}])[0].get("description", "unknown")
            forecast_lines.append(f"{dt}: {temp}°C, {desc}")

    current_main = current.get("main", {})
    summary_input = (
        f"User prompt: {user_prompt}\n"
        f"Current: {current_main.get('temp')}°C, feels like {current_main.get('feels_like')}°C\n"
        f"Conditions: {current.get('weather',[{}])[0].get('description','')}\n"
        f"Wind: {current.get('wind',{}).get('speed')} m/s\n"
        f"AQI: {aqi}\n"
        f"Forecast: {'; '.join(forecast_lines)}\n"
        f"Alerts: {len(alerts)} active\n"
    )

    client = OpenAI(api_key=OPENAI_API_KEY)
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a friendly but smart weather assistant."},
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
        "summary": gpt_summary
    }
