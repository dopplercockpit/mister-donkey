# city_disambiguator.py 🧠🌍
# Smart disambiguation of fuzzy/multi-region city names
import requests
import os
from geo_utils_helper import calculate_distance

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
WEATHERAPI_KEY = os.getenv("WEATHERAPI_KEY")

def disambiguate_city(query: str, lat: float = None, lon: float = None, return_all: bool = False) -> dict | None:
    """
    Disambiguates fuzzy city queries like 'London' or 'Windsor' by checking both
    OpenWeather and WeatherAPI, scoring results by proximity and keyword match.
    
    Args:
        query: City name to search for
        lat: User's latitude for proximity scoring
        lon: User's longitude for proximity scoring
        return_all: If True, returns detailed response with all candidates and confidence
        
    Returns:
        If return_all=False: Single best candidate dict (backward compatibility)
        If return_all=True: Detailed dict with best, candidates, and confidence info
    """
    open_results = fetch_openweather_candidates(query)
    weatherapi_results = fetch_weatherapi_candidates(query)

    all_candidates = open_results + weatherapi_results
    if not all_candidates:
        return None

    # Remove duplicates and score candidates
    unique_candidates = deduplicate_candidates(all_candidates)
    scored_candidates = [
        {**candidate, "score": score_candidate(candidate, lat, lon, query)}
        for candidate in unique_candidates
    ]
    
    # Sort by score (highest first)
    scored_candidates.sort(key=lambda x: x["score"], reverse=True)
    
    if not return_all:
        # Backward compatibility - return just the best candidate
        return scored_candidates[0] if scored_candidates else None
    
    # Enhanced response with transparency and confidence
    return build_enhanced_response(scored_candidates, query)

def build_enhanced_response(scored_candidates: list, query: str) -> dict:
    """Build enhanced response with confidence analysis and top candidates."""
    if not scored_candidates:
        return {
            "best": None,
            "candidates": [],
            "confidence": "no_results",
            "ambiguity_warning": f"No results found for '{query}'"
        }
    
    best = scored_candidates[0]
    top_3 = scored_candidates[:3]
    
    # Calculate confidence metrics
    confidence_info = calculate_confidence(scored_candidates, query)
    
    return {
        "best": best,
        "candidates": top_3,
        "total_found": len(scored_candidates),
        "confidence": confidence_info["level"],
        "confidence_score": confidence_info["score"],
        "ambiguity_warning": confidence_info.get("warning"),
        "debug_info": {
            "score_breakdown": explain_top_score(best, query),
            "query": query
        }
    }

def score_candidate(candidate: dict, user_lat: float = None, user_lon: float = None, query: str = "") -> float:
    """
    Score a candidate city based on various factors.
    Higher score = better match.
    """
    score = 0.0
    
    # Base score for having complete data
    if candidate.get("name") and candidate.get("lat") and candidate.get("lon"):
        score += 1.0
    
    # Exact name match bonus
    if candidate.get("name", "").lower() == query.lower():
        score += 3.0
    elif query.lower() in candidate.get("name", "").lower():
        score += 1.5
    
    # Country/region popularity weighting (adaptive, not hardcoded)
    country_weights = {
        "US": 2.0, "CA": 1.8, "GB": 1.8, "FR": 1.6, "DE": 1.4, "AU": 1.2
    }
    country_code = candidate.get("country", "")
    if country_code in country_weights:
        score += country_weights[country_code]
    
    # Major region/state bonus (adaptive scoring)
    region = candidate.get("region", "").lower()
    major_regions = [
        "california", "texas", "new york", "florida", "ontario", "quebec",
        "england", "scotland", "île-de-france", "bavaria", "catalonia"
    ]
    if any(major in region for major in major_regions):
        score += 1.0
    
    # Proximity bonus if user location provided
    if user_lat is not None and user_lon is not None:
        try:
            distance = calculate_distance(user_lat, user_lon, candidate["lat"], candidate["lon"])
            if distance < 50:  # Very close
                score += 4.0
            elif distance < 200:  # Close
                score += 2.5
            elif distance < 500:  # Nearby
                score += 1.5
            elif distance < 1000:  # Same region
                score += 0.5
        except (TypeError, ValueError):
            pass  # Skip proximity if coordinates are invalid
    
    # Source reliability bonus
    if candidate.get("source") == "openweather":
        score += 0.2
    elif candidate.get("source") == "weatherapi":
        score += 0.1
    
    return round(score, 2)

