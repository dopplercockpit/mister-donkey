# routes.py (UPDATED VERSION)
# Fixes: Added tone selector and conversation history support

import json
import os
import traceback
from datetime import datetime

from flask import Blueprint, Response, g, jsonify, redirect, request, stream_with_context, url_for
from flask_cors import cross_origin

from extensions import limiter
from utils import ErrorCode, error_response
from conversation_db import get_history_for_openai, get_history_raw, store_exchange
from request_metrics import record_event_metric

# Configuration
from config import ENV

DEFAULT_PROMPT_RATE_LIMIT = "100/day;20/hour;5/minute"

PROMPT_RATE_LIMIT = (
    os.getenv("PROMPT_RATE_LIMIT", DEFAULT_PROMPT_RATE_LIMIT).strip()
    or DEFAULT_PROMPT_RATE_LIMIT
)

prompt_rate_limit = limiter.shared_limit(PROMPT_RATE_LIMIT, scope="prompt")

# Helper for geocoding
from geo_utils_helper import resolve_location_query, reverse_geolocate

# Main logic to process the weather prompt
from process_app_prompt import process_prompt_from_app_structured

# Legacy "agent" database functions
from agent_db import add_agent, get_agents

# Our custom city resolver
from city_resolver import resolve_city_context

# NEW: Conversation manager
from conversation_manager import (
    conversation_manager,
    create_conversation,
    get_conversation,
    add_message_to_conversation,
    update_conversation_metadata
)

# Session logger for tracking metrics
from session_logger import session_logger

# Create a Blueprint
bp = Blueprint("routes", __name__)


def _location_label_from_request_data(data):
    location = data.get("location") if isinstance(data.get("location"), dict) else {}
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    return data.get("city") or location.get("city") or location.get("name") or metadata.get("location")

def _normalize_temp_unit(value):
    return value if value in ("C", "F") else "C"

def _temperature_unit_instruction(temp_unit):
    if temp_unit == "F":
        return (
            "Measurement formatting rule: In user-facing prose, include both US/imperial and metric units "
            "for weather measurements when those measurements are mentioned, with US/imperial first. "
            "For temperatures, use Fahrenheit first and Celsius second, rounded to whole numbers with no decimals, "
            "e.g. 64°F / 18°C. For feels-like temperatures, follow the same format, e.g. feels like 59°F / 15°C. "
            "For wind speed, use mph first and km/h second, rounded to whole numbers, e.g. 12 mph / 19 km/h. "
            "For precipitation amount, use inches first and millimeters second; keep small inch values readable "
            "with up to two decimals when needed, e.g. 0.08 in / 2 mm. For visibility, use miles first and "
            "kilometers second, rounded sensibly, e.g. 6 mi / 10 km. For pressure, use inHg first and hPa second, "
            "e.g. 29.92 inHg / 1013 hPa. Humidity and precipitation chance remain percentages only. "
            "UV index remains unitless."
        )
    return (
        "Measurement formatting rule: In user-facing prose, include both metric and US/imperial units "
        "for weather measurements when those measurements are mentioned, with metric first. "
        "For temperatures, use Celsius first and Fahrenheit second, rounded to whole numbers with no decimals, "
        "e.g. 18°C / 64°F. For feels-like temperatures, follow the same format, e.g. feels like 15°C / 59°F. "
        "For wind speed, use km/h first and mph second, rounded to whole numbers, e.g. 19 km/h / 12 mph. "
        "For precipitation amount, use millimeters first and inches second; keep small inch values readable "
        "with up to two decimals when needed, e.g. 2 mm / 0.08 in. For visibility, use kilometers first and "
        "miles second, rounded sensibly, e.g. 10 km / 6 mi. For pressure, use hPa first and inHg second, "
        "e.g. 1013 hPa / 29.92 inHg. Humidity and precipitation chance remain percentages only. "
        "UV index remains unitless."
    )

