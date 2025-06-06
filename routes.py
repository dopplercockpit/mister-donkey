# File: /mnt/data/routes.py
# Description: Defines all the HTTP endpoints (routes) for Mister Donkey’s backend.
#              We register this blueprint in main.py, which handles creating the Flask app,
#              applying CORS, and starting the WeatherAgent thread.
#
# Tone: Fun, bubbly, dark-humor-laced, with a dash of profanity and comedic metaphors (Carlin/Sheldon/Fran-style).
#       Comments explain each block’s purpose. We improved existing code (fixed tuple-unpacking bug,
#       removed rogue CORS calls) rather than gutting everything.
#
# Requirements:
#   - Do NOT import or reference `app` here. That’s main.py’s job.
#   - CORS is already configured in main.py; here we optionally use @cross_origin for per-route overrides.
#   - Use resolve_city_context to preprocess prompts, then hand off to process_prompt_from_app.
#   - Fall back to reverse geolocation only if user didn’t explicitly provide a city.
#   - Return proper JSON responses (status codes, error messages) so the front-end doesn’t think it’s hallucinating.
#   - If you see profanity in the comments, blame George Carlin yelling through Sheldon’s mouth.

from flask import Blueprint, request, jsonify
from flask_cors import cross_origin

import os
import json

# Helper for reverse geocoding (lat/lon → “City, Region, Country” string).
from geo_utils_helper import reverse_geolocate

# Main logic to process the weather prompt (OpenAI calls, parsing, etc.).
from process_app_prompt import process_prompt_from_app

# Legacy “agent” (scheduled push) database functions.
from agent_db import add_agent, get_agents

# Our custom city resolver that splits prompts like “weather in Paris” out for us.
from city_resolver import resolve_city_context

# ------------------------------------------------------------------------------
# Create a Blueprint. This is like telling Flask “Here’s a bundle of routes—please register
# them when I give you this blueprint in main.py.” We keep everything neat and modular.
bp = Blueprint("routes", __name__)
# ------------------------------------------------------------------------------

@bp.route("/", methods=["GET"])
def home():
    """
    GET /
    A simple sanity-check endpoint. If you see this in your browser (or curl), it means the
    server is alive and eager to spit out some weather profanity.
    """
    return "👋 Welcome to Mister Donkey's API. Try POSTing to /prompt or /agents."


# ------------------------------------------------------------------------------
@bp.route("/geo/reverse", methods=["POST"])
@cross_origin()  # Let CORS rules from main.py apply; this annotation is a no-op since main.py already set up global CORS.
def reverse_lookup():
    """
    POST /geo/reverse
    Body JSON: { "lat": float, "lon": float }
    Returns JSON: { "city": "City, Region, Country" } or an error JSON.
    
    Purpose: Given a pair of coordinates (lat & lon), return a 
             human-readable city name. Useful for “Hey, Mister Donkey,
             where the hell am I?” requests.
    """
    data = request.get_json() or {}
    lat = data.get("lat")
    lon = data.get("lon")

    # Validate input. If client didn’t send lat/lon, throw a polite middle-finger error.
    if lat is None or lon is None:
        return jsonify({"error": "Missing 'lat' or 'lon' in request body."}), 400

    try:
        city_name = reverse_geolocate(lat, lon)
    except Exception as ex:
        # If reverse_geolocate itself crashed, return a 500 with the message.
        return jsonify({"error": f"Reverse geolocation failed: {str(ex)}"}), 500

    if not city_name:
        # If the helper returns None or empty, treat it as a failure.
        return jsonify({"error": "Could not determine city from coordinates."}), 500

    # Return the sweet, sweet city name. The front-end can now say “Paris” instead of “(48.85, 2.35)”.
    return jsonify({"city": city_name})


# ------------------------------------------------------------------------------
@bp.route("/agents", methods=["GET"])
def get_all_agents():
    """
    GET /agents
    Returns the list of “legacy” scheduled agents from the database.
    We might not even need this if you’ve retired the agent_db approach, but here it is
    just in case you need to fetch all scheduled jobs (user_id, city, times, timezone).
    """
    try:
        agents = get_agents()
        return jsonify(agents)
    except Exception as ex:
        return jsonify({"error": f"Failed to retrieve agents: {str(ex)}"}), 500


# ------------------------------------------------------------------------------
@bp.route("/agents", methods=["POST"])
def add_or_update_agent():
    """
    POST /agents
    Body JSON: { "user_id": str, "city": str, "times": [ "HH:MM", ... ], "timezone": "TZ_STRING" }
    Purpose: Legacy endpoint to create/update a scheduled “Weather Agent” in the DB.
             Expects user_id, city (string), list of time strings, and a timezone string.
             If anything is missing or malformed, we return a 400 with an error message.
    """
    data = request.get_json() or {}

    # Required fields: user_id, city, times[], timezone.
    required_fields = ["user_id", "city", "times", "timezone"]
    missing = [f for f in required_fields if f not in data]
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400

    # Validate that times is a list of "HH:MM" strings.
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


