# routes.py
from flask import Blueprint, request, jsonify
from flask_cors import cross_origin

import json
import os

from geo_utils_helper import reverse_geolocate
from process_app_prompt import process_prompt_from_app, extract_city_from_prompt
from agent_db import add_agent, get_agents  # If you still want the old “/agents” endpoints

bp = Blueprint("routes", __name__)

@bp.route("/", methods=["GET"])
def home():
    return "👋 Welcome to Mister Donkey's API. Try POSTing to /prompt or /agents."

@bp.route("/geo/reverse", methods=["POST"])
def reverse_lookup():
    """
    POST /geo/reverse
    Body: { lat: number, lon: number }
    Returns: { city: "City, Region, Country" } or error.
    """
    data = request.json or {}
    lat = data.get("lat")
    lon = data.get("lon")
    if lat is None or lon is None:
        return jsonify({"error": "Missing coordinates"}), 400

    city = reverse_geolocate(lat, lon)
    if not city:
        return jsonify({"error": "Failed to reverse geolocate"}), 500
    return jsonify({"city": city})

@bp.route("/agents", methods=["GET"])
def get_all_agents():
    """
    GET /agents
    Returns the list of “legacy” agents from agent_db (if you're still using them).
    """
    try:
        agents = get_agents()
        return jsonify(agents)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route("/agents", methods=["POST"])
def add_or_update_agent():
    """
    POST /agents
    Legacy endpoint to save a scheduled agent. 
    Body must include: { user_id, city, times: [ "HH:MM", ... ], timezone }.
    """
    data = request.json or {}
    required_fields = ["user_id", "city", "times", "timezone"]
    if not all(field in data for field in required_fields):
        return jsonify({"error": "Missing required fields"}), 400

    if not isinstance(data["times"], list) or not all(":" in t for t in data["times"]):
        return jsonify({"error": "Times must be a list of HH:MM strings"}), 400

    try:
        add_agent(
            user_id=data["user_id"],
            location=data["city"],
            reminder_times=data["times"],
            tz_string=data["timezone"]
        )
        return jsonify({"status": "Agent saved to DB!"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route("/prompt", methods=["POST"])
@cross_origin()  # allow any origin for development; you can lock this down later
def handle_prompt():
    """
    POST /prompt
    Body: { prompt: string, location?: { lat: number, lon: number } }
    Returns: JSON from process_prompt_from_app(...)
    """
    data = request.get_json() or {}
    user_prompt = data.get("prompt", "").strip()
    location = data.get("location") or {}
    lat = location.get("lat")
    lon = location.get("lon")

    # If front‐end passed coords but user didn't already type “in City”, append it
    if lat is not None and lon is not None and not extract_city_from_prompt(user_prompt):
        city = reverse_geolocate(lat, lon)
        if city:
            if user_prompt:
                user_prompt = f"{user_prompt} in {city}"
            else:
                user_prompt = f"Weather in {city}"

    if not user_prompt:
        return jsonify({"error": "Missing 'prompt' in request."}), 400

    try:
        result = process_prompt_from_app(user_prompt, location=location)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