def _append_temperature_unit_instruction(prompt, temp_unit):
    return f"{prompt}\n\nUser temperature unit preference: {_temperature_unit_instruction(temp_unit)}"

def _attach_temp_unit_metadata(result, temp_unit):
    result["temp_unit"] = temp_unit
    metadata = result.get("metadata")
    if isinstance(metadata, dict):
        metadata["temp_unit"] = temp_unit
    else:
        result["metadata"] = {"temp_unit": temp_unit}

@bp.route("/", methods=["GET"])
def home():
    """GET / - Simple sanity-check endpoint."""
    return jsonify({
        "service": "Mister Donkey Weather API",
        "version": "2.0",
        "features": [
            "Weather forecasts",
            "Tone selection (10 personalities)",
            "Conversation history",
            "City resolution",
            "Auto-loading"
        ],
        "endpoints": {
            "/prompt": "Main weather query endpoint",
            "/geo/reverse": "Reverse geocoding",
            "/geo/resolve": "Manual location resolution",
            "/agents": "Scheduled weather agents",
            "/conversation/new": "Create new conversation",
            "/conversation/<id>": "Get conversation history",
            "/tones": "List available tones"
        }
    })

@bp.route("/geo/reverse", methods=["POST"])
@cross_origin()
def reverse_lookup():
    """POST /geo/reverse - Convert lat/lon to city name."""
    data = request.get_json() or {}
    lat = data.get("lat")
    lon = data.get("lon")

    if lat is None or lon is None:
        return error_response("Missing 'lat' or 'lon' in request body.", ErrorCode.INVALID_REQUEST, 400)

    try:
        city_name = reverse_geolocate(lat, lon)
    except Exception as ex:
        return error_response(f"Reverse geolocation failed: {str(ex)}", ErrorCode.API_ERROR, 500)

    if not city_name:
        return error_response("Could not determine city from coordinates.", ErrorCode.LOCATION_NOT_FOUND, 500)

    return jsonify({"city": city_name})

@bp.route("/geo/resolve", methods=["POST"])
@cross_origin()
def resolve_manual_location():
    """POST /geo/resolve - Convert manual city/postal input to lat/lon."""
    data = request.get_json() or {}
    query = (data.get("query") or "").strip()

    if len(query) < 2:
        return error_response("Enter at least 2 characters for location search.", ErrorCode.INVALID_REQUEST, 400)

    try:
        result = resolve_location_query(query)
    except Exception as ex:
        return error_response(f"Location resolution failed: {str(ex)}", ErrorCode.API_ERROR, 500)

    if not result:
        return error_response("Could not resolve location", ErrorCode.LOCATION_NOT_FOUND, 404)

    return jsonify({
        "name": result["name"],
        "lat": result["lat"],
        "lon": result["lon"],
        "source": "manual",
    })

@bp.route("/agents", methods=["GET"])
def get_all_agents():
    """GET /agents - Return list of scheduled agents."""
    try:
        agents = get_agents()
        return jsonify(agents)
    except Exception as ex:
        return error_response(f"Failed to retrieve agents: {str(ex)}", ErrorCode.INTERNAL_ERROR, 500)

@bp.route("/agents", methods=["POST"])
def add_or_update_agent():
    """POST /agents - Create/update scheduled Weather Agent."""
    data = request.get_json() or {}

    required_fields = ["user_id", "city", "times", "timezone"]
    missing = [f for f in required_fields if f not in data]
    if missing:
        return error_response(f"Missing required fields: {', '.join(missing)}", ErrorCode.INVALID_REQUEST, 400)

    times = data.get("times")
    if not isinstance(times, list) or not all(isinstance(t, str) and ":" in t for t in times):
        return error_response("Field 'times' must be a list of 'HH:MM' strings.", ErrorCode.INVALID_REQUEST, 400)

    try:
        add_agent(
            user_id=data["user_id"],
            location=data["city"],
            reminder_times=times,
            tz_string=data["timezone"]
        )
        return jsonify({"status": "Agent saved to DB!"})
    except Exception as ex:
        return error_response(f"Failed to save agent: {str(ex)}", ErrorCode.INTERNAL_ERROR, 500)

