from flask_cors import CORS
from routes import app

CORS(app, resources={r"/prompt": {"origins": "http://localhost:8080"}})


if __name__ == "__main__":
    app.run(debug=True)
