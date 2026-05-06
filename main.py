# main.py

import os
import sys
import time
import json
import uuid
import traceback
import requests as http

# Load .env before anything else so validate_env() sees the vars
from dotenv import load_dotenv
load_dotenv()

# ========================================
# Startup Environment Validation
# ========================================
REQUIRED_ENV_VARS = [
    "OPENAI_API_KEY",
    "OPENWEATHER_API_KEY",
    "WEATHERAPI_KEY",
    "GEOLOCATION_API_KEY",
    "FIREBASE_ADMIN_JSON",
    "SMTP_HOST",
    "SMTP_USER",
    "SMTP_PASS",
]

def validate_env():
    missing = [v for v in REQUIRED_ENV_VARS if not os.getenv(v, "").strip()]
    if missing:
        for var in missing:
            print(f"❌ Missing required environment variable: {var}")
        sys.exit(1)
    print("✅ All required environment variables present")

validate_env()

# Safe to import env-dependent modules now
from flask import Flask, request, jsonify, g
from flask_cors import CORS
from datetime import datetime
from routes import bp as routes_bp
from threading import Thread

from weather_agent import monitor_all_sessions_loop
from weather_agent import weather_agent_bp
from conversation_manager import conversation_manager
from extensions import limiter
from conversation_db import init_db as _init_conversation_db

app = Flask(__name__)
limiter.init_app(app)
_init_conversation_db()

# ========================================
# CORS Configuration
# ========================================
ENV = os.getenv("ENV", "prod").strip().lower()

if ENV in ("dev", "development"):
    CORS(app,
         resources={r"/*": {
             "origins": "*",
             "allow_headers": ["Content-Type", "Authorization"],
             "methods": ["GET", "POST", "OPTIONS", "PUT", "DELETE"],
             "expose_headers": ["Content-Type", "X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset", "Retry-After"],
             "supports_credentials": True
         }})
    print("⚠️ CORS: Development mode - allowing all origins")
else:
    allowed_origins = [
        "https://weatherjackass.com",
        "https://www.weatherjackass.com",
        "http://localhost:3000",
        "http://localhost:5000",
    ]
    CORS(app,
         resources={r"/*": {
             "origins": allowed_origins,
             "allow_headers": ["Content-Type", "Authorization"],
             "methods": ["GET", "POST", "OPTIONS"],
             "expose_headers": ["Content-Type", "X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset", "Retry-After"],
             "supports_credentials": True
         }})
    print(f"🔒 CORS: Production mode - allowing: {allowed_origins}")

# ========================================
# Request/Response Logging + Request ID
# ========================================
_SILENT_PATHS = {"/health", "/health/deep"}

@app.before_request
def log_request():
    g.start_time = time.time()
    g.request_id = str(uuid.uuid4())
    if request.path in _SILENT_PATHS:
        return
    rid = f"[REQ-{g.request_id[:8]}]"
    print(f"\n{'='*60}")
    print(f"📥 {rid} REQUEST [{datetime.now().strftime('%H:%M:%S')}]")
    print(f"{'='*60}")
    print(f"{rid} Method: {request.method}")
    print(f"{rid} Path: {request.path}")
    print(f"{rid} Origin: {request.headers.get('Origin', 'No origin')}")
    if request.is_json:
        try:
            body = request.get_json()
            print(f"{rid} Body: {json.dumps(body, indent=2)}")
        except Exception:
            pass

@app.after_request
def log_response(response):
    req_id = g.get("request_id", "")
    # Always attach the header so every response carries it
    response.headers["X-Request-ID"] = req_id

    # Inject request_id into 4xx/5xx JSON bodies so error messages are reportable
    if response.status_code >= 400 and response.is_json:
        try:
            body = response.get_json(silent=True)
            if isinstance(body, dict) and "request_id" not in body:
                body["request_id"] = req_id
                response.set_data(json.dumps(body))
                response.content_type = "application/json"
        except Exception:
            pass

    if request.path in _SILENT_PATHS:
        return response

    rid = f"[REQ-{req_id[:8]}]" if req_id else ""
    duration = time.time() - g.get("start_time", time.time())
    print(f"\n{'='*60}")
    print(f"📤 {rid} RESPONSE [{datetime.now().strftime('%H:%M:%S')}] - {duration:.3f}s")
    print(f"{rid} Status: {response.status}")
    print(f"{'='*60}\n")
    return response

