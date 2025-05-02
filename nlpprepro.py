import os
import json
from openai import OpenAI

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
client = OpenAI(api_key=OPENAI_API_KEY)

def preprocess_with_gpt(prompt_text: str) -> dict:
    """
    Uses GPT to extract structured intent from fuzzy weather prompts.
    Returns: dict with keys: city, time_context, intent, special_request
    """
    system_msg = (
        "You are an assistant that extracts structured data from user messages related to weather. "
        "You do not reply conversationally. You return only a JSON object with the following keys:\n\n"
        "- city: string (most likely place mentioned)\n"
        "- time_context: string ('now', 'tonight', 'tomorrow', 'next week', etc.)\n"
        "- intent: string ('current', 'forecast', 'historical')\n"
        "- special_request: string ('what to wear', 'air quality', 'storm warning', etc. or just 'general')\n\n"
        "If a field is not clearly mentioned, use null."
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt_text}
            ],
            temperature=0.2,
            max_tokens=150
        )
        reply = response.choices[0].message.content
        return json.loads(reply)
    except Exception as e:
        print(f"🤬 Preprocessor GPT error: {e}")
        return {}