# NEW: Tone management endpoints
@bp.route("/tones", methods=["GET"])
@cross_origin()
def get_tones():
    """GET /tones - List available personality tones"""
    from dopplertower_engine import TONE_PRESETS

    emoji_map = {
        "sarcastic": "🙄",
        "pirate": "🏴‍☠️",
        "professional": "📊",
        "hippie": "☮️",
        "drill_sergeant": "🎖️",
        "gen_z": "💅",
        "noir_detective": "🕵️",
        "shakespeare": "🎭",
        "mobster": "🤌",
        "doomsday": "☢️"
    }

    tones = []
    for key, config in TONE_PRESETS.items():
        tones.append({
            "id": key,
            "name": config.get("name", key.replace("_", " ").title()),
            "description": config.get("short_description", config["system_prompt"][:100] + "..."),
            "emoji": emoji_map.get(key, "🌦️"),
            "character_slug": key.replace("_", "-"),
            "image": f"/characters/{key.replace('_', '-')}.png",
            "is_default": key == "sarcastic"
        })

    return jsonify({
        "tones": tones,
        "default": "sarcastic"
    })

# NEW: Conversation management endpoints
@bp.route("/conversation/new", methods=["POST"])
@cross_origin()
def new_conversation():
    """POST /conversation/new - Create a new conversation session"""
    data = request.get_json() or {}
    user_id = data.get("user_id")
    
    session_id = create_conversation()
    
    # Set initial metadata
    if data.get("location"):
        update_conversation_metadata(session_id, "location", data["location"])
    if data.get("tone"):
        update_conversation_metadata(session_id, "tone", data["tone"])
    
    return jsonify({
        "session_id": session_id,
        "created_at": datetime.now().isoformat(),
        "status": "active"
    })

@bp.route("/conversation/<session_id>", methods=["GET"])
@cross_origin()
def get_conversation_history(session_id: str):
    """GET /conversation/<id> - Get conversation history"""
    session = conversation_manager.get_session(session_id)
    
    if not session:
        return jsonify({"error": "Session not found or expired"}), 404
    
    summary = conversation_manager.get_session_summary(session_id)
    
    return jsonify({
        "session": summary,
        "messages": conversation_manager.get_conversation_history(session_id, format_for_openai=False)
    })

@bp.route("/conversation/<session_id>/clear", methods=["POST"])
@cross_origin()
def clear_conversation(session_id: str):
    """POST /conversation/<id>/clear - Clear conversation history"""
    conversation_manager.delete_session(session_id)
    return jsonify({"status": "cleared"})