def calculate_confidence(scored_candidates: list, query: str) -> dict:
    """Calculate confidence level and potential warnings."""
    if not scored_candidates:
        return {"level": "no_results", "score": 0.0}
    
    top_score = scored_candidates[0]["score"]
    second_score = scored_candidates[1]["score"] if len(scored_candidates) > 1 else 0
    
    score_gap = top_score - second_score
    total_candidates = len(scored_candidates)
    
    confidence_score = min(top_score / 10.0, 1.0)  # Normalize to 0-1
    
    # Determine confidence level
    if score_gap >= 3.0 and top_score >= 6.0:
        level = "high"
        warning = None
    elif score_gap >= 1.5 or top_score >= 4.0:
        level = "medium"
        warning = None
    else:
        level = "low"
        if total_candidates > 3:
            warning = f"Multiple cities named '{query}' found. Please be more specific or select from the options."
        else:
            warning = f"Uncertain match for '{query}'. Please verify the location."
    
    result = {
        "level": level,
        "score": round(confidence_score, 2)
    }
    
    if warning:
        result["warning"] = warning
    
    return result

def explain_top_score(candidate: dict, query: str) -> dict:
    """Explain how the top candidate got its score for debugging."""
    if not candidate:
        return {}
    
    explanations = []
    score = candidate.get("score", 0)
    
    if candidate.get("name", "").lower() == query.lower():
        explanations.append("Exact name match (+3.0)")
    elif query.lower() in candidate.get("name", "").lower():
        explanations.append("Partial name match (+1.5)")
    
    country = candidate.get("country", "")
    if country in ["US", "CA", "GB", "FR", "DE", "AU"]:
        explanations.append(f"Major country {country} (+bonus)")
    
    return {
        "total_score": score,
        "factors": explanations,
        "location": f"{candidate.get('name', '')}, {candidate.get('region', '')}, {candidate.get('country', '')}"
    }

def deduplicate_candidates(candidates: list) -> list:
    """Remove duplicate candidates based on name + coordinates."""
    seen = set()
    unique = []
    
    for candidate in candidates:
        # Create a key based on name and approximate coordinates
        name = candidate.get("name", "").lower()
        lat = round(candidate.get("lat", 0), 2) if candidate.get("lat") else 0
        lon = round(candidate.get("lon", 0), 2) if candidate.get("lon") else 0
        key = f"{name}_{lat}_{lon}"
        
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    
    return unique

# Original functions preserved for backward compatibility
def fetch_openweather_candidates(query):
    try:
        url = f"http://api.openweathermap.org/geo/1.0/direct?q={query}&limit=5&appid={OPENWEATHER_API_KEY}"
        r = requests.get(url, timeout=5)
        r.raise_for_status()
        return [
            {
                "name": c.get("name"),
                "region": c.get("state", ""),
                "country": c.get("country", ""),
                "lat": c.get("lat"),
                "lon": c.get("lon"),
                "source": "openweather"
            }
            for c in r.json()
        ]
    except Exception as e:
        print(f"🌩️ OpenWeather error: {e}")
        return []

def fetch_weatherapi_candidates(query):
    try:
        url = f"http://api.weatherapi.com/v1/search.json?key={WEATHERAPI_KEY}&q={query}"
        r = requests.get(url, timeout=5)
        r.raise_for_status()
        return [
            {
                "name": c.get("name"),
                "region": c.get("region", ""),
                "country": c.get("country", ""),
                "lat": c.get("lat"),
                "lon": c.get("lon"),
                "source": "weatherapi"
            }
            for c in r.json()
        ]
    except Exception as e:
        print(f"🌦️ WeatherAPI error: {e}")
        return []

# Convenience functions for different use cases
def get_best_city(query: str, lat: float = None, lon: float = None) -> dict | None:
    """Get just the best candidate (backward compatible)."""
    return disambiguate_city(query, lat, lon, return_all=False)

def get_city_options(query: str, lat: float = None, lon: float = None) -> dict:
    """Get all candidates with confidence info for frontend selection."""
    return disambiguate_city(query, lat, lon, return_all=True)

# Example usage for testing
if __name__ == "__main__":
    # Test the enhanced functionality
    print("Testing 'Paris' disambiguation:")
    result = get_city_options("Paris")
    print(f"Best: {result['best']['name']}, {result['best']['region']}")
    print(f"Confidence: {result['confidence']} ({result['confidence_score']})")
    print(f"Total candidates: {result['total_found']}")
    if result.get('ambiguity_warning'):
        print(f"Warning: {result['ambiguity_warning']}")
