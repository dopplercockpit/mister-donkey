# geo_utils_helper.py
# Geolocation utility functions helper for Doppler Tower
# Utility functions for geolocation via OpenCage

import os
import requests

GEOLOCATION_API_KEY = os.getenv("GEOLOCATION_API_KEY")

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
    """
    url = f"https://api.opencagedata.com/geocode/v1/json?q={lat}+{lon}&key={GEOLOCATION_API_KEY}"
    resp = requests.get(url)
    if resp.status_code != 200:
        print(f"Reverse Geolocation Error: {resp.status_code}: {resp.text}")
        return None

    data = resp.json()
    if data.get("results"):
        return data["results"][0].get("formatted")

    return None