@bp.route("/prompt", methods=["POST"])
@cross_origin()
@prompt_rate_limit
def handle_prompt():
    """
    POST /prompt - Main weather prompt endpoint.
    
    NEW Features:
    - Tone selection via 'tone' parameter
    - Conversation continuity via 'session_id' parameter
    - Better city resolution (explicit cities override geolocation)
    """
    data = request.get_json() or {}
    user_prompt = (data.get("prompt") or "").strip()
    location = data.get("location") or {}
    is_auto_request = data.get("auto", False)
    debug_requested = bool(data.get("debug", False))
    temp_unit = _normalize_temp_unit(data.get("temp_unit", "C"))
    
    # NEW: Tone and conversation parameters
    tone = data.get("tone", "sarcastic")
    session_id = data.get("session_id")
    record_event_metric(
        "weather_request_received",
        location=_location_label_from_request_data(data),
        tone=tone,
        session_id=session_id,
    )

    # Validate tone
    from dopplertower_engine import TONE_PRESETS
    if tone not in TONE_PRESETS:
        tone = "sarcastic"
        print(f"⚠️ Invalid tone '{data.get('tone')}', using default: sarcastic")

    # Extract location data early
    lat = location.get("lat")
    lon = location.get("lon")

    # Enhanced debug logging
    if debug_requested or is_auto_request:
        print(f"\n🔍 Debug enabled: auto={is_auto_request}, debug={debug_requested}, tone={tone}")
        print(f"📝 Input prompt: '{user_prompt}'")
        print(f"📍 Location data: {json.dumps(location)}")
        if session_id:
            print(f"💬 Session ID: {session_id}")
        if lat is not None and lon is not None:
            print(f"📍 Coordinates: {lat}, {lon}")
        print("-" * 50)
    
    # 1) City Resolver: Preprocess user prompt
    try:
        modified_prompt, resolved_city, resolver_metadata = resolve_city_context(user_prompt, location)
    except Exception as ex:
        error_trace = traceback.format_exc()
        print(f"❌ ERROR in /prompt:\n{error_trace}")
        if session_id:
            session_logger.log_error(session_id, f"City resolver error: {str(ex)}")
        return error_response(
            str(ex), ErrorCode.INTERNAL_ERROR, 500,
            trace=error_trace if ENV == "dev" else None,
        )

    # Enhanced debugging
    if is_auto_request:
        print(f"🧠 Auto-load Resolver Debug: {json.dumps(resolver_metadata)}")
        print(f"🧠 Auto-load Modified Prompt: '{modified_prompt}'")
        print(f"🧠 Auto-load Resolved City: '{resolved_city}'")
    else:
        print("🧠 Resolver Debug:", json.dumps(resolver_metadata))

    # If city was resolved but stripped from prompt, put it back
    if resolved_city and resolved_city.lower() not in modified_prompt.lower():
        modified_prompt = f"{modified_prompt} in {resolved_city}"
        print(f"🔁 Re-injected resolved city into prompt: '{modified_prompt}'")

    # 2) Reverse geocoding fallback for auto requests
    if lat is not None and lon is not None and not resolved_city:
        try:
            fallback_city = reverse_geolocate(lat, lon)
        except Exception as ex:
            print(f"⚠️ Reverse geocode error: {str(ex)}")
            fallback_city = None

        if fallback_city:
            clean_city = fallback_city.split(",")[0].strip()

            if clean_city.lower() not in modified_prompt.lower():
                if modified_prompt:
                    modified_prompt = f"{modified_prompt} in {clean_city}"
                else:
                    modified_prompt = f"Weather in {clean_city}"
                
                if is_auto_request:
                    print(f"🤖 Auto-load: Injected fallback city: '{modified_prompt}'")
                else:
                    print(f"🔄 Injecting cleaned fallback city into prompt: '{modified_prompt}'")

    # 3) Validate we have a prompt
    if not modified_prompt:
        error_msg = "Missing 'prompt' in request. I need SOMETHING to work with."
        if is_auto_request:
            error_msg = "Auto-loading failed: Could not determine location or generate prompt."
        return error_response(error_msg, ErrorCode.INVALID_REQUEST, 400)

    modified_prompt = _append_temperature_unit_instruction(modified_prompt, temp_unit)

    # Load conversation history from SQLite (last 6 exchanges = 12 messages)
    conversation_history = None
    if session_id:
        conversation_history = get_history_for_openai(session_id, exchanges=6)
        print(f"💬 Loaded {len(conversation_history)} messages from SQLite history")

    # 4) Process the prompt with tone and conversation
    try:
        result = process_prompt_from_app_structured(
            modified_prompt,
            location=location,
            tone=tone,
            conversation_history=conversation_history
        )

        # Persist exchange to SQLite
        if session_id:
            store_exchange(session_id, user_prompt, result.get("text_summary", ""))
            result["session_id"] = session_id

        _attach_temp_unit_metadata(result, temp_unit)
        
        # Ensure debug flag is set if either condition is true
        if debug_requested or is_auto_request:
            result["debug"] = True
            result["debug_info"] = {
                "auto_request": is_auto_request,
                "debug_requested": debug_requested,
                "original_prompt": user_prompt,
                "modified_prompt": modified_prompt,
                "resolver_metadata": resolver_metadata,
                "tone_used": tone,
                "temp_unit": temp_unit,
                "has_conversation_history": conversation_history is not None
            }
        
        # Add tone info
        result["tone"] = tone
        
        # Add auto-loading metadata
        if is_auto_request:
            result["auto_loaded"] = True
            result["auto_prompt"] = modified_prompt
            print(f"🤖 Auto-load successful for prompt: '{modified_prompt}'")
        
        return jsonify(result)
    
    except Exception as ex:
        error_msg = str(ex)
        error_trace = traceback.format_exc()

        # Log error to session if session_id exists
        if session_id:
            session_logger.log_error(session_id, f"Prompt processing error: {error_msg}")

        debug_info = {
            "error": error_msg,
            "trace": error_trace if ENV == "dev" else "Enable dev mode for trace",
            "debug_enabled": debug_requested or is_auto_request
        }

        if is_auto_request:
            print(f"🛑 Auto-load failed: {error_msg}")
            error_msg = f"Auto-loading failed: {error_msg}"

        print(f"❌ ERROR in process_prompt_from_app:\n{error_trace}")
        return error_response(error_msg, ErrorCode.API_ERROR, 500, debug_info=debug_info)


