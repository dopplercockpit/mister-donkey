import os
from flask import Flask
from flask_cors import CORS
from dotenv import load_dotenv  # <-- 1) import
from routes import bp as routes_bp

# 2) load .env
load_dotenv()

app = Flask(__name__)
#CORS(app, resources={r"/prompt": {"origins": "http://127.0.0.1:5173"}}) For local testing only.DO NOT USE IN PRODUCTION.
# ↑ Adjust "http://127.0.0.1:5173" to match your React dev server’s actual origin
# If your front-end is at http://localhost:5173, use that. 
# For broader testing, you can do CORS(app, resources={r"/*": {"origins": "*"}}) for development.

CORS(app, origins=["https://weatherjackass.com"])# This is the original line for COR for production. 
# Dormant string - CORS(app, origins=["https://www.weatherjackass.com"])

# Register the blueprint from routes.py
app.register_blueprint(routes_bp)

if __name__ == "__main__":
    PORT = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=PORT)
