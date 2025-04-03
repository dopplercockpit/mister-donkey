# 'process_app_prompt.py'
# Main prompt processing function for Doppler Tower - prompt interpreter

import re
from datetime import datetime, timedelta
from dopplertower_engine import get_full_weather_summary


def extract_city_from_prompt(prompt):
    # Naive city extraction based on capitalized words (fallback if GPT not used)
    matches = re.findall(r'\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\b', prompt)
    return matches[-1] if matches else None


def process_app_prompt(prompt_text, fallback_city="Lyon"):
    # Step 1: Try to get city from prompt
    city_guess = extract_city_from_prompt(prompt_text)
    city_query = city_guess if city_guess else fallback_city

    # Step 2: Use the full weather engine to retrieve data
    result = get_full_weather_summary(city_query, user_prompt=prompt_text, timezone_offset=0)

    # Add a fallback message if GPT failed
    if "gpt_summary" not in result and "summary" in result:
        result["gpt_summary"] = result["summary"]

    return result
