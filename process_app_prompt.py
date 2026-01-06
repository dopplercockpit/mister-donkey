# process_app_prompt.py (UPDATED VERSION)
# Fixes: Supports tone selection and conversation history
# NEW: Uses LLM router for intelligent location resolution

import re
from dopplertower_engine import get_full_weather_summary, get_full_weather_summary_by_coords
from geo_utils_helper import get_geolocation, reverse_geolocate
from nlpprepro import preprocess_with_gpt
from agent_dkmanager import check_and_create_agent
from city_resolver import resolve_city_context, preprocess_prompt_for_weather
from llm_router import preprocess_prompt_for_weather_with_llm  # NEW: LLM-based router
from improved_location_resolver import resolve_location_safely, validate_weather_result

def normalize_city_name(city: str) -> str:
    return " ".join(w.capitalize() for w in city.strip().split())

def process_prompt_from_app(
    prompt_text: str, 
    location: dict | None = None,
    tone: str = "sarcastic",  # NEW
    conversation_history: list = None  # NEW
) -> dict:
    """
    Enhanced prompt processor with tone selection and conversation continuity.
    
    NEW Parameters:
    - tone: Personality tone for the response (sarcastic, pirate, professional, etc.)
    - conversation_history: Previous messages in the conversation
    """
    print(f"🚀 Processing prompt: '{prompt_text}'")
    print(f"📍 Location data: {location}")
    print(f"🎭 Tone: {tone}")
    if conversation_history:
        print(f"💬 Conversation history: {len(conversation_history)} messages")

    # STEP 0: LLM Router Preprocessing (NEW: Uses intelligent semantic routing)
    resolver_result = preprocess_prompt_for_weather_with_llm(prompt_text, location)
    
    processed_prompt = resolver_result["processed_prompt"]
    resolved_city_from_resolver = resolver_result["resolved_city"]
    resolver_metadata = resolver_result["metadata"]
    
    print(f"🎯 LLM Router Results:")
    print(f"   Original: '{resolver_result['original_prompt']}'")
    print(f"   Processed: '{processed_prompt}'")
    print(f"   Resolved City: {resolved_city_from_resolver}")
    print(f"   Method: {resolver_metadata.get('resolution_method')}")
    print(f"   Is Explicit: {resolver_metadata.get('is_location_explicit')}")
    
    # STEP 1: NLP Preprocessing with GPT
    parsed = preprocess_with_gpt(processed_prompt)
    print("🤖 GPT preprocessor returned:", parsed)

    # STEP 2: Safely resolve location (explicit cities always take priority over geolocation)
    final_lat, final_lon, display_name = resolve_location_safely(
        user_prompt=prompt_text,
        resolved_city=resolved_city_from_resolver,
        location=location
    )
    
    # If we couldn't resolve location, return error
    if final_lat is None or final_lon is None:
        return {
            "error": "Could not determine location. Please provide a city name or enable location services.",
            "debug_info": {
                "resolver_result": resolver_result,
                "gpt_parsed": parsed,
                "location_input": location
            }
        }
    
    print(f"🌍 Final resolved location: {display_name} at {final_lat}, {final_lon}")
    
    # STEP 3: Get weather using coordinates with tone and conversation history
    result = get_full_weather_summary_by_coords(
        final_lat, 
        final_lon, 
        display_name=display_name, 
        user_prompt=processed_prompt, 
        timezone_offset=0,
        tone=tone,  # NEW: Pass tone through
        conversation_history=conversation_history  # NEW: Pass conversation through
    )
    
    # STEP 4: Validate result matches expected location
    if not validate_weather_result(result, final_lat, final_lon):
        print("🚨 Weather result validation FAILED - coordinates don't match!")
        result["warning"] = "Location validation failed. Result may be inaccurate."
    
    # Add debugging information
    result["parsed_prompt"] = parsed
    result["original_prompt"] = prompt_text
    result["processed_prompt"] = processed_prompt
    result["city_resolver_debug"] = resolver_result
    result["tone_used"] = tone
    
    # Comprehensive diagnostics
    result["diagnostics"] = {
        "original_prompt": prompt_text,
        "processed_prompt": processed_prompt,
        "resolved_city_string": resolved_city_from_resolver,
        "final_coords": {"lat": final_lat, "lon": final_lon},
        "display_name": display_name,
        "llm_router": resolver_result,  # Changed from city_resolver to llm_router
        "validation_passed": validate_weather_result(result, final_lat, final_lon),
        "location_source": "explicit_city" if resolved_city_from_resolver else "user_location",
        "tone": tone,
        "has_conversation_history": conversation_history is not None
    }
    
    # Agent creation (existing logic)
    agent_msg = check_and_create_agent(parsed, location, user_id="anon123")
    if agent_msg:
        print(agent_msg)

    return result