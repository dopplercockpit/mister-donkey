# llm_router.py
# The "Brain" that routes user requests to the correct location and intent.
# Replaces fragile Regex with specific LLM instruction.

import json
import os
from openai import OpenAI
from config import OPENAI_API_KEY, OPENAI_MODEL

client = OpenAI(api_key=OPENAI_API_KEY)

def route_request(user_prompt: str) -> dict:
    """
    Analyzes the user's raw prompt to extract:
    1. The specific target location (if any).
    2. A cleaned version of the prompt (removing the location text).
    
    Returns:
        {
            "target_location": str | None,  # e.g. "Paris, France" or None if using GPS
            "cleaned_prompt": str,          # e.g. "What is the weather?"
            "is_location_explicit": bool    # True if user typed a city, False if vague
        }
    """
    
    system_instruction = (
        "You are a strict semantic router for a weather app. "
        "Your goal is to extract the Geographic Entity the user is asking about.\n\n"
        "RULES:\n"
        "1. If the user mentions a specific city, region, or landmark (e.g., 'Paris', 'The Big Apple', 'Mom's house in Austin'), extract it as 'target_location'.\n"
        "2. If the user implies their CURRENT location (e.g., 'here', 'outside', 'local', 'my area'), set 'target_location' to null.\n"
        "3. Ignore idiom words that look like cities but aren't (e.g., 'Holy Toledo', 'raining cats and dogs').\n"
        "4. Return 'cleaned_prompt' with the location text removed, so the personality engine processes just the question.\n\n"
        "Output strictly valid JSON."
    )

    # We use a simple JSON structure to force the LLM to be precise.
    tools = [
        {
            "type": "function",
            "function": {
                "name": "route_weather_request",
                "description": "Extract location and clean prompt",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "target_location": {
                            "type": ["string", "null"],
                            "description": "The full city/location name, or null if using current GPS location."
                        },
                        "cleaned_prompt": {
                            "type": "string",
                            "description": "The user prompt with the location phrase removed."
                        },
                        "is_location_explicit": {
                            "type": "boolean",
                            "description": "True if a specific place was named, False if 'here' or implied."
                        }
                    },
                    "required": ["cleaned_prompt", "is_location_explicit"]
                }
            }
        }
    ]

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL, 
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_prompt}
            ],
            tools=tools,
            tool_choice={"type": "function", "function": {"name": "route_weather_request"}},
            temperature=0.0
        )

        tool_call = response.choices[0].message.tool_calls[0]
        arguments = json.loads(tool_call.function.arguments)
        
        return arguments

    except Exception as e:
        print(f"🚨 Router LLM failed: {e}")
        # Fallback: assume no location change, return original prompt
        return {
            "target_location": None,
            "cleaned_prompt": user_prompt,
            "is_location_explicit": False
        }


def resolve_city_context_with_llm(prompt_text: str, location: dict = None) -> tuple:
    """
    Wrapper function that uses LLM router and returns data in the format
    expected by the existing city_resolver interface.

    This acts as a drop-in replacement for city_resolver.resolve_city_context()

    Returns:
        Tuple[
            modified_prompt: str,          # Cleaned prompt
            resolved_city: Optional[str],  # City name or None
            metadata: Dict                 # Debug info
        ]
    """
    print(f"🧠 LLM Router: Processing prompt: '{prompt_text}'")

    # Call the LLM router
    router_result = route_request(prompt_text)

    # Extract results
    target_location = router_result.get("target_location")
    cleaned_prompt = router_result.get("cleaned_prompt", prompt_text)
    is_explicit = router_result.get("is_location_explicit", False)

    # Build metadata for debugging
    metadata = {
        "original_prompt": prompt_text,
        "resolution_method": "llm_router",
        "injected_location": False,
        "injected_location_name": None,
        "resolved_city": target_location,
        "is_location_explicit": is_explicit,
        "llm_router_result": router_result
    }

    print(f"🧠 LLM Router Results:")
    print(f"   Target Location: {target_location}")
    print(f"   Cleaned Prompt: '{cleaned_prompt}'")
    print(f"   Is Explicit: {is_explicit}")

    return cleaned_prompt, target_location, metadata


def preprocess_prompt_for_weather_with_llm(prompt_text: str, location: dict = None) -> dict:
    """
    Wrapper that calls resolve_city_context_with_llm() and formats output as a dict.
    This matches the interface of city_resolver.preprocess_prompt_for_weather()

    Returns:
        {
            "original_prompt": str,
            "processed_prompt": str,
            "resolved_city": str or None,
            "metadata": dict
        }
    """
    modified_prompt, resolved_city, metadata = resolve_city_context_with_llm(prompt_text, location or {})

    return {
        "original_prompt": prompt_text,
        "processed_prompt": modified_prompt,
        "resolved_city": resolved_city,
        "metadata": metadata
    }