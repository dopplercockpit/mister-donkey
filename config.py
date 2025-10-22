# config.py
import os

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "").strip()
WEATHERAPI_KEY = os.getenv("WEATHERAPI_KEY", "").strip()

ENV = os.getenv("ENV", "prod").strip()
DEFAULT_UNITS = os.getenv("UNITS", "metric").strip()
