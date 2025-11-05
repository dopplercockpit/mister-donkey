# main.py (PATCHED VERSION)
# Fixes: CORS issues, adds comprehensive logging, supports dev/prod modes

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
from weather_agent import monitor_all_sessions_loop
from weather_agent import weather_agent_bp

# Load .env
load_dotenv()

app = Flask(__name__)

# ========================================
# CORS Configuration (Environment-aware)
# ========================================
ENV = os.getenv("ENV", "prod").strip().lower()

if ENV == "dev" or ENV == "development":
    # Development: Allow all origins for testing
    CORS(app, 
         resources={r"/*": {
             "origins": "*",
             "allow_headers": ["Content-Type", "Authorization"],
             "methods": ["GET", "POST", "OPTIONS", "PUT", "DELETE"],
             "expose_headers": ["Content-Type"],
             "supports_credentials": True
         }})
    print("⚠️ CORS: Development mode - allowing all origins")
    print("⚠️ Security: This should NEVER be used in production!")
else:
    # Production: Strict origin control
    allowed_origins = [
        "https://weatherjackass.com",
        "https://www.weatherjackass.com"
    ]
    CORS(app, 
         resources={r"/*": {
             "origins": allowed_origins,
             "allow_headers": ["Content-Type"],
             "methods": ["GET", "POST", "OPTIONS"],
             "supports_credentials": False
         }})
    print(f"🔒 CORS: Production mode - allowing: {allowed_origins}")

# ========================================
# Request/Response Logging Middleware
# ========================================
@app.before_request
def log_request():
    """Log all incoming requests for debugging"""
    g.start_time = time.time()
    
    # Skip logging for health checks to reduce noise
    if request.path == "/health":
        return
    
    print(f"\n{'='*60}")
    print(f"📥 INCOMING REQUEST [{datetime.now().strftime('%H:%M:%S')}]")
    print(f"{'='*60}")
    print(f"Method: {request.method}")
    print(f"Path: {request.path}")
    print(f"Remote: {request.remote_addr}")
    print(f"User-Agent: {request.headers.get('User-Agent', 'Unknown')[:100]}")
    
    if request.is_json:
        try:
            body = request.get_json()
            # Sanitize sensitive data
            if 'api_key' in body:
                body = {**body, 'api_key': '***REDACTED***'}
            print(f"Body: {json.dumps(body, indent=2)}")
        except Exception as e:
            print(f"Body: <Failed to parse JSON: {e}>")
    elif request.data:
        print(f"Body: {request.get_data(as_text=True)[:500]}")

@app.after_request
def log_response(response):
    """Log all outgoing responses for debugging"""
    # Skip logging for health checks
    if request.path == "/health":
        return response
    
    duration = time.time() - g.get('start_time', time.time())
    
    print(f"\n{'='*60}")
    print(f"📤 OUTGOING RESPONSE [{datetime.now().strftime('%H:%M:%S')}]")
    print(f"{'='*60}")
    print(f"Status: {response.status}")
    print(f"Duration: {duration:.3f}s")
    
    # Add CORS headers for debugging
    print(f"CORS Headers:")
    for header in ['Access-Control-Allow-Origin', 'Access-Control-Allow-Methods']:
        value = response.headers.get(header)
        if value:
            print(f"  {header}: {value}")
    
    if response.is_json:
        try:
            data = response.get_json()
            data_str = json.dumps(data, indent=2)
            
            # Truncate long responses
            if len(data_str) > 1000:
                print(f"Body: {data_str[:1000]}...")
                print(f"  ... (truncated, total {len(data_str)} chars)")
            else:
                print(f"Body: {data_str}")
        except Exception as e:
            print(f"Body: <Failed to parse: {e}>")
    
    print(f"{'='*60}\n")
    return response

# ========================================
# Global Error Handler
# ========================================
@app.errorhandler(Exception)
def handle_error(error):
    """Catch all unhandled errors and return JSON"""
    error_trace = traceback.format_exc()
    error_id = f"ERR-{int(time.time())}"
    
    print(f"\n{'🚨'*30}")
    print(f"UNHANDLED ERROR [{error_id}]")
    print(f"{'🚨'*30}")
    print(error_trace)
    print(f"{'🚨'*30}\n")
    
    # Return detailed error in dev, sanitized in prod
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
            "message": "Please contact support with this error ID",
            "timestamp": datetime.now().isoformat()
        }, 500

# ========================================
# Register Blueprints
# ========================================
app.register_blueprint(routes_bp)
app.register_blueprint(weather_agent_bp, url_prefix="/weather")

# ========================================
# Health Check (before weather monitor starts)
# ========================================
@app.route("/health", methods=["GET"])
def health_check():
    """Detailed health check for debugging"""
    import sys
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "environment": ENV,
        "python_version": sys.version,
        "cors_enabled": True,
        "cors_mode": "permissive (dev)" if ENV == "dev" else "strict (prod)",
        "endpoints": {
            "main": ["/", "/health"],
            "weather": ["/prompt", "/geo/reverse"],
            "agents": ["/agents", "/weather/start-agent", "/weather/status/<user_id>"],
        }
    }

# ========================================
# Optional Weather Monitor (if enabled)
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
    print(f"{'🚀'*30}\n")
    
    app.run(
        debug=(ENV == "dev"),
        host="0.0.0.0",
        port=PORT
    )