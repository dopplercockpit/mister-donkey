from dataclasses import asdict, dataclass
from typing import Any, Optional


@dataclass
class WeatherSnapshot:
    temp_c: Optional[float] = None
    temp_f: Optional[float] = None
    feels_like_c: Optional[float] = None
    feels_like_f: Optional[float] = None
    humidity: Optional[int] = None

    wind_kph: Optional[float] = None
    wind_mph: Optional[float] = None
    wind_ms: Optional[float] = None
    wind_degree: Optional[int] = None

    conditions: str = ""
    condition_code: Any = None
    condition_main: str = ""
    icon_code: str = ""
    icon: str = ""

    precip_mm: Optional[float] = None
    precip_probability: Optional[int] = None
    uv_index: Optional[float] = None
    visibility_km: Optional[float] = None
    visibility_m: Optional[int] = None
    cloud_pct: Optional[int] = None
    pressure: Optional[int] = None

    source: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        data.update({
            "conditions_code": self.condition_main,
            "wind_speed_ms": self.wind_ms,
            "wind_speed_kmh": self.wind_kph,
            "wind_speed_mph": self.wind_mph,
            "wind_direction": self.wind_degree,
            "clouds_percent": self.cloud_pct,
        })
        return data


def safe_round(value, digits=1):
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def c_to_f(c):
    rounded = safe_round(c, 1)
    if rounded is None:
        return None
    return safe_round((rounded * 9 / 5) + 32, 1)


def ms_to_kph(ms):
    rounded = safe_round(ms, 3)
    if rounded is None:
        return None
    return safe_round(rounded * 3.6, 1)


def ms_to_mph(ms):
    rounded = safe_round(ms, 3)
    if rounded is None:
        return None
    return safe_round(rounded * 2.23694, 1)


def meters_to_km(meters):
    rounded = safe_round(meters, 1)
    if rounded is None:
        return None
    return safe_round(rounded / 1000, 1)


def _first_present(*values):
    for value in values:
        if value is not None:
            return value
    return None


def _as_int(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def map_weather_icon(condition_main_or_code):
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
        "Tornado": "🌪️",
    }
    return icon_map.get(condition_main_or_code, "🌤️")


def normalize_openweather_current(data) -> WeatherSnapshot:
    data = data or {}
    main = data.get("main") or {}
    weather = (data.get("weather") or [{}])[0] or {}
    wind = data.get("wind") or {}
    clouds = data.get("clouds") or {}
    rain = data.get("rain") or {}
    snow = data.get("snow") or {}

    temp_c = safe_round(main.get("temp"), 1)
    feels_like_c = safe_round(main.get("feels_like"), 1)
    wind_ms = safe_round(wind.get("speed"), 1)
    visibility_m = _as_int(data.get("visibility"))
    condition_main = weather.get("main") or ""

    return WeatherSnapshot(
        temp_c=temp_c,
        temp_f=c_to_f(temp_c),
        feels_like_c=feels_like_c,
        feels_like_f=c_to_f(feels_like_c),
        humidity=_as_int(main.get("humidity")),
        wind_kph=ms_to_kph(wind_ms),
        wind_mph=ms_to_mph(wind_ms),
        wind_ms=wind_ms,
        wind_degree=_as_int(wind.get("deg")),
        conditions=(weather.get("description") or "").title(),
        condition_code=weather.get("id"),
        condition_main=condition_main,
        icon_code=weather.get("icon") or "",
        icon=map_weather_icon(condition_main),
        precip_mm=safe_round(_first_present(rain.get("1h"), rain.get("3h"), snow.get("1h"), snow.get("3h")), 1),
        visibility_km=meters_to_km(visibility_m),
        visibility_m=visibility_m,
        cloud_pct=_as_int(clouds.get("all")),
        pressure=_as_int(main.get("pressure")),
        source="openweather",
    )


def normalize_weatherapi_current(data) -> WeatherSnapshot:
    data = data or {}
    current = data.get("current") if isinstance(data.get("current"), dict) else data
    condition = current.get("condition") or {}

    return WeatherSnapshot(
        temp_c=safe_round(current.get("temp_c"), 1),
        temp_f=safe_round(current.get("temp_f"), 1),
        feels_like_c=safe_round(current.get("feelslike_c"), 1),
        feels_like_f=safe_round(current.get("feelslike_f"), 1),
        humidity=_as_int(current.get("humidity")),
        wind_kph=safe_round(current.get("wind_kph"), 1),
        wind_mph=safe_round(current.get("wind_mph"), 1),
        wind_degree=_as_int(current.get("wind_degree")),
        conditions=condition.get("text") or "",
        condition_code=condition.get("code"),
        icon_code=condition.get("icon") or "",
        icon=map_weather_icon(condition.get("text")),
        precip_mm=safe_round(current.get("precip_mm"), 1),
        uv_index=safe_round(current.get("uv"), 1),
        visibility_km=safe_round(current.get("vis_km"), 1),
        cloud_pct=_as_int(current.get("cloud")),
        pressure=_as_int(current.get("pressure_mb")),
        source="weatherapi",
    )


def normalize_openweather_forecast_item(item) -> WeatherSnapshot:
    item = item or {}
    snapshot = normalize_openweather_current(item)
    pop = _as_float(item.get("pop"))
    if pop is not None:
        snapshot.precip_probability = _as_int(round(pop * 100))
    return snapshot
