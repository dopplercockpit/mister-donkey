# vitamin_d_forecast.py
# Estimates Vitamin D synthesis potential from UV index, sun elevation,
# cloud cover, and Fitzpatrick skin type.

import math
import os
import requests
from datetime import datetime, timezone
from typing import Optional

WEATHERAPI_KEY = os.getenv("WEATHERAPI_KEY")
WEATHERAPI_URL = "http://api.weatherapi.com/v1"

# Fitzpatrick scale: skin_type -> synthesis time multiplier relative to Type I.
# Type I (very fair) needs the least sun; Type VI (dark) needs the most.
SKIN_TYPES = {
    1: {"label": "Type I – Very Fair",  "description": "Always burns, never tans",       "multiplier": 1.0},
    2: {"label": "Type II – Fair",       "description": "Usually burns, rarely tans",      "multiplier": 1.8},
    3: {"label": "Type III – Medium",    "description": "Sometimes burns, gradually tans", "multiplier": 2.8},
    4: {"label": "Type IV – Olive",      "description": "Rarely burns, always tans",       "multiplier": 4.0},
    5: {"label": "Type V – Brown",       "description": "Very rarely burns",               "multiplier": 6.0},
    6: {"label": "Type VI – Dark",       "description": "Never burns, always tans",        "multiplier": 9.0},
}

# Base synthesis time (minutes) for Type I skin at UV index 3, full sun, optimal elevation.
# Derived from published dermatology literature midpoint estimates.
_BASE_MINUTES = 20.0


def sun_elevation_deg(lat: float, lon: float, utc_dt: datetime) -> float:
    """Return the solar elevation angle in degrees for the given position and UTC time."""
    day = utc_dt.timetuple().tm_yday
    hour_utc = utc_dt.hour + utc_dt.minute / 60.0 + utc_dt.second / 3600.0

    # Approximate solar time using longitude offset (15° per hour)
    solar_hour = hour_utc + lon / 15.0
    hour_angle = 15.0 * (solar_hour - 12.0)  # degrees; 0 at solar noon

    # Solar declination (degrees)
    declination = 23.45 * math.sin(math.radians((360.0 / 365.0) * (day - 81)))

    lat_r = math.radians(lat)
    dec_r = math.radians(declination)
    ha_r  = math.radians(hour_angle)

    sin_elev = (
        math.sin(lat_r) * math.sin(dec_r)
        + math.cos(lat_r) * math.cos(dec_r) * math.cos(ha_r)
    )
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_elev))))


def _cloud_factor(cloud_pct: int) -> float:
    """
    Convert cloud cover % to a UVB transmission factor (0–1).
    Clear sky = 1.0; fully overcast ≈ 0.20.
    """
    return max(0.05, 1.0 - (cloud_pct / 100.0) * 0.80)


def _elevation_factor(elev_deg: float) -> float:
    """
    Scale effective UVB by sun elevation.
    < 0°   → none (below horizon)
    0–15°  → minimal (atmosphere absorbs most UVB at low angles)
    15–35° → partial
    > 35°  → full
    """
    if elev_deg <= 0:
        return 0.0
    if elev_deg < 15:
        return (elev_deg / 15.0) * 0.30
    if elev_deg < 35:
        return 0.30 + ((elev_deg - 15.0) / 20.0) * 0.70
    return 1.0


def _vd_index(synthesis_minutes: Optional[int]) -> int:
    """Map synthesis_minutes to a 0–10 Vitamin D synthesis index."""
    if synthesis_minutes is None:
        return 0
    if synthesis_minutes <= 10:  return 10
    if synthesis_minutes <= 20:  return 9
    if synthesis_minutes <= 30:  return 7
    if synthesis_minutes <= 45:  return 6
    if synthesis_minutes <= 60:  return 5
    if synthesis_minutes <= 90:  return 4
    if synthesis_minutes <= 120: return 3
    if synthesis_minutes <= 180: return 2
    return 1


def _recommendation(
    synthesis_minutes: Optional[int],
    effective_uv: float,
    elevation: float,
    uv_index: float,
    skin_type: int,
) -> str:
    if elevation <= 0:
        return "The sun is below the horizon — no Vitamin D synthesis is possible right now."
    if elevation < 15:
        return (
            f"The sun is too low ({elevation:.0f}°) for meaningful UVB to reach the ground. "
            "Vitamin D synthesis is negligible. Try again around solar noon."
        )
    if uv_index < 1:
        return "UV index is too low for significant Vitamin D synthesis today. Consider supplements or dietary sources."
    if effective_uv < 0.5:
        return "Heavy cloud cover is blocking most UVB. Vitamin D synthesis today is minimal."

    if synthesis_minutes is None:
        return "Conditions don't support Vitamin D synthesis right now."

    spf_note = (
        "Apply SPF 15+ after your synthesis window to protect fair skin."
        if skin_type <= 2
        else "Sunscreen optional after your synthesis window."
    )

    if synthesis_minutes <= 20:
        return f"Excellent conditions! Expose arms and face for ~{synthesis_minutes} min. {spf_note}"
    if synthesis_minutes <= 45:
        return f"Good conditions. About {synthesis_minutes} min of midday sun will do it. {spf_note}"
    if synthesis_minutes <= 90:
        return f"Moderate conditions — aim for {synthesis_minutes} min around solar noon. {spf_note}"
    return (
        f"Poor conditions. You'd need ~{synthesis_minutes} min of sun exposure — "
        "a supplement may be more practical today."
    )


def get_vitamin_d_forecast(lat: float, lon: float, skin_type: int = 3) -> dict:
    """
    Calculate Vitamin D synthesis forecast for the given location and skin type.

    Args:
        lat:       Latitude
        lon:       Longitude
        skin_type: Fitzpatrick scale 1–6

    Returns dict with:
        vitamin_d_index     – 0–10 synthesis index
        synthesis_minutes   – minutes of exposure needed (None if impossible)
        recommendation      – human-readable advice string
        uv_index            – current UV index from WeatherAPI
        sun_elevation       – solar elevation angle in degrees
        cloud_factor        – UVB transmission factor (0–1; 1 = clear sky)
        skin_type_label     – Fitzpatrick label string
    """
    skin_type = max(1, min(6, int(skin_type)))
    skin = SKIN_TYPES[skin_type]
    now_utc = datetime.now(timezone.utc)

    # Fetch UV index and cloud cover from WeatherAPI
    uv_index: float = 0.0
    cloud_pct: int  = 0
    try:
        resp = requests.get(
            f"{WEATHERAPI_URL}/current.json",
            params={"key": WEATHERAPI_KEY, "q": f"{lat},{lon}"},
            timeout=6,
        )
        if resp.status_code == 200:
            wa_current = resp.json().get("current", {})
            uv_index  = float(wa_current.get("uv", 0))
            cloud_pct = int(wa_current.get("cloud", 0))
    except Exception as exc:
        print(f"⚠️ VitaminD: WeatherAPI fetch failed: {exc}")

    elevation  = sun_elevation_deg(lat, lon, now_utc)
    c_factor   = _cloud_factor(cloud_pct)
    e_factor   = _elevation_factor(elevation)
    effective_uv = uv_index * c_factor * e_factor

    if effective_uv < 0.5:
        synthesis_minutes = None
    else:
        # Time = base × skin_multiplier × reference_uv / effective_uv
        raw = (_BASE_MINUTES * skin["multiplier"] * 3.0) / effective_uv
        synthesis_minutes = round(min(raw, 480))  # cap at 8 h

    return {
        "vitamin_d_index":    _vd_index(synthesis_minutes),
        "synthesis_minutes":  synthesis_minutes,
        "recommendation":     _recommendation(synthesis_minutes, effective_uv, elevation, uv_index, skin_type),
        "uv_index":           round(uv_index, 1),
        "sun_elevation":      round(elevation, 1),
        "cloud_factor":       round(c_factor, 2),
        "skin_type_label":    skin["label"],
        "skin_type_description": skin["description"],
        "cloud_cover_pct":    cloud_pct,
        "effective_uv":       round(effective_uv, 2),
        "timestamp_utc":      now_utc.isoformat(),
    }