@bp.route("/prompt/structured", methods=["POST"])
@cross_origin()
@prompt_rate_limit
def handle_prompt_structured():
    """POST /prompt/structured - 308 permanent redirect to /prompt (identical response)."""
    return redirect(url_for("routes.handle_prompt"), 308)


@bp.route("/vitamin-d", methods=["POST"])
@cross_origin()
@limiter.limit("10 per minute")
def vitamin_d():
    """
    POST /vitamin-d
    Body: { lat, lon, skin_type (1-6 Fitzpatrick), session_id (optional) }
    Returns: { vitamin_d_index, synthesis_minutes, recommendation,
               uv_index, sun_elevation, cloud_factor, skin_type_label, ... }
    """
    from vitamin_d_forecast import get_vitamin_d_forecast

    data = request.get_json() or {}
    lat = data.get("lat")
    lon = data.get("lon")
    skin_type = data.get("skin_type", 3)
    session_id = data.get("session_id")

    if lat is None or lon is None:
        return error_response("Missing required fields: lat, lon", ErrorCode.INVALID_REQUEST, 400)

    try:
        lat = float(lat)
        lon = float(lon)
    except (ValueError, TypeError):
        return error_response("lat and lon must be numeric", ErrorCode.INVALID_REQUEST, 400)

    try:
        skin_type = int(skin_type)
        if not 1 <= skin_type <= 6:
            raise ValueError
    except (ValueError, TypeError):
        return error_response("skin_type must be an integer 1–6", ErrorCode.INVALID_REQUEST, 400)

    if session_id:
        print(f"☀️ /vitamin-d request | session={session_id} | ({lat:.3f}, {lon:.3f}) | skin={skin_type}")

    try:
        result = get_vitamin_d_forecast(lat, lon, skin_type)
        return jsonify(result)
    except Exception as ex:
        error_trace = traceback.format_exc()
        print(f"❌ ERROR in /vitamin-d:\n{error_trace}")
        return error_response(str(ex), ErrorCode.API_ERROR, 500,
                              trace=error_trace if ENV == "dev" else None)


@bp.route("/history/<session_id>", methods=["GET"])
@cross_origin()
def get_history(session_id: str):
    """GET /history/<session_id> — last 20 exchanges as JSON."""
    messages = get_history_raw(session_id, exchanges=20)
    return jsonify({"session_id": session_id, "messages": messages, "count": len(messages)})


