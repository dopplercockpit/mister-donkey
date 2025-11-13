#!/usr/bin/env python3
"""
Test script to verify the city search fix
Tests that search_city_with_weatherapi properly disambiguates cities
"""

import os
import sys

# Set up environment
from dopplertower_engine import search_city_with_weatherapi

def test_city_search(city_name, user_lat=None, user_lon=None):
    """Test searching for a city and print results"""
    print(f"\n{'='*60}")
    print(f"Testing: '{city_name}'")
    if user_lat and user_lon:
        print(f"User location: {user_lat}, {user_lon}")
    print(f"{'='*60}")

    result = search_city_with_weatherapi(city_name, user_lat=user_lat, user_lon=user_lon)

    if result:
        print(f"✅ Found: {result['full_name']}")
        print(f"   Coordinates: {result['lat']}, {result['lon']}")
        print(f"   Score: {result.get('score', 'N/A')}")
        print(f"   Source: {result.get('source', 'N/A')}")
    else:
        print(f"❌ No results found for '{city_name}'")

    return result


def main():
    print("🧪 Testing City Search Fix")
    print("=" * 60)
    print("Testing that the disambiguator properly prioritizes cities")
    print("instead of blindly returning first US/CA result\n")

    # Test 1: Paris (should return Paris, France without user location)
    test_city_search("Paris")

    # Test 2: Paris with US user location (should still return Paris, France due to exact match bonus)
    test_city_search("Paris", user_lat=40.7128, user_lon=-74.0060)  # NYC

    # Test 3: London (should return London, UK)
    test_city_search("London")

    # Test 4: Springfield (ambiguous US city - should pick one with good score)
    test_city_search("Springfield")

    # Test 5: Windsor with Canadian user location (should prefer Windsor, ON)
    test_city_search("Windsor", user_lat=43.6532, user_lon=-79.3832)  # Toronto

    # Test 6: Tokyo (unambiguous)
    test_city_search("Tokyo")

    # Test 7: Portland with US West Coast user (should prefer Portland, OR)
    test_city_search("Portland", user_lat=47.6062, user_lon=-122.3321)  # Seattle

    # Test 8: Melbourne with Australian user (should prefer Melbourne, AU)
    test_city_search("Melbourne", user_lat=-33.8688, user_lon=151.2093)  # Sydney

    print("\n" + "=" * 60)
    print("✅ Testing complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
