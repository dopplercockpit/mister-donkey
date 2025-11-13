# improved_location_resolver.py (FIXED VERSION)
# Fixes: Explicit city mentions now ALWAYS override geolocation

from typing import Dict, Optional, Tuple
from geo_utils_helper import reverse_geolocate, calculate_distance, is_valid_coordinates, get_geolocation

# # OLD VERSION (disabled 2025-11-13 by Josh to fix Rouville/Lyon bug)
# def resolve_location_safely(...):
#     ...
#     # old logic
#     ...

def resolve_location_safely(
    user_prompt: str,
    resolved_city: Optional[str],
    location: Optional[Dict],
    force_explicit_city: bool = True
) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    """
    Safely resolve location with strict validation to prevent wrong coordinates.

    Priority:
    1. Explicit city from the prompt      → forward geocode name → (lat, lon, label)
    2. Browser/location coordinates       → trust lat/lon from frontend
    3. Fallback                           → None, force frontend to ask for city
    """
    print("🧭 resolve_location_safely() called")
    print(f"   user_prompt: {user_prompt!r}")
    print(f"   resolved_city (from resolver): {resolved_city!r}")
    print(f"   frontend location dict: {location!r}")

    # 1) Explicit city from prompt
    if force_explicit_city and resolved_city:
        city_name = resolved_city.strip()
        print(f"   🔎 Using explicit city from prompt: {city_name!r}")
        lat, lon, full_name = get_geolocation(city_name)

        if lat is not None and lon is not None and is_valid_coordinates(lat, lon):
            # Label: use the full_name from geocoder if available
            display_name = full_name or city_name
            print(f"   ✅ Explicit city resolved to: ({lat}, {lon}) → {display_name}")
            return lat, lon, display_name
        else:
            print("   ⚠️ Explicit city geocode failed or invalid, falling back to frontend location")

    # 2) Frontend location (browser geolocation)
    if location:
        lat = location.get("lat")
        lon = location.get("lon")

        if is_valid_coordinates(lat, lon):
            # Try to re-use friendly name if frontend provided it (from /geo/reverse)
            display_name = location.get("name")
            if not display_name:
                display_name = reverse_geolocate(lat, lon)

            print(f"   ✅ Using frontend coordinates: ({lat}, {lon}) → {display_name!r}")
            return lat, lon, display_name
        else:
            print(f"   ⚠️ Frontend coordinates invalid: {lat}, {lon}")

    # 3) Fallback: nothing usable
    print("   ❌ No valid location could be resolved (no explicit city, no valid coords)")
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

