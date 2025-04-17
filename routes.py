# routes.py

from flask import Blueprint, request, jsonify
from flask_cors import cross_origin

import json
import os
from geo_utils_helper import reverse_geolocate
from process_app_prompt import process_prompt_from_app
from process_app_prompt import extract_city_from_prompt
from agent_db import add_agent, get_agents

bp = Blueprint("routes", __name__)

@bp.route("/", methods=["GET"])
def home():
    return "👋 Welcome to Mister Donkey's API. Try POSTing to /prompt or /agents."

@bp.route("/geo/reverse", methods=["POST"])
def reverse_lookup():
    data = request.json
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
    try:
        agents = get_agents()
        return jsonify(agents)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route("/agents", methods=["POST"])
def add_or_update_agent():
    data = request.json
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
@cross_origin()  # allow any origin; you can lock this down to your frontend if you like
def handle_prompt():
    data = request.get_json() or {}

    # 1) Grab their raw text prompt
    user_prompt = data.get("prompt", "").strip()

    # 2) If browser passed real coords, reverse‑lookup and inject "in City"
    location = data.get("location") or {}
    lat, lon = location.get("lat"), location.get("lon")
    if lat is not None and lon is not None and not extract_city_from_prompt(user_prompt):
        city = reverse_geolocate(lat, lon)
        if city:
            if user_prompt:
                user_prompt = f"{user_prompt} in {city}"
            else:
                # if they didn't type anything, at least ask for that location
                user_prompt = f"Weather in {city}"

    # 3) If we still have nothing, error out
    if not user_prompt:
        return jsonify({"error": "Missing 'prompt' in request."}), 400

    # 4) Hand off both the text and raw coords
    try:
        result = process_prompt_from_app(user_prompt, location=location)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