# ------------------------------------------------------------------------------
@bp.route("/prompt", methods=["POST"])
@cross_origin()  # Explicitly allowing CORS per-route. Global CORS is already configured in main.py.
def handle_prompt():
    """
    POST /prompt
    Body JSON: { "prompt": str, "location"?: { "lat": float, "lon": float } }
    Returns: JSON. Built by process_prompt_from_app(), including weather data, gags, and profanity.
    
    Flow:
      1) Extract the raw user prompt (e.g. “What’s the weather?”). 
      2) Extract optional location { lat, lon } if front-end passed geolocation.
      3) Call resolve_city_context(prompt, location) → (modified_prompt, resolved_city, metadata).
         - modified_prompt: The prompt with “in CITY” injected if the user already typed it
                           or if our logic spotted it (e.g. “outside” or “here”).
         - resolved_city:  A string like “Paris” if found; otherwise None.
         - metadata:       A dict containing debug info (we’ll print for logs).
      4) If we have lat/lon but NO resolved_city, call reverse_geolocate(lat, lon) to get fallback_city.
         - Inject fallback_city into the prompt: “{modified_prompt} in {fallback_city}”.
      5) If modified_prompt is now empty (should never happen unless prompt was empty), return 400.
      6) Finally, hand off the modified_prompt + location to process_prompt_from_app(), which calls OpenAI,
         fetches weather, etc. and returns a rich JSON response (message, forecast, emoji, etc.).
      7) If anything blows up, catch Exception(e) and return a 500 JSON with error + repr(e) for debugging.
    """
    data = request.get_json() or {}
    user_prompt = (data.get("prompt") or "").strip()
    location = data.get("location") or {}
    lat = location.get("lat")
    lon = location.get("lon")

    # 1) City Resolver: Preprocess user prompt. This can capture things like “in Paris” or “here” etc.
    try:
        modified_prompt, resolved_city, resolver_metadata = resolve_city_context(user_prompt, location)
    except Exception as ex:
        # If city_resolver itself fails, bail out with 500.
        return jsonify({"error": f"City resolution failed: {str(ex)}"}), 500

    # Print debugging metadata for logs. If you see a 500, grep for "Resolver Debug" in your logs.
    print("🧠 Resolver Debug:", json.dumps(resolver_metadata))

    # If city was resolved but stripped from prompt, put it the fuck back
    if resolved_city and resolved_city.lower() not in modified_prompt.lower():
        modified_prompt = f"{modified_prompt} in {resolved_city}"
        print(f"🔁 Re-injected resolved city into prompt: '{modified_prompt}'")

    # 2) If front-end gave us lat/lon but the user didn’t explicitly mention a city (resolved_city is None),
    #    we’ll do reverse geocoding to give a fallback city name and inject it.
    if lat is not None and lon is not None and not resolved_city:
        try:
            fallback_city = reverse_geolocate(lat, lon)
        except Exception as ex:
            # If reverse geolocation fails, log it but continue with whatever prompt we have.
            print(f"⚠️ Reverse geocode error: {str(ex)}")
            fallback_city = None

        if fallback_city:
            # Chop off extra fluff like "street, zip, country"
            clean_city = fallback_city.split(",")[0].strip()

            # Avoid redundant injection if prompt already includes the city name
            if clean_city.lower() not in modified_prompt.lower():
                if modified_prompt:
                    modified_prompt = f"{modified_prompt} in {clean_city}"
                else:
                    modified_prompt = f"Weather in {clean_city}"
                print(f"🔄 Injecting cleaned fallback city into prompt: '{modified_prompt}'")

    # 3) If we still have no prompt text (user_prompt was blank and we couldn’t inject anything), return 400.
    if not modified_prompt:
        return jsonify({"error": "Missing 'prompt' in request. I need SOMETHING to work with."}), 400

    # 4) Kick the real engine—process_prompt_from_app does the heavy lifting:
    #    - Interpret the prompt (OpenAI API calls, NLP, etc.)
    #    - Fetch weather data from whatever upstream API
    #    - Compose a humor-laden, profanity-spiced response
    try:
        result = process_prompt_from_app(modified_prompt, location=location)
        # The result is already a JSON-serializable dict, e.g.
        # {
        #   "text": "Weather’s crap: 12°C, raining like a Russian hooker’s tears ☂️",
        #   "forecast": { ... },
        #   "metadata": { ... }
        # }
        return jsonify(result)
    except Exception as ex:
        # If the GPT pipeline or weather fetch blows up, send it back as a 500.
        # Including repr(ex) so we can see if it was a failed HTTP call, an OpenAI API quota error, etc.
        return jsonify({"error": str(ex), "trace": repr(ex)}), 500
