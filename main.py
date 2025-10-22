import os
from flask import Flask
from flask_cors import CORS
from dotenv import load_dotenv  # <-- 1) import
from routes import bp as routes_bp
from threading import Thread
from weather_agent import monitor_all_sessions_loop
from weather_agent import weather_agent_bp

# 2) load .env
load_dotenv()

app = Flask(__name__)
#CORS(app, resources={r"/prompt": {"origins": "http://127.0.0.1:5173"}}) For local testing only.DO NOT USE IN PRODUCTION.
# ↑ Adjust "http://127.0.0.1:5173" to match your React dev server’s actual origin
# If your front-end is at http://localhost:5173, use that. 
# For broader testing, you can do CORS(app, resources={r"/*": {"origins": "*"}}) for development.

# 🛡️ Apply CORS to ALL routes. ONLY allow your actual prod domains!
CORS(app, resources={r"/*": {"origins": [
    "https://weatherjackass.com",
    "https://www.weatherjackass.com"
]}})

# Register the blueprint from routes.py
app.register_blueprint(routes_bp)
app.register_blueprint(weather_agent_bp, url_prefix="/weather")

if os.getenv("START_WEATHER_MONITOR", "").lower() == "true":
    from threading import Thread
    from weather_agent import monitor_all_sessions_loop
    agent_thread = Thread(target=monitor_all_sessions_loop, daemon=True)
    agent_thread.start()

if __name__ == "__main__":
    PORT = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=PORT)
