# routes.py
from flask import Flask, request, jsonify
import json
import os
from geo_utils_helper import reverse_geolocate
from process_app_prompt import process_app_prompt
from agent_db import add_agent, get_agents  # NEW

app = Flask(__name__)


@app.route("/", methods=["GET"])
def home():
    return "👋 Welcome to Mister Donkey's API. Try POSTing to /prompt or /agents."

@app.route("/geo/reverse", methods=["POST"])
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

@app.route("/agents", methods=["GET"])
def get_all_agents():
    try:
        agents = get_agents()
        return jsonify(agents)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/agents", methods=["POST"])
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

@app.route("/prompt", methods=["POST"])
def handle_prompt():
    data = request.json
    user_prompt = data.get("prompt")

    if not user_prompt:
        return jsonify({"error": "Missing 'prompt' in request."}), 400

    try:
        result = process_app_prompt(user_prompt)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
