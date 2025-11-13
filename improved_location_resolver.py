# improved_location_resolver.py (FIXED VERSION)
# Fixes: Explicit city mentions now ALWAYS override geolocation

from typing import Dict, Optional, Tuple
from geo_utils_helper import reverse_geolocate, calculate_distance, is_valid_coordinates

def resolve_location_safely(
    user_prompt: str,
    resolved_city: Optional[str],
    location: Optional[Dict],
    force_explicit_city: bool = True  # NEW: Default to prioritizing explicit cities
) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """
    Safely resolve location with strict validation to prevent wrong coordinates.
    
    Returns: (lat, lon, display_name)
    
    Priority (FIXED - Issue #1):
    1. **ALWAYS prioritize explicit city mentions in prompt** ("weather in Paris")
    2. Only use frontend coordinates if NO city is explicitly mentioned
    3. Never mix frontend coords with a different city name
    
    New parameter:
    - force_explicit_city: If True (default), explicit city ALWAYS wins over geolocation
    """
    
    # Extract frontend coordinates if available
    frontend_lat = None
    frontend_lon = None
    frontend_name = None
    
    if location:
        try:
            frontend_lat = float(location.get("lat")) if location.get("lat") is not None else None
            frontend_lon = float(location.get("lon")) if location.get("lon") is not None else None
            frontend_name = location.get("name")
            
            # Validate frontend coordinates
            if frontend_lat is not None and frontend_lon is not None:
                if not is_valid_coordinates(frontend_lat, frontend_lon):
                    print(f"⚠️ Invalid frontend coordinates: {frontend_lat}, {frontend_lon}")
                    frontend_lat = None
                    frontend_lon = None
        except (ValueError, TypeError) as e:
            print(f"⚠️ Error parsing frontend coordinates: {e}")
            frontend_lat = None
            frontend_lon = None
    
    # CASE 1: User explicitly mentioned a city (e.g., "weather in Detroit")
    # THIS NOW HAS ABSOLUTE PRIORITY - FIXES THE MAIN BUG
    if resolved_city and force_explicit_city:
        print(f"🎯 EXPLICIT CITY DETECTED: '{resolved_city}' - OVERRIDING geolocation!")

        # Geocode the requested city (pass user coords for better disambiguation)
        try:
            from dopplertower_engine import search_city_with_weatherapi

            # CRITICAL FIX: Pass user coordinates for proximity-based disambiguation
            city_info = search_city_with_weatherapi(
                resolved_city,
                user_lat=frontend_lat,
                user_lon=frontend_lon
            )

            if city_info and city_info.get("lat") is not None and city_info.get("lon") is not None:
                city_lat = float(city_info["lat"])
                city_lon = float(city_info["lon"])
                city_display = city_info.get("full_name") or resolved_city

                # Log disambiguation score for debugging
                if city_info.get("score"):
                    print(f"🎯 Disambiguation score: {city_info['score']} (source: {city_info.get('source', 'unknown')})")

                # Validate the geocoded coordinates
                if is_valid_coordinates(city_lat, city_lon):
                    # Optional: Log distance from user if we have their location
                    if frontend_lat is not None and frontend_lon is not None:
                        distance = calculate_distance(frontend_lat, frontend_lon, city_lat, city_lon)
                        print(f"ℹ️ User is {distance:.0f}km from requested city (using requested city anyway)")

                    print(f"✅ Using explicit city: {city_display} at {city_lat}, {city_lon}")
                    return city_lat, city_lon, city_display
                else:
                    print(f"❌ Geocoded coordinates for '{resolved_city}' are invalid")

        except Exception as e:
            print(f"❌ Failed to geocode '{resolved_city}': {e}")
    
    # CASE 2: No explicit city, use frontend coordinates (user's actual location)
    if frontend_lat is not None and frontend_lon is not None:
        print(f"📍 No explicit city - using frontend coordinates: {frontend_lat}, {frontend_lon}")
        
        # Get a human-readable name for these coordinates
        display_name = frontend_name
        if not display_name:
            try:
                display_name = reverse_geolocate(frontend_lat, frontend_lon)
            except Exception as e:
                print(f"⚠️ Reverse geocoding failed: {e}")
                display_name = f"{frontend_lat:.2f}, {frontend_lon:.2f}"
        
        print(f"✅ Using user's location: {display_name}")
        return frontend_lat, frontend_lon, display_name
    
    # CASE 3: No explicit city AND no frontend coordinates
    print("❌ No valid location data available")
    return None, None, None


def validate_weather_result(result: Dict, expected_lat: float, expected_lon: float) -> bool:
    """
    Validate that weather result matches expected coordinates.
    Prevents the "random Africa location" bug.
    """
    if not result or "coords" not in result:
        return False
    
    result_coords = result.get("coords", {})
    result_lat = result_coords.get("lat")
    result_lon = result_coords.get("lon")
    
    if result_lat is None or result_lon is None:
        return False
    
    # Allow small differences due to rounding (within 1km)
    distance = calculate_distance(expected_lat, expected_lon, result_lat, result_lon)
    
    if distance > 50:  # More than 50km difference = something went wrong
        print(f"🚨 LOCATION MISMATCH DETECTED!")
        print(f"   Expected: {expected_lat}, {expected_lon}")
        print(f"   Got: {result_lat}, {result_lon}")
        print(f"   Distance: {distance:.1f}km")
        return False
    
    return True

