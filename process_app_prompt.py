# Purpose: normalize the prompt + city, then call the engine.
# Updated process_app_prompt.py with City Resolver integration
import re
from dopplertower_engine import get_full_weather_summary
from geo_utils_helper import get_geolocation, reverse_geolocate
from nlpprepro import preprocess_with_gpt
from agent_dkmanager import check_and_create_agent
from city_resolver import resolve_city_context, preprocess_prompt_for_weather  # NEW IMPORT

def normalize_city_name(city: str) -> str:
    return " ".join(w.capitalize() for w in city.strip().split())

# Commenting out as it may be duplicating effort that exists in CityResolver.
# def extract_city_from_prompt(prompt: str) -> str | None:
#    # capture "in CITY" or "at CITY" or "for CITY"
#    m = re.search(r"(?:in|at|for)\s+([A-Za-z\s]+)", prompt)
#    if m:
#        # strip trailing punctuation
#        return re.sub(r"[^\w\s]", "", m.group(1)).strip()
#    return None

def process_prompt_from_app(prompt_text: str, location: dict | None = None) -> dict:
    """
    Enhanced prompt processor with City Resolver preprocessing.
    Now prevents GPT from hallucinating locations by resolving context first.
    """
    print(f"🚀 Processing prompt: '{prompt_text}'")
    print(f"📍 Location data: {location}")
    
    # STEP 0: City Resolver Preprocessing 
    # This happens BEFORE GPT gets to see the prompt
    resolver_result = preprocess_prompt_for_weather(prompt_text, location)
    
    processed_prompt = resolver_result["processed_prompt"]
    resolved_city_from_resolver = resolver_result["resolved_city"]
    resolver_metadata = resolver_result["metadata"]
    
    print(f"🎯 City Resolver Results:")
    print(f"   Original: '{resolver_result['original_prompt']}'")
    print(f"   Processed: '{processed_prompt}'")
    print(f"   Resolved City: {resolved_city_from_resolver}")
    print(f"   Method: {resolver_metadata.get('resolution_method')}")
    print(f"   Injected Location: {resolver_metadata.get('injected_location')}")
    
    # STEP 1: NLP Preprocessing with GPT (using the preprocessed prompt)
    parsed = preprocess_with_gpt(processed_prompt)
    print("🤖 GPT preprocessor returned:", parsed)

    city_from_gpt = parsed.get("city")
    time_context = parsed.get("time_context")
    intent = parsed.get("intent")

    # STEP 2: City Resolution Priority Logic
    city_query = None
    prompt_metadata = {"resolver_metadata": resolver_metadata}

    # Priority 1: Use City Resolver result if it found something
    if resolved_city_from_resolver:
        city_query = normalize_city_name(resolved_city_from_resolver)
        prompt_metadata["city_source"] = "city_resolver"
        print(f"🎯 Using city from City Resolver: {city_query}")
    
    # Priority 2: Use GPT result only if City Resolver didn't find anything
    elif city_from_gpt:
        city_query = normalize_city_name(city_from_gpt)
        print(f"🧽 Normalized city from GPT: {city_query}")
        prompt_metadata["city_source"] = "gpt_extraction"
        print(f"🤖 Using city from GPT (fallback): {city_query}")
    
    # Priority 3: Legacy regex extraction (further fallback)
    # elif not city_query:
    #    raw = extract_city_from_prompt(processed_prompt)
    #    if raw:
    #        city_query = normalize_city_name(raw)
    #        prompt_metadata["city_source"] = "regex_extraction"
    #        print(f"🔍 Found city via regex: {city_query}")

    # Priority 4: Frontend location fallback (only if nothing else worked)
    if location and not city_query:
        print("🔧 Using fallback location from frontend because previous methods failed")
        city_name = location.get("name")
        if city_name:
            prompt_metadata["city"] = city_name
            prompt_metadata["timezone"] = location.get("tz_id")
            prompt_metadata["lat"] = location.get("lat")
            prompt_metadata["lon"] = location.get("lon")
            prompt_metadata["city_source"] = "fallback_frontend_location"
            city_query = city_name
            print(f"📍 Final fallback city_query from frontend: {city_query}")
        else:
            print("⚠️ Location object present but missing 'name'")

    # Priority 5: Reverse-geocode lat/lon if still no valid city
    if not city_query and location:
        lat, lon = location.get("lat"), location.get("lon")
        if lat is not None and lon is not None:
            city_query = reverse_geolocate(lat, lon)
            prompt_metadata["city_source"] = "reverse_geocoding"
            print(f"🗺️ Using reverse geocoded location: {city_query}")

    # Priority 6: Full geocoding fallback using original prompt
    if not city_query:
        lat, lon, full = get_geolocation(prompt_text)
        if lat and lon:
            city_query = full
            prompt_metadata["city_source"] = "full_geocoding_fallback"
            print(f"🌍 Final geocoding fallback result: {city_query}")

    # Error out if no city found
    if not city_query:
        return {
            "error": "City not found.",
            "debug_info": {
                "resolver_result": resolver_result,
                "gpt_parsed": parsed,
                "metadata": prompt_metadata
            }
        }

    print(f"🌍 Final city_query: {city_query}")
    print(f"📊 City source: {prompt_metadata.get('city_source')}")

    # Agent creation (existing logic)
    agent_msg = check_and_create_agent(parsed, location, user_id="anon123")
    if agent_msg:
        print(agent_msg)

    from city_disambiguator import disambiguate_city  # <== top of file

    # 🔍 Try to disambiguate city before querying
    disambiguated = disambiguate_city(city_query, lat=location.get("lat") if location else None, lon=location.get("lon") if location else None)
    if disambiguated:
        city_query = disambiguated["full_name"] = ", ".join(filter(None, [disambiguated["name"], disambiguated["region"], disambiguated["country"]]))
        print(f"🏆 Disambiguated to: {city_query}")

    # INSERT replacement (keep the old block commented with "# removed" if you prefer)
    final_lat = None
    final_lon = None
    display_name = None

    # 1) If the resolver picked a specific city that's different from device location, geocode it
    if resolved_city_from_resolver:
        try:
            from dopplertower_engine import search_city_with_weatherapi
            info = search_city_with_weatherapi(resolved_city_from_resolver)
            if info and info.get("lat") is not None and info.get("lon") is not None:
                final_lat = info["lat"]
                final_lon = info["lon"]
                display_name = info.get("full_name") or resolved_city_from_resolver
        except Exception as e:
            print(f"⚠️ Geocode of resolver city failed: {e}")

    # 2) Otherwise, use the frontend coordinates if present
    if (final_lat is None or final_lon is None) and location:
        try:
            lat = location.get("lat")
            lon = location.get("lon")
            if lat is not None and lon is not None:
                final_lat = float(lat)
                final_lon = float(lon)
                display_name = location.get("name")
        except Exception as e:
            print(f"⚠️ Frontend coords invalid: {e}")

    # 3) If we still have nothing, fall back to city string
    if final_lat is not None and final_lon is not None:
        from dopplertower_engine import get_full_weather_summary_by_coords
        result = get_full_weather_summary_by_coords(
            final_lat, final_lon, display_name=display_name, user_prompt=processed_prompt, timezone_offset=0
        )
    else:
        # last resort: string-based resolution
        result = get_full_weather_summary(
            city_query if city_query else (location.get("name") if location else None),
            user_prompt=processed_prompt,
            timezone_offset=0
        )

    # Removed the old direct call to get_full_weather_summary(city_query...)  # removed
    
    # Add debugging information to the result
    result["parsed_prompt"] = parsed
    result["prompt_metadata"] = prompt_metadata
    result["city_resolver_debug"] = resolver_result
    result["original_prompt"] = prompt_text
    result["processed_prompt"] = processed_prompt
    
    # ADD a stable diagnostics object that exists for BOTH manual and auto flows
    result["diagnostics"] = {
        "original_prompt": prompt_text,
        "processed_prompt": processed_prompt,
        "chosen_city_string": city_query,
        "final_coords": {"lat": final_lat, "lon": final_lon},
        "display_name": display_name,
        "city_resolver": resolver_result,
        "prompt_metadata": prompt_metadata,
    }


    return result