@bp.route("/metrics/share", methods=["POST"])
@cross_origin()
def metrics_share():
    """POST /metrics/share - Minimal share conversion event."""
    data = request.get_json(silent=True) if request.is_json else {}
    data = data if isinstance(data, dict) else {}
    record_event_metric(
        "share_event_received",
        endpoint="/metrics/share",
        session_id=data.get("session_id"),
        client_id=data.get("client_id") or data.get("user_id"),
        location=_location_label_from_request_data(data),
        tone=data.get("tone"),
    )
    return jsonify({"ok": True})


@bp.route("/metrics/kofi-click", methods=["POST"])
@cross_origin()
def metrics_kofi_click():
    """POST /metrics/kofi-click - Minimal Ko-fi click conversion event."""
    data = request.get_json(silent=True) if request.is_json else {}
    data = data if isinstance(data, dict) else {}
    record_event_metric(
        "kofi_click_received",
        endpoint="/metrics/kofi-click",
        session_id=data.get("session_id"),
        client_id=data.get("client_id") or data.get("user_id"),
        location=_location_label_from_request_data(data),
        tone=data.get("tone"),
    )
    return jsonify({"ok": True})


@bp.route("/prompt/stream", methods=["POST"])
@cross_origin()
@prompt_rate_limit
def handle_prompt_stream():
    """POST /prompt/stream - SSE version of /prompt with structured weather parity."""
    from dopplertower_engine import TONE_PRESETS

    data = request.get_json() or {}
    user_prompt = (data.get("prompt") or "").strip()
    location    = data.get("location") or {}
    tone        = data.get("tone", "sarcastic")
    session_id  = data.get("session_id")
    temp_unit   = _normalize_temp_unit(data.get("temp_unit", "C"))
    record_event_metric(
        "weather_request_received",
        location=_location_label_from_request_data(data),
        tone=tone,
        session_id=session_id,
    )

    if tone not in TONE_PRESETS:
        tone = "sarcastic"

    if not user_prompt:
        return error_response("Missing prompt", ErrorCode.INVALID_REQUEST, 400)

    conv_history = get_history_for_openai(session_id, exchanges=6) if session_id else None
    req_id = g.get("request_id", "")
    prompt_for_processing = _append_temperature_unit_instruction(user_prompt, temp_unit)

    print(f"🌊 /prompt/stream | session={session_id} | tone={tone}")

    def text_chunks(text: str, size: int = 60):
        for index in range(0, len(text), size):
            yield text[index:index + size]

    def generate():
        yield f"event: meta\ndata: {json.dumps({'request_id': req_id, 'session_id': session_id, 'temp_unit': temp_unit}, ensure_ascii=False)}\n\n"
        try:
            result = process_prompt_from_app_structured(
                prompt_for_processing,
                location=location,
                tone=tone,
                conversation_history=conv_history
            )
            if result.get("error"):
                raise ValueError(result.get("error"))

            weather_payload = dict(result)
            weather_payload.pop("raw", None)
            weather_payload["session_id"] = session_id
            weather_payload["tone"] = tone
            _attach_temp_unit_metadata(weather_payload, temp_unit)
            yield f"event: weather\ndata: {json.dumps(weather_payload, ensure_ascii=False)}\n\n"

            text = result.get("text_summary") or result.get("summary") or ""
            for chunk in text_chunks(text):
                safe_chunk = chunk.replace("\n", "\\n")
                yield f"data: {safe_chunk}\n\n"

            if session_id and text:
                store_exchange(session_id, user_prompt, text)

            yield "data: [DONE]\n\n"
        except Exception as ex:
            if session_id:
                session_logger.log_error(session_id, f"Stream prompt processing error: {str(ex)}")
            payload = {"error": str(ex), "request_id": req_id}
            if ENV == "dev":
                payload["trace"] = traceback.format_exc()
            yield f"event: error\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        return

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx response buffering
            "X-Request-ID": req_id,
        },
    )
