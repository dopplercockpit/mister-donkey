# vitamin_d_forecast.py
# Estimates current Vitamin D synthesis potential from UV index, sun elevation,
# cloud cover, and Fitzpatrick skin type.

import math
import os
from datetime import datetime, timezone
from typing import Optional

import requests

WEATHERAPI_KEY = os.getenv("WEATHERAPI_KEY")
WEATHERAPI_URL = "http://api.weatherapi.com/v1"

SKIN_TYPES = {
    1: {"label": "Type I - Very Fair", "description": "Always burns, never tans", "multiplier": 1.0},
    2: {"label": "Type II - Fair", "description": "Usually burns, rarely tans", "multiplier": 1.8},
    3: {"label": "Type III - Medium", "description": "Sometimes burns, gradually tans", "multiplier": 2.8},
    4: {"label": "Type IV - Olive", "description": "Rarely burns, always tans", "multiplier": 4.0},
    5: {"label": "Type V - Brown", "description": "Very rarely burns", "multiplier": 6.0},
    6: {"label": "Type VI - Dark", "description": "Never burns, always tans", "multiplier": 9.0},
}

_BASE_MINUTES = 20.0


def sun_elevation_deg(lat: float, lon: float, utc_dt: datetime) -> float:
    """Return the approximate solar elevation angle in degrees."""
    day = utc_dt.timetuple().tm_yday
    hour_utc = utc_dt.hour + utc_dt.minute / 60.0 + utc_dt.second / 3600.0
    solar_hour = hour_utc + lon / 15.0
    hour_angle = 15.0 * (solar_hour - 12.0)
    declination = 23.45 * math.sin(math.radians((360.0 / 365.0) * (day - 81)))

    lat_r = math.radians(lat)
    dec_r = math.radians(declination)
    ha_r = math.radians(hour_angle)
    sin_elev = (
        math.sin(lat_r) * math.sin(dec_r)
        + math.cos(lat_r) * math.cos(dec_r) * math.cos(ha_r)
    )
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_elev))))


def _cloud_factor(cloud_pct: int) -> float:
    """Convert cloud cover percentage to a rough UVB transmission factor."""
    return max(0.05, 1.0 - (cloud_pct / 100.0) * 0.80)


def _elevation_factor(elev_deg: float) -> float:
    """Scale effective UVB by sun elevation."""
    if elev_deg <= 0:
        return 0.0
    if elev_deg < 15:
        return (elev_deg / 15.0) * 0.30
    if elev_deg < 35:
        return 0.30 + ((elev_deg - 15.0) / 20.0) * 0.70
    return 1.0


def _vd_index(synthesis_minutes: Optional[int]) -> int:
    if synthesis_minutes is None:
        return 0
    if synthesis_minutes <= 10:
        return 10
    if synthesis_minutes <= 20:
        return 9
    if synthesis_minutes <= 30:
        return 7
    if synthesis_minutes <= 45:
        return 6
    if synthesis_minutes <= 60:
        return 5
    if synthesis_minutes <= 90:
        return 4
    if synthesis_minutes <= 120:
        return 3
    if synthesis_minutes <= 180:
        return 2
    return 1


def _day_phase(local_hour: int) -> str:
    if 5 <= local_hour < 11:
        return "morning"
    if 11 <= local_hour < 15:
        return "midday"
    if 15 <= local_hour < 18:
        return "afternoon"
    if 18 <= local_hour < 21:
        return "evening"
    return "night"


def _recommendation(
    synthesis_minutes: Optional[int],
    effective_uv: float,
    elevation: float,
    uv_index: float,
    skin_type: int,
) -> str:
    if elevation <= 0:
        return "The sun is below the horizon - no Vitamin D synthesis is possible right now. Do not chase Vitamin D in the dark like a confused houseplant."
    if elevation < 15:
        return (
            f"The sun is too low ({elevation:.0f} degrees) for meaningful UVB to reach the ground. "
            "Vitamin D synthesis is negligible. Try again around solar noon."
        )
    if uv_index < 1:
        return "UV index is too low for significant Vitamin D synthesis right now. Consider supplements or dietary sources."
    if effective_uv < 0.5:
        return "Heavy cloud cover is blocking most UVB. Vitamin D synthesis right now is minimal."
    if synthesis_minutes is None:
        return "Conditions do not support Vitamin D synthesis right now."

    safety_note = "After that, protect your skin: shade, clothing, and broad-spectrum SPF 15+ or higher."
    if skin_type <= 2 or uv_index >= 6:
        safety_note += " For fair skin or high UV, consider SPF 30+, shade, and limiting exposure."

    if synthesis_minutes <= 20:
        return f"About {synthesis_minutes} minutes may be enough for Vitamin D right now. {safety_note}"
    if synthesis_minutes <= 45:
        return f"About {synthesis_minutes} minutes may be enough for Vitamin D under current conditions. {safety_note}"
    if synthesis_minutes <= 90:
        return f"Current conditions are moderate: about {synthesis_minutes} minutes may be useful. {safety_note}"
    return (
        f"Poor conditions. You would need about {synthesis_minutes} minutes of sun exposure right now. "
        "That is a long damn time to stand around; dietary sources or supplements may be more practical."
    )


def get_vitamin_d_forecast(lat: float, lon: float, skin_type: int = 3) -> dict:
    skin_type = max(1, min(6, int(skin_type)))
    skin = SKIN_TYPES[skin_type]
    now_utc = datetime.now(timezone.utc)
    local_hour = int((now_utc.hour + lon / 15.0) % 24)

    uv_index = 0.0
    cloud_pct = 0
    try:
        resp = requests.get(
            f"{WEATHERAPI_URL}/current.json",
            params={"key": WEATHERAPI_KEY, "q": f"{lat},{lon}"},
            timeout=6,
        )
        if resp.status_code == 200:
            wa_current = resp.json().get("current", {})
            uv_index = float(wa_current.get("uv", 0))
            cloud_pct = int(wa_current.get("cloud", 0))
    except Exception as exc:
        print(f"VitaminD: WeatherAPI fetch failed: {exc}")

    elevation = sun_elevation_deg(lat, lon, now_utc)
    c_factor = _cloud_factor(cloud_pct)
    e_factor = _elevation_factor(elevation)
    effective_uv = uv_index * c_factor * e_factor

    if effective_uv < 0.5:
        synthesis_minutes = None
    else:
        raw = (_BASE_MINUTES * skin["multiplier"] * 3.0) / effective_uv
        synthesis_minutes = round(min(raw, 480))

    return {
        "vitamin_d_index": _vd_index(synthesis_minutes),
        "synthesis_minutes": synthesis_minutes,
        "recommendation": _recommendation(synthesis_minutes, effective_uv, elevation, uv_index, skin_type),
        "protection_after_minutes": synthesis_minutes,
        "sun_safety_note": (
            "Vitamin D estimates are approximate. Avoid burning. Sunscreen after the useful exposure window is not defeat; it is not being a crispy idiot."
        ),
        "exposure_window_label": "Useful exposure window",
        "day_phase": _day_phase(local_hour),
        "uv_index": round(uv_index, 1),
        "sun_elevation": round(elevation, 1),
        "cloud_factor": round(c_factor, 2),
        "skin_type_label": skin["label"],
        "skin_type_description": skin["description"],
        "cloud_cover_pct": cloud_pct,
        "effective_uv": round(effective_uv, 2),
        "timestamp_utc": now_utc.isoformat(),
    }
