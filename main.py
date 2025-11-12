# main.py (CORRECTED VERSION)
# Fixes: CORS issues, adds conversation manager import

import os
import sys
import time
import json
import traceback
from flask import Flask, request, g
from flask_cors import CORS
from dotenv import load_dotenv
from datetime import datetime
from routes import bp as routes_bp
from threading import Thread

# ✅ FIXED: Import weather agent properly
from weather_agent import monitor_all_sessions_loop
from weather_agent import weather_agent_bp

# ✅ NEW: Import conversation manager
from conversation_manager import conversation_manager

# Load .env
load_dotenv()

app = Flask(__name__)

# ========================================
# CORS Configuration (CRITICAL FIX)
# ========================================
ENV = os.getenv("ENV", "prod").strip().lower()

# ✅ FIXED: More permissive CORS for debugging
if ENV == "dev" or ENV == "development":
    # Development: Allow all origins
    CORS(app, 
         resources={r"/*": {
             "origins": "*",
             "allow_headers": ["Content-Type", "Authorization"],
             "methods": ["GET", "POST", "OPTIONS", "PUT", "DELETE"],
             "expose_headers": ["Content-Type"],
             "supports_credentials": True
         }})
    print("⚠️ CORS: Development mode - allowing all origins")
else:
    # Production: Allow both your domains
    allowed_origins = [
        "https://weatherjackass.com",
        "https://www.weatherjackass.com",
        "http://localhost:3000",  # ✅ Added for local testing
        "http://localhost:5000",  # ✅ Added for local testing
    ]
    CORS(app, 
         resources={r"/*": {
             "origins": allowed_origins,
             "allow_headers": ["Content-Type", "Authorization"],
             "methods": ["GET", "POST", "OPTIONS"],
             "expose_headers": ["Content-Type"],
             "supports_credentials": True
         }})
    print(f"🔒 CORS: Production mode - allowing: {allowed_origins}")

# ========================================
# Request/Response Logging
# ========================================
@app.before_request
def log_request():
    """Log incoming requests"""
    g.start_time = time.time()
    
    if request.path == "/health":
        return
    
    print(f"\n{'='*60}")
    print(f"📥 REQUEST [{datetime.now().strftime('%H:%M:%S')}]")
    print(f"{'='*60}")
    print(f"Method: {request.method}")
    print(f"Path: {request.path}")
    print(f"Origin: {request.headers.get('Origin', 'No origin')}")
    
    if request.is_json:
        try:
            body = request.get_json()
            print(f"Body: {json.dumps(body, indent=2)}")
        except:
            pass

@app.after_request
def log_response(response):
    """Log responses and add CORS headers"""
    if request.path == "/health":
        return response
    
    duration = time.time() - g.get('start_time', time.time())
    print(f"\n{'='*60}")
    print(f"📤 RESPONSE [{datetime.now().strftime('%H:%M:%S')}] - {duration:.3f}s")
    print(f"Status: {response.status}")
    print(f"{'='*60}\n")
    
    return response

# ========================================
# Error Handler
# ========================================
@app.errorhandler(Exception)
def handle_error(error):
    """Catch all errors"""
    error_trace = traceback.format_exc()
    error_id = f"ERR-{int(time.time())}"
    
    print(f"\n{'🚨'*30}")
    print(f"ERROR [{error_id}]")
    print(error_trace)
    print(f"{'🚨'*30}\n")
    
    if ENV == "dev":
        return {
            "error": str(error),
            "error_type": type(error).__name__,
            "error_id": error_id,
            "trace": error_trace,
            "timestamp": datetime.now().isoformat()
        }, 500
    else:
        return {
            "error": "Internal server error",
            "error_id": error_id,
            "timestamp": datetime.now().isoformat()
        }, 500

# ========================================
# Register Blueprints
# ========================================
app.register_blueprint(routes_bp)
app.register_blueprint(weather_agent_bp, url_prefix="/weather")

# ========================================
# Health Check
# ========================================
@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "environment": ENV,
        "features": {
            "conversation_manager": True,
            "weather_agent": True,
            "cors_enabled": True
        }
    }

# ========================================
# Optional: Conversation cleanup
# ========================================
def cleanup_conversations():
    """Cleanup expired conversations periodically"""
    while True:
        try:
            time.sleep(3600)  # Every hour
            cleaned = conversation_manager.cleanup_expired_sessions()
            if cleaned > 0:
                print(f"🧹 Cleaned up {cleaned} expired sessions")
        except Exception as e:
            print(f"⚠️ Cleanup error: {e}")

cleanup_thread = Thread(target=cleanup_conversations, daemon=True)
cleanup_thread.start()

# ========================================
# Optional: Weather Monitor
# ========================================
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