# process_app_prompt.py (PATCHED VERSION)
# Fixes: Location accuracy, prevents "random Africa" bug

import re
from dopplertower_engine import get_full_weather_summary, get_full_weather_summary_by_coords
from geo_utils_helper import get_geolocation, reverse_geolocate
from nlpprepro import preprocess_with_gpt
from agent_dkmanager import check_and_create_agent
from city_resolver import resolve_city_context, preprocess_prompt_for_weather
from improved_location_resolver import resolve_location_safely, validate_weather_result

def normalize_city_name(city: str) -> str:
    return " ".join(w.capitalize() for w in city.strip().split())

def process_prompt_from_app(prompt_text: str, location: dict | None = None) -> dict:
    """
    Enhanced prompt processor with strict location validation.
    FIXES: Random Africa coordinates bug.
    """
    print(f"🚀 Processing prompt: '{prompt_text}'")
    print(f"📍 Location data: {location}")
    
    # STEP 0: City Resolver Preprocessing
    resolver_result = preprocess_prompt_for_weather(prompt_text, location)
    
    processed_prompt = resolver_result["processed_prompt"]
    resolved_city_from_resolver = resolver_result["resolved_city"]
    resolver_metadata = resolver_result["metadata"]
    
    print(f"🎯 City Resolver Results:")
    print(f"   Original: '{resolver_result['original_prompt']}'")
    print(f"   Processed: '{processed_prompt}'")
    print(f"   Resolved City: {resolved_city_from_resolver}")
    print(f"   Method: {resolver_metadata.get('resolution_method')}")
    
    # STEP 1: NLP Preprocessing with GPT
    parsed = preprocess_with_gpt(processed_prompt)
    print("🤖 GPT preprocessor returned:", parsed)

    # STEP 2: Safely resolve location (NEW - prevents Africa bug)
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
    
    # STEP 3: Get weather using coordinates (most reliable method)
    result = get_full_weather_summary_by_coords(
        final_lat, 
        final_lon, 
        display_name=display_name, 
        user_prompt=processed_prompt, 
        timezone_offset=0
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
    
    # Comprehensive diagnostics
    result["diagnostics"] = {
        "original_prompt": prompt_text,
        "processed_prompt": processed_prompt,
        "resolved_city_string": resolved_city_from_resolver,
        "final_coords": {"lat": final_lat, "lon": final_lon},
        "display_name": display_name,
        "city_resolver": resolver_result,
        "validation_passed": validate_weather_result(result, final_lat, final_lon),
        "location_source": "explicit_city" if resolved_city_from_resolver else "user_location"
    }
    
    # Agent creation (existing logic)
    agent_msg = check_and_create_agent(parsed, location, user_id="anon123")
    if agent_msg:
        print(agent_msg)

    return result