# Purpose: turn GPS into “City, Region, Country”. Uses WeatherAPI as a robust fallback.
# REV_geo_utils_helper.py
# Geolocation utility functions helper for Doppler Tower
# Utility functions for geolocation via OpenCage

import os
import requests
import math

GEOLOCATION_API_KEY = os.getenv("GEOLOCATION_API_KEY")
WEATHERAPI_KEY = os.getenv("WEATHERAPI_KEY")
WEATHERAPI_URL = "http://api.weatherapi.com/v1"

def is_valid_coordinates(lat, lon):
    """Validate that coordinates are reasonable"""
    try:
        lat_f = float(lat)
        lon_f = float(lon)
        return -90 <= lat_f <= 90 and -180 <= lon_f <= 180
    except (ValueError, TypeError):
        return False

def calculate_distance(lat1, lon1, lat2, lon2):
    """Calculate distance between two coordinates in km"""
    try:
        lat1, lon1, lat2, lon2 = map(math.radians, [float(lat1), float(lon1), float(lat2), float(lon2)])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a))
        return c * 6371  # Earth's radius in km
    except:
        return float('inf')

def get_geolocation(city_name):
    """
    Given a city name, return (lat, lon, full name)
    """
    url = f"https://api.opencagedata.com/geocode/v1/json?q={city_name}&key={GEOLOCATION_API_KEY}"
    resp = requests.get(url)
    if resp.status_code != 200:
        print(f"Geolocation Error: {resp.status_code}: {resp.text}")
        return None, None, None

    data = resp.json()
    if data.get("results"):
        loc = data["results"][0]
        lat = loc["geometry"]["lat"]
        lon = loc["geometry"]["lng"]
        full_name = loc.get("formatted", city_name)
        return lat, lon, full_name

    return None, None, None

def reverse_geolocate(lat, lon):
    """
    Given lat/lon, return the city + country (or formatted string)
    Enhanced with validation and fallback protection
    """
    # Validate input coordinates
    if not is_valid_coordinates(lat, lon):
        print(f"❌ Invalid coordinates: {lat}, {lon}")
        return None
    
    original_lat, original_lon = float(lat), float(lon)
    
    # 1) First, try OpenCage (high-precision reverse geocoding)
    try:
        url = f"https://api.opencagedata.com/geocode/v1/json"
        resp = requests.get(url, params={
            "q": f"{lat},{lon}",
            "key": GEOLOCATION_API_KEY,
            "limit": 1,
            "no_annotations": 1  # Faster response
        }, timeout=5)
        
        if resp.status_code == 200:
            data = resp.json().get("results", [])
            if data:
                result = data[0]
                # Validate the result is close to our input coordinates
                returned_lat = result.get("geometry", {}).get("lat")
                returned_lon = result.get("geometry", {}).get("lng")
                
                if (returned_lat is not None and returned_lon is not None and
                    calculate_distance(original_lat, original_lon, returned_lat, returned_lon) < 100):  # Within 100km
                    return result.get("formatted")
                else:
                    print(f"⚠️ OpenCage returned distant result: {returned_lat}, {returned_lon}")
    except Exception as e:
        print(f"⚠️ OpenCage failed: {e}")

    # 2) Fallback to WeatherAPI with validation
    try:
        wa_url = f"{WEATHERAPI_URL}/search.json"
        resp = requests.get(wa_url, params={
            "key": WEATHERAPI_KEY, 
            "q": f"{lat},{lon}"
        }, timeout=5)
        
        if resp.status_code == 200:
            wa_data = resp.json()
            if wa_data and isinstance(wa_data, list) and wa_data:
                match = wa_data[0]
                
                # Validate returned coordinates are close to input
                returned_lat = match.get("lat")
                returned_lon = match.get("lon")
                
                if (returned_lat is not None and returned_lon is not None and
                    calculate_distance(original_lat, original_lon, returned_lat, returned_lon) < 100):
                    return f"{match['name']}, {match['region']}, {match['country']}"
                else:
                    print(f"⚠️ WeatherAPI returned distant result: {returned_lat}, {returned_lon}")
    except Exception as e:
        print(f"⚠️ WeatherAPI reverse failed: {e}")

    # 3) Last resort: Return coordinates as string
    print(f"⚠️ All reverse geocoding failed for {lat}, {lon}")
    return f"Location {lat:.2f}, {lon:.2f}"

def resolve_city_from_latlon(lat, lon):
    """Legacy function - now uses the improved reverse_geolocate"""
    return reverse_geolocate(lat, lon)