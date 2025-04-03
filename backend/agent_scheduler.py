# agent_scheduler.py
# Agent scheduler for Doppler Tower - web/app

import json
import time
from datetime import datetime
from dopplertower_engine import get_full_weather_summary
import pytz
import os

AGENTS_FILE = "agents.json"
LOG_DIR = "agent_logs"
os.makedirs(LOG_DIR, exist_ok=True)

# Example structure of each agent:
# {
#   "user_id": "test@example.com",
#   "city": "Lyon",
#   "times": ["07:00", "16:00"],
#   "timezone": "CET"
# }

def load_agents():
    try:
        with open(AGENTS_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading agents: {e}")
        return []

def check_and_trigger(agent):
    tz = pytz.timezone(agent.get("timezone", "UTC"))
    now = datetime.now(tz).strftime("%H:%M")

    if now in agent["times"]:
        print(f"⏰ Triggering weather check for {agent['user_id']} in {agent['city']} at {now} ({agent['timezone']})")
        result = get_full_weather_summary(agent["city"], user_prompt="Automated agent check", timezone_offset=0)

        log_path = os.path.join(LOG_DIR, f"{agent['user_id'].replace('@', '_at_')}_{agent['city'].replace(' ', '_')}.log")
        with open(log_path, "a") as log_file:
            log_file.write(f"\n\n=== {datetime.now(tz).isoformat()} ===\n")
            log_file.write(result["summary"] + "\n")

        # In future: push via email, mobile, or Telegram
        print(f"✅ Logged update for {agent['user_id']} → {log_path}")
    else:
        print(f"⏱️ Not time yet for {agent['city']} ({agent['timezone']} now {now})")

def run_scheduler():
    print("🔁 Starting Kickass Donkey Agent Scheduler...")
    while True:
        agents = load_agents()
        for agent in agents:
            check_and_trigger(agent)
        print("🌙 Sleeping for 60 seconds...")
        time.sleep(60)

if __name__ == "__main__":
    run_scheduler()