# ========================================
# Error Handler
# ========================================
@app.errorhandler(Exception)
def handle_error(error):
    error_trace = traceback.format_exc()
    error_id = f"ERR-{int(time.time())}"
    req_id = g.get("request_id", "unknown")
    rid = f"[REQ-{req_id[:8]}]"
    print(f"\n{'🚨'*30}")
    print(f"🚨 {rid} ERROR [{error_id}]")
    print(error_trace)
    print(f"{'🚨'*30}\n")
    if ENV == "dev":
        return jsonify({
            "error": str(error),
            "error_type": type(error).__name__,
            "error_id": error_id,
            "request_id": req_id,
            "trace": error_trace,
            "timestamp": datetime.now().isoformat()
        }), 500
    return jsonify({
        "error": "Internal server error",
        "error_id": error_id,
        "request_id": req_id,
        "timestamp": datetime.now().isoformat()
    }), 500

# ========================================
# Rate Limit Handler
# ========================================
@app.errorhandler(429)
def rate_limit_exceeded(e):
    req_id = g.get("request_id", "unknown")
    rid = f"[REQ-{req_id[:8]}]"
    print(f"⚠️ {rid} Rate limit exceeded: {request.method} {request.path} — {e.description}")
    response = jsonify({
        "error": "Slow down, the donkey needs a break.",
        "retry_after": 60,
        "request_id": req_id,
    })
    response.status_code = 429
    response.headers["Retry-After"] = "60"
    return response

# ========================================
# Register Blueprints
# ========================================
app.register_blueprint(routes_bp)
app.register_blueprint(weather_agent_bp, url_prefix="/weather")

# ========================================
# Health Checks
# ========================================
@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "environment": ENV,
        "features": {
            "conversation_manager": True,
            "weather_agent": True,
            "cors_enabled": True
        }
    })


@app.route("/health/deep", methods=["GET"])
def health_check_deep():
    """Ping each external API and report reachability + latency."""
    services = {}
    overall = "healthy"

    def ping(name, method, url, **kwargs):
        nonlocal overall
        t0 = time.time()
        try:
            r = method(url, timeout=5, **kwargs)
            latency = round((time.time() - t0) * 1000)
            ok = r.status_code == 200
            services[name] = {
                "status": "ok" if ok else "error",
                "http_status": r.status_code,
                "latency_ms": latency,
            }
            if not ok:
                overall = "degraded"
        except Exception as exc:
            services[name] = {"status": "error", "error": str(exc)}
            overall = "degraded"

    wa_key = os.getenv("WEATHERAPI_KEY", "")
    if wa_key:
        ping("weatherapi", http.get,
             "http://api.weatherapi.com/v1/current.json",
             params={"key": wa_key, "q": "London"})
    else:
        services["weatherapi"] = {"status": "not_configured"}
        overall = "degraded"

    ow_key = os.getenv("OPENWEATHER_API_KEY", "")
    if ow_key:
        ping("openweather", http.get,
             "http://api.openweathermap.org/data/2.5/weather",
             params={"q": "London", "appid": ow_key})
    else:
        services["openweather"] = {"status": "not_configured"}
        overall = "degraded"

    ai_key = os.getenv("OPENAI_API_KEY", "")
    if ai_key:
        ping("openai", http.get,
             "https://api.openai.com/v1/models",
             headers={"Authorization": f"Bearer {ai_key}"})
    else:
        services["openai"] = {"status": "not_configured"}
        overall = "degraded"

    return jsonify({
        "status": overall,
        "timestamp": datetime.now().isoformat(),
        "environment": ENV,
        "services": services,
    })


# ========================================
# Background Threads
# ========================================
def cleanup_conversations():
    while True:
        try:
            time.sleep(3600)
            cleaned = conversation_manager.cleanup_expired_sessions()
            if cleaned > 0:
                print(f"🧹 Cleaned up {cleaned} expired sessions")
        except Exception as e:
            print(f"⚠️ Cleanup error: {e}")

cleanup_thread = Thread(target=cleanup_conversations, daemon=True)
cleanup_thread.start()

if os.getenv("START_WEATHER_MONITOR", "").lower() == "true":
    print("🤖 Starting weather monitoring agent...")
    agent_thread = Thread(target=monitor_all_sessions_loop, daemon=True)
    agent_thread.start()
    print("✅ Weather monitoring agent started")

# ========================================
# Startup
# ========================================
if __name__ == "__main__":
    PORT = int(os.environ.get("PORT", 5000))

    print(f"\n{'🚀'*30}")
    print(f"Starting Mister Donkey Backend")
    print(f"{'🚀'*30}")
    print(f"Environment: {ENV}")
    print(f"Port: {PORT}")
    print(f"Debug: {ENV == 'dev'}")
    print(f"Conversation Manager: Active")
    print(f"{'🚀'*30}\n")

    app.run(
        debug=(ENV == "dev"),
        host="0.0.0.0",
        port=PORT
    )
