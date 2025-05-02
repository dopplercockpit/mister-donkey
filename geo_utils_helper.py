# geo_utils_helper.py
# Geolocation utility functions helper for Doppler Tower
# Utility functions for geolocation via OpenCage

import os
import requests

GEOLOCATION_API_KEY = os.getenv("GEOLOCATION_API_KEY")

WEATHERAPI_KEY = os.getenv("WEATHERAPI_KEY")
WEATHERAPI_URL = "http://api.weatherapi.com/v1"



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

#def reverse_geolocate(lat, lon):
    """
    Given lat/lon, return the city + country (or formatted string)
    """
#    url = f"https://api.opencagedata.com/geocode/v1/json?q={lat}+{lon}&key={GEOLOCATION_API_KEY}"
def reverse_geolocate(lat, lon):
    # 1) First, try WeatherAPI reverse-search (very precise):
    
        # 1) First, try OpenCage (high-precision reverse geocoding)
    url = f"https://api.opencagedata.com/geocode/v1/json"
    resp = requests.get(url, params={
        "q": f"{lat},{lon}",
        "key": GEOLOCATION_API_KEY,
        "limit": 1
    })
    if resp.status_code == 200:
        data = resp.json().get("results", [])
        if data:
            return data[0].get("formatted")

    # 2) Fallback to WeatherAPI if OpenCage fails:
    try:
        wa = requests.get(
            f"{WEATHERAPI_URL}/search.json",
            params={"key": WEATHERAPI_KEY, "q": f"{lat},{lon}"}
        ).json()
        if wa and isinstance(wa, list):
            m = wa[0]
            return f"{m['name']}, {m['region']}, {m['country']}"
    except Exception:
        pass


    # 2) Fallback to OpenCage with comma‑separated coords:
    url = f"https://api.opencagedata.com/geocode/v1/json"
    resp = requests.get(url, params={
        "q": f"{lat},{lon}",
        "key": GEOLOCATION_API_KEY,
        "limit": 1
    })
    if resp.status_code != 200:
        print(f"Reverse Geolocation Error: {resp.status_code}: {resp.text}")
        return None
    data = resp.json().get("results", [])
    return data[0].get("formatted") if data else None


#    resp = requests.get(url)
#    if resp.status_code != 200:
#        print(f"Reverse Geolocation Error: {resp.status_code}: {resp.text}")
#        return None
#
#    data = resp.json()
#    if data.get("results"):
#        return data["results"][0].get("formatted")
#
#    return None


def resolve_city_from_latlon(lat, lon):
    url = f"{WEATHERAPI_URL}/search.json?key={WEATHERAPI_KEY}&q={lat},{lon}"
    response = requests.get(url)
    try:
        results = response.json()
        if results and isinstance(results, list):
            match = results[0]
            return f"{match['name']}, {match['region']}, {match['country']}"
    except Exception as e:
        print(f"⚠️ Failed reverse geolocation: {e}")
    return None
