"""Deterministic Mister Donkey weather fallback templates."""
import hashlib


def _safe_number(value):
    return value if isinstance(value, (int, float)) else None


def _current_parts(current):
    current = current if isinstance(current, dict) else {}
    main = current.get("main") if isinstance(current.get("main"), dict) else {}
    wind = current.get("wind") if isinstance(current.get("wind"), dict) else {}
    weather_items = current.get("weather") if isinstance(current.get("weather"), list) else []
    weather = weather_items[0] if weather_items else {}

    return {
        "temp_c": _safe_number(main.get("temp")),
        "feels_like_c": _safe_number(main.get("feels_like")),
        "humidity": main.get("humidity"),
        "wind_mps": _safe_number(wind.get("speed")),
        "weather_id": weather.get("id"),
        "condition": weather.get("main") or weather.get("description") or "unknown conditions",
        "description": weather.get("description") or weather.get("main") or "unknown conditions",
    }


def _family(parts):
    weather_id = parts["weather_id"]
    condition = str(parts["condition"] or "").lower()
    temp = parts["temp_c"]
    wind = parts["wind_mps"]

    if isinstance(weather_id, int):
        if 200 <= weather_id <= 232:
            return "thunderstorm"
        if 300 <= weather_id <= 531:
            return "rain"
        if 600 <= weather_id <= 622:
            return "snow"
        if weather_id in (701, 711, 721, 731, 741, 751, 761, 762):
            return "fog_mist"
        if weather_id == 800:
            return "clear_sunny"
        if 801 <= weather_id <= 804:
            return "clouds"

    if any(word in condition for word in ("thunder", "storm")):
        return "thunderstorm"
    if any(word in condition for word in ("rain", "drizzle", "shower")):
        return "rain"
    if "snow" in condition:
        return "snow"
    if any(word in condition for word in ("fog", "mist", "haze")):
        return "fog_mist"
    if temp is not None and temp >= 35:
        return "extreme_heat"
    if temp is not None and temp <= 0:
        return "cold"
    if wind is not None and wind >= 12:
        return "wind"
    if any(word in condition for word in ("clear", "sun")):
        return "clear_sunny"
    if "cloud" in condition:
        return "clouds"
    return "unknown"


def _weather_sentence(parts):
    temp = parts["temp_c"]
    feels_like = parts["feels_like_c"]
    wind = parts["wind_mps"]
    humidity = parts["humidity"]

    bits = []
    if temp is not None:
        bits.append(f"{round(temp)} C")
    if feels_like is not None:
        bits.append(f"feels like {round(feels_like)} C")
    if wind is not None:
        bits.append(f"wind {round(wind * 3.6)} km/h")
    if humidity is not None:
        bits.append(f"humidity {humidity}%")
    return ", ".join(bits) if bits else "the instruments are being annoyingly vague"


def _tone_prefix(tone):
    return {
        "professional": "Executive Donkey fallback:",
        "pirate": "Fallback forecast, captain:",
        "hippie": "Cosmic backup forecast:",
        "drill_sergeant": "Weather order:",
        "gen_z": "Backup forecast, bestie:",
        "noir_detective": "Fallback case note:",
        "shakespeare": "Backup weather proclamation:",
        "mobster": "Fallback forecast, pal:",
        "doomsday": "Emergency backup forecast:",
    }.get(tone, "Mister Donkey backup forecast:")


TEMPLATES = {
    "clear_sunny": [
        "{prefix} {location}: clear skies, {details}. The sun is behaving for once, so enjoy it before the atmosphere remembers it has a job.",
        "{prefix} {location}: {details}. Basically sunny. Wear shades, not denial.",
    ],
    "clouds": [
        "{prefix} {location}: cloudy, {details}. The sky looks like it gave up halfway through laundry day.",
        "{prefix} {location}: clouds are loitering overhead, {details}. Fine weather, just emotionally gray.",
    ],
    "rain": [
        "{prefix} {location}: rain in the mix, {details}. Bring an umbrella unless you enjoy cosplaying as a damp receipt.",
        "{prefix} {location}: wet weather, {details}. The sky is leaking again. Plan accordingly.",
    ],
    "thunderstorm": [
        "{prefix} {location}: storms around, {details}. If the sky starts yelling, maybe do not stand under tall metal things like a genius.",
        "{prefix} {location}: thunderstorm conditions, {details}. The atmosphere is throwing furniture. Stay sharp.",
    ],
    "snow": [
        "{prefix} {location}: snow showing up, {details}. Walk like the pavement owes you money but might sue.",
        "{prefix} {location}: snowy conditions, {details}. Layers, traction, patience. The winter nonsense package.",
    ],
    "fog_mist": [
        "{prefix} {location}: fog or mist, {details}. Visibility is doing its mysterious little disappearing act.",
        "{prefix} {location}: murky conditions, {details}. Drive like other people exist, because apparently they still do.",
    ],
    "wind": [
        "{prefix} {location}: windy, {details}. Secure loose stuff unless you want your trash can starting a new life.",
        "{prefix} {location}: the wind is being dramatic, {details}. Hats are now temporary property.",
    ],
    "extreme_heat": [
        "{prefix} {location}: serious heat, {details}. Hydrate, find shade, and do not challenge the sun like it cares.",
        "{prefix} {location}: hot as bad decisions, {details}. Light clothes, water, and fewer heroic outdoor plans.",
    ],
    "cold": [
        "{prefix} {location}: cold conditions, {details}. Layer up unless shivering is your chosen personality.",
        "{prefix} {location}: chilly nonsense, {details}. Gloves are cheaper than pretending your fingers are fine.",
    ],
    "unknown": [
        "{prefix} {location}: {condition}, {details}. The forecast is usable, even if the fancy roast engine is off sulking.",
        "{prefix} {location}: {condition}, {details}. Not enough drama for poetry, enough weather for planning.",
    ],
}


def build_fallback_roast(location_label, current, forecast=None, alerts=None, tone="sarcastic", reason=None):
    parts = _current_parts(current)
    family = _family(parts)
    prefix = _tone_prefix(tone)
    details = _weather_sentence(parts)
    choices = TEMPLATES.get(family, TEMPLATES["unknown"])
    selector = f"{location_label}|{family}|{parts['weather_id']}|{parts['temp_c']}|{tone}|{reason}"
    index = int(hashlib.sha256(selector.encode("utf-8")).hexdigest(), 16) % len(choices)
    template = choices[index]
    alert_count = len(alerts) if isinstance(alerts, list) else 0
    alert_text = " Active weather alerts are present, so do not ignore the boring official warnings." if alert_count else ""
    reason_text = {
        "quota_exceeded": " Cost controls blocked the fancy LLM roast.",
        "llm_error": " The LLM tripped over its own shoelaces.",
        "llm_disabled": " The LLM is disabled, so this is the sturdy backup version.",
        "cache_error": " The cache/database layer complained, so this is the safe backup.",
    }.get(reason, "")

    return (
        template.format(
            prefix=prefix,
            location=location_label or "your location",
            condition=parts["description"],
            details=details,
        )
        + alert_text
        + reason_text
    )
