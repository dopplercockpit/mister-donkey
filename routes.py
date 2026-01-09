# routes.py (UPDATED VERSION)
# Fixes: Added tone selector and conversation history support

from datetime import datetime
from flask import Blueprint, request, jsonify
from flask_cors import cross_origin
import traceback
import os
import json

# Configuration
from config import ENV

# Helper for reverse geocoding
from geo_utils_helper import reverse_geolocate

# Main logic to process the weather prompt
from process_app_prompt import process_prompt_from_app

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

# Create a Blueprint
bp = Blueprint("routes", __name__)

@bp.route("/", methods=["GET"])
def home():
    """GET / - Simple sanity-check endpoint."""
    return jsonify({
        "service": "Mister Donkey Weather API",
        "version": "2.0",
        "features": [
            "Weather forecasts",
            "Tone selection (8 personalities)",
            "Conversation history",
            "City resolution",
            "Auto-loading"
        ],
        "endpoints": {
            "/prompt": "Main weather query endpoint",
            "/geo/reverse": "Reverse geocoding",
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
        return jsonify({"error": "Missing 'lat' or 'lon' in request body."}), 400

    try:
        city_name = reverse_geolocate(lat, lon)
    except Exception as ex:
        return jsonify({"error": f"Reverse geolocation failed: {str(ex)}"}), 500

    if not city_name:
        return jsonify({"error": "Could not determine city from coordinates."}), 500

    return jsonify({"city": city_name})

@bp.route("/agents", methods=["GET"])
def get_all_agents():
    """GET /agents - Return list of scheduled agents."""
    try:
        agents = get_agents()
        return jsonify(agents)
    except Exception as ex:
        return jsonify({"error": f"Failed to retrieve agents: {str(ex)}"}), 500

@bp.route("/agents", methods=["POST"])
def add_or_update_agent():
    """POST /agents - Create/update scheduled Weather Agent."""
    data = request.get_json() or {}

    required_fields = ["user_id", "city", "times", "timezone"]
    missing = [f for f in required_fields if f not in data]
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400

    times = data.get("times")
    if not isinstance(times, list) or not all(isinstance(t, str) and ":" in t for t in times):
        return jsonify({"error": "Field 'times' must be a list of 'HH:MM' strings."}), 400

    try:
        add_agent(
            user_id=data["user_id"],
            location=data["city"],
            reminder_times=times,
            tz_string=data["timezone"]
        )
        return jsonify({"status": "Agent saved to DB!"})
    except Exception as ex:
        return jsonify({"error": f"Failed to save agent: {str(ex)}"}), 500

# NEW: Tone management endpoints
@bp.route("/tones", methods=["GET"])
@cross_origin()
def get_tones():
    """GET /tones - List available personality tones"""
    from dopplertower_engine import TONE_PRESETS

    tones = []
    for key, config in TONE_PRESETS.items():
        tones.append({
            "id": key,
            "name": config.get("name", key.replace("_", " ").title()),
            "description": config["system_prompt"][:150] + "...",
            "emoji": {
                "sarcastic": "🙄",
                "pirate": "🏴‍☠️",
                "professional": "📊",
                "hippie": "☮️",
                "drill_sergeant": "🎖️",
                "gen_z": "💅",
                "noir_detective": "🕵️",
                "shakespeare": "🎭"
            }.get(key, "🌦️")
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
    
    # NEW: Tone and conversation parameters
    tone = data.get("tone", "sarcastic")
    session_id = data.get("session_id")

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
        
        return jsonify({
            "error": str(ex),
            "error_type": type(ex).__name__,
            "trace": error_trace if ENV == "dev" else "Enable dev mode for trace",
            "timestamp": datetime.now().isoformat()
        }), 500

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
        return jsonify({"error": error_msg}), 400

    # NEW: Handle conversation history
    conversation_history = None
    if session_id:
        conversation_history = get_conversation(session_id)
        print(f"💬 Loaded {len(conversation_history)} previous messages")

    # 4) Process the prompt with tone and conversation
    try:
        result = process_prompt_from_app(
            modified_prompt, 
            location=location,
            tone=tone,  # NEW
            conversation_history=conversation_history  # NEW
        )
        
        # Add message to conversation history
        if session_id:
            add_message_to_conversation(session_id, "user", user_prompt)
            add_message_to_conversation(session_id, "assistant", result.get("summary", ""))
            result["session_id"] = session_id
            result["conversation_length"] = len(get_conversation(session_id))
        
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
        
        debug_info = {
            "error": error_msg,
            "trace": error_trace if ENV == "dev" else "Enable dev mode for trace",
            "debug_enabled": debug_requested or is_auto_request
        }
        
        if is_auto_request:
            print(f"🛑 Auto-load failed: {error_msg}")
            error_msg = f"Auto-loading failed: {error_msg}"
        
        print(f"❌ ERROR in process_prompt_from_app:\n{error_trace}")

        return jsonify({"error": error_msg, "debug_info": debug_info}), 500


@bp.route("/prompt/structured", methods=["POST"])
@cross_origin()
def handle_prompt_structured():
    """
    POST /prompt/structured - Returns structured JSON weather response.

    NEW in Phase 3:
    - Returns weather data in structured format with separate sections
    - Includes text_summary, weather object, news array, metadata
    - Perfect for building rich UI with weather cards
    - All features from /prompt endpoint available

    Request Body:
        {
            "prompt": "Weather in New York",
            "location": {"lat": 40.7, "lon": -74.0},  // optional
            "tone": "sarcastic",  // optional
            "session_id": "uuid",  // optional for conversation
            "auto": false,  // optional
            "debug": false  // optional
        }

    Response Format:
        {
            "text_summary": "GPT-generated text with personality...",
            "weather": {
                "current": {
                    "temp_c": 15,
                    "temp_f": 59,
                    "conditions": "Partly Cloudy",
                    "icon": "⛅",
                    "humidity": 65,
                    ...
                },
                "forecast_3day": [
                    {
                        "day": "Monday",
                        "temp_high_c": 18,
                        "temp_low_c": 12,
                        "conditions": "Sunny",
                        "icon": "☀️"
                    },
                    ...
                ],
                "alerts": [...],
                "air_quality": "🟢 Good"
            },
            "news": {
                "articles": [...],
                "has_context": true,
                "count": 3
            },
            "metadata": {
                "location": "New York, NY, USA",
                "coords": {"lat": 40.7, "lon": -74.0},
                "tone": "sarcastic",
                "timestamp": "2026-01-06T...",
                "has_alerts": false,
                "has_news": true
            },
            "raw": {  // Full API responses for advanced use
                "current": {...},
                "forecast": {...}
            }
        }
    """
    # Import process function with structured support
    from process_app_prompt import process_prompt_from_app_structured

    data = request.get_json() or {}
    user_prompt = (data.get("prompt") or "").strip()
    location = data.get("location") or {}
    is_auto_request = data.get("auto", False)
    debug_requested = bool(data.get("debug", False))

    # Tone and conversation parameters
    tone = data.get("tone", "sarcastic")
    session_id = data.get("session_id")

    # Validate tone
    from dopplertower_engine import TONE_PRESETS
    if tone not in TONE_PRESETS:
        tone = "sarcastic"
        print(f"⚠️ Invalid tone '{data.get('tone')}', using default: sarcastic")

    # Extract location data
    lat = location.get("lat")
    lon = location.get("lon")

    # Logging
    if debug_requested or is_auto_request:
        print(f"\n🔍 STRUCTURED endpoint: auto={is_auto_request}, debug={debug_requested}, tone={tone}")
        print(f"📝 Input prompt: '{user_prompt}'")
        print(f"📍 Location data: {json.dumps(location)}")
        if session_id:
            print(f"💬 Session ID: {session_id}")
        print("-" * 50)

    # City Resolver preprocessing
    try:
        modified_prompt, resolved_city, resolver_metadata = resolve_city_context(user_prompt, location)
    except Exception as ex:
        error_trace = traceback.format_exc()
        print(f"❌ ERROR in /prompt/structured:\n{error_trace}")

        return jsonify({
            "error": str(ex),
            "error_type": type(ex).__name__,
            "trace": error_trace if ENV == "dev" else "Enable dev mode for trace",
            "timestamp": datetime.now().isoformat()
        }), 500

    # Reverse geocoding fallback
    if lat is not None and lon is not None and not resolved_city:
        try:
            fallback_city = reverse_geolocate(lat, lon)
        except Exception as ex:
            print(f"⚠️ Reverse geocode error: {str(ex)}")
            fallback_city = None

        if fallback_city:
            clean_city = fallback_city.split(",")[0].strip()
            if clean_city.lower() not in modified_prompt.lower():
                modified_prompt = f"{modified_prompt} in {clean_city}" if modified_prompt else f"Weather in {clean_city}"
                print(f"🔄 Structured endpoint: Injected fallback city: '{modified_prompt}'")

    # Validate prompt
    if not modified_prompt:
        error_msg = "Missing 'prompt' in request."
        if is_auto_request:
            error_msg = "Auto-loading failed: Could not determine location or generate prompt."
        return jsonify({"error": error_msg}), 400

    # Handle conversation history
    conversation_history = None
    if session_id:
        conversation_history = get_conversation(session_id)
        print(f"💬 Loaded {len(conversation_history)} previous messages")

    # Process with STRUCTURED flag
    try:
        result = process_prompt_from_app_structured(
            modified_prompt,
            location=location,
            tone=tone,
            conversation_history=conversation_history
        )

        # Add message to conversation history
        if session_id:
            add_message_to_conversation(session_id, "user", user_prompt)
            add_message_to_conversation(session_id, "assistant", result.get("text_summary", ""))
            result["session_id"] = session_id
            result["conversation_length"] = len(get_conversation(session_id))

        # Add metadata
        if debug_requested or is_auto_request:
            result["debug"] = True
            result["debug_info"] = {
                "auto_request": is_auto_request,
                "debug_requested": debug_requested,
                "original_prompt": user_prompt,
                "modified_prompt": modified_prompt,
                "resolver_metadata": resolver_metadata,
                "tone_used": tone,
                "has_conversation_history": conversation_history is not None,
                "endpoint": "structured"
            }

        if is_auto_request:
            result["auto_loaded"] = True
            result["auto_prompt"] = modified_prompt
            print(f"🤖 Structured auto-load successful: '{modified_prompt}'")

        return jsonify(result)

    except Exception as ex:
        error_msg = str(ex)
        error_trace = traceback.format_exc()

        if is_auto_request:
            print(f"🛑 Structured auto-load failed: {error_msg}")
            error_msg = f"Auto-loading failed: {error_msg}"

        print(f"❌ ERROR in /prompt/structured:\n{error_trace}")

        return jsonify({
            "error": error_msg,
            "trace": error_trace if ENV == "dev" else "Enable dev mode for trace",
            "endpoint": "structured"
        }), 500