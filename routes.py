# routes.py (CLEANED VERSION)
# Purpose: accept JSON, pass to the processor, return a JSON response.

from datetime import datetime
from flask import Blueprint, request, jsonify
from flask_cors import cross_origin
import traceback
import os
import json

# Configuration
from config import ENV

# Helper for reverse geocoding (lat/lon → "City, Region, Country" string).
from geo_utils_helper import reverse_geolocate

# Main logic to process the weather prompt (OpenAI calls, parsing, etc.).
from process_app_prompt import process_prompt_from_app

# Legacy "agent" (scheduled push) database functions.
from agent_db import add_agent, get_agents

# Our custom city resolver that splits prompts like "weather in Paris" out for us.
from city_resolver import resolve_city_context

# Create a Blueprint
bp = Blueprint("routes", __name__)

@bp.route("/", methods=["GET"])
def home():
    """GET / - Simple sanity-check endpoint."""
    return "👋 Welcome to Mister Donkey's API. Try POSTing to /prompt or /agents."

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

@bp.route("/prompt", methods=["POST"])
@cross_origin()
def handle_prompt():
    """
    POST /prompt - Main weather prompt endpoint.
    
    Handles both manual prompts and auto-loading requests.
    Auto-loading is triggered by { "auto": true } in the request body.
    Debug output is enabled by { "debug": true } or auto-loading.
    """
    data = request.get_json() or {}
    user_prompt = (data.get("prompt") or "").strip()
    location = data.get("location") or {}
    is_auto_request = data.get("auto", False)
    debug_requested = bool(data.get("debug", False))

    # Extract location data early
    lat = location.get("lat")
    lon = location.get("lon")

    # Enhanced debug logging
    if debug_requested or is_auto_request:
        print(f"\n🔍 Debug enabled: auto={is_auto_request}, debug={debug_requested}")
        print(f"📝 Input prompt: '{user_prompt}'")
        print(f"📍 Location data: {json.dumps(location)}")
        if lat is not None and lon is not None:
            print(f"📍 Coordinates: {lat}, {lon}")
        print("-" * 50)
    
    # 1) City Resolver: Preprocess user prompt
    try:
        modified_prompt, resolved_city, resolver_metadata = resolve_city_context(user_prompt, location)
    except Exception as ex:
        # Log full traceback
        error_trace = traceback.format_exc()
        print(f"❌ ERROR in /prompt:\n{error_trace}")
        
        # Return detailed error to frontend
        return jsonify({
            "error": str(ex),
            "error_type": type(ex).__name__,
            "trace": error_trace if ENV == "dev" else "Enable dev mode for trace",
            "timestamp": datetime.now().isoformat()
        }), 500

    # Enhanced debugging for auto requests
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

    # 4) Process the prompt
    try:
        result = process_prompt_from_app(modified_prompt, location=location)
        
        # Ensure debug flag is set if either condition is true
        if debug_requested or is_auto_request:
            result["debug"] = True
            result["debug_info"] = {
                "auto_request": is_auto_request,
                "debug_requested": debug_requested,
                "original_prompt": user_prompt,
                "modified_prompt": modified_prompt,
                "resolver_metadata": resolver_metadata
            }
        
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
        
        # Log the full error
        print(f"❌ ERROR in process_prompt_from_app:\n{error_trace}")
        
        return jsonify({"error": error_msg, "debug_info": debug_info}), 500