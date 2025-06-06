# city_resolver.py
# Smart City Resolver Preprocessor for Doppler Tower
# Prevents GPT from hallucinating locations by injecting context before GPT processing

import re
from typing import Dict, Optional, Tuple
from geo_utils_helper import reverse_geolocate

class CityResolver:
    """
    Lightweight preprocessor that resolves location context in user prompts
    before GPT has a chance to hallucinate bizarre locations.
    """
    
    # Keywords that strongly suggest user is asking about their current location
    IMPLICIT_LOCATION_KEYWORDS = [
        "outside", "here", "right now", "currently", "at the moment",
        "do i need", "should i", "will i need", "can i", "is it",
        "tonight", "today", "tomorrow", "this morning", "this afternoon",
        "this evening", "this weekend", "later", "soon", "now"
    ]
    
    # Patterns that suggest user wants weather for their current location
    IMPLICIT_PATTERNS = [
        r"\b(?:what'?s\s+it\s+like|how'?s\s+(?:the\s+)?weather|what'?s\s+(?:the\s+)?weather)\b",
        r"\b(?:do\s+i\s+need|should\s+i\s+(?:bring|wear|take))\b",
        r"\b(?:will\s+it|is\s+it\s+going\s+to|gonna)\s+(?:rain|snow|be\s+(?:hot|cold|sunny|cloudy))\b",
        r"\b(?:how\s+(?:hot|cold|warm|cool)|what'?s\s+the\s+temperature)\b"
    ]
    
    # Explicit city patterns - more comprehensive
    EXPLICIT_CITY_PATTERNS = [
        r"\b(?:in|at|for|near|around)\s+([A-Za-z][\w\s\-,.']+?)(?:\s+(?:today|tomorrow|tonight|now|currently)|\s*[.!?]|$)",
        r"\b([A-Za-z][\w\s\-,.']{2,})\s+weather\b",
        r"\bweather\s+in\s+([A-Za-z][\w\s\-,.']+)",
        r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*),?\s+(?:[A-Z]{2}|[A-Za-z]+)\b"  # City, State/Country
    ]
    
    @classmethod
    def extract_explicit_city(cls, prompt: str) -> Optional[str]:
        """
        Extract explicitly mentioned city from prompt using multiple patterns.
        Returns normalized city name or None.
        """
        prompt_clean = prompt.strip().lower()
        
        for pattern in cls.EXPLICIT_CITY_PATTERNS:
            matches = re.finditer(pattern, prompt, re.IGNORECASE)
            for match in matches:
                city_raw = match.group(1).strip()
                
                # Clean up the extracted city
                city_clean = re.sub(r'[^\w\s\-,.]', '', city_raw).strip()
                
                # Filter out obvious non-cities
                if cls._is_likely_city(city_clean):
                    return cls._normalize_city_name(city_clean)
        
        return None
    
    @classmethod
    def _is_likely_city(cls, text: str) -> bool:
        """Check if extracted text is likely a city name."""
        if not text or len(text) < 2:
            return False
        
        # Filter out common false positives
        false_positives = {
            'weather', 'today', 'tomorrow', 'tonight', 'morning', 'afternoon',
            'evening', 'hot', 'cold', 'warm', 'cool', 'sunny', 'cloudy', 'rainy',
            'need', 'bring', 'wear', 'take', 'like', 'outside', 'inside',
            'going', 'gonna', 'will', 'should', 'can', 'might', 'could'
        }
        
        text_lower = text.lower().strip()
        return text_lower not in false_positives and len(text.split()) <= 4
    
    @classmethod
    def _normalize_city_name(cls, city: str) -> str:
        """Normalize city name for consistent formatting."""
        return " ".join(word.capitalize() for word in city.strip().split())
    
    @classmethod
    def has_implicit_location_context(cls, prompt: str) -> bool:
        """
        Check if prompt has keywords/patterns suggesting user wants local weather.
        """
        prompt_lower = prompt.lower()
        
        # Check for explicit keywords
        for keyword in cls.IMPLICIT_LOCATION_KEYWORDS:
            if keyword in prompt_lower:
                return True
        
        # Check for implicit patterns
        for pattern in cls.IMPLICIT_PATTERNS:
            if re.search(pattern, prompt_lower):
                return True
        
        return False
    
    @classmethod
    def inject_location_context(cls, prompt: str, location_name: str) -> str:
        """
        Intelligently inject location context into prompt at the most natural position.
        """
        if not location_name:
            return prompt
        
        prompt_lower = prompt.lower().strip()
        
        # Pattern-based injection strategies
        injection_strategies = [
            # "What's the weather?" → "What's the weather in Paris?"
            (r"(what'?s\s+(?:the\s+)?weather)(\s*[.!?]?$)", rf"\1 in {location_name}\2"),
            
            # "How's it outside?" → "How's it outside in Paris?"
            (r"(how'?s\s+it\s+outside)(\s*[.!?]?$)", rf"\1 in {location_name}\2"),
            
            # "Do I need a coat?" → "Do I need a coat in Paris?"
            (r"(do\s+i\s+need\s+.+?)(\s*[.!?]?$)", rf"\1 in {location_name}\2"),
            
            # "Will it rain tonight?" → "Will it rain tonight in Paris?"
            (r"(will\s+it\s+(?:rain|snow|be\s+\w+)\s+(?:tonight|today|tomorrow))(\s*[.!?]?$)", rf"\1 in {location_name}\2"),
            
            # "Is it hot?" → "Is it hot in Paris?"
            (r"(is\s+it\s+(?:hot|cold|warm|cool|sunny|cloudy|rainy))(\s*[.!?]?$)", rf"\1 in {location_name}\2"),
        ]
        
        # Try each injection strategy
        for pattern, replacement in injection_strategies:
            new_prompt = re.sub(pattern, replacement, prompt, flags=re.IGNORECASE)
            if new_prompt != prompt:
                return new_prompt
        
        # Fallback: append location at the end
        if prompt.endswith(('?', '.', '!')):
            return f"{prompt[:-1]} in {location_name}{prompt[-1]}"
        else:
            return f"{prompt} in {location_name}"

def resolve_city_context(prompt_text: str, location: Optional[Dict] = None) -> Tuple[str, Optional[str], Dict]:
    """
    Main City Resolver function.
    
    Args:
        prompt_text: Raw user prompt
        location: Frontend geolocation data with 'lat', 'lon', 'name', etc.
    
    Returns:
        Tuple of:
        - Modified prompt with location context
        - Resolved city name
        - Metadata about the resolution process
    """
    metadata = {
        "original_prompt": prompt_text,
        "has_explicit_city": False,
        "has_implicit_context": False,
        "resolution_method": None,
        "injected_location": False
    }
    
    # Step 1: Check for explicit city in prompt
    explicit_city = CityResolver.extract_explicit_city(prompt_text)
    if explicit_city:
        metadata["has_explicit_city"] = True
        metadata["resolution_method"] = "explicit_extraction"
        return prompt_text, explicit_city, metadata
    
    # Step 2: Check if prompt has implicit location context
    has_implicit = CityResolver.has_implicit_location_context(prompt_text)
    metadata["has_implicit_context"] = has_implicit
    
    if not has_implicit:
        # No location context detected - return as-is
        metadata["resolution_method"] = "no_context_detected"
        return prompt_text, None, metadata
    
    # Step 3: Try to resolve location from frontend data
    resolved_location = None
    
    if location:
        # Try using the provided location name
        if location.get("name"):
            resolved_location = location["name"]
            metadata["resolution_method"] = "frontend_location_name"
        
        # Fallback to reverse geocoding if needed
        elif location.get("lat") and location.get("lon"):
            try:
                resolved_location = reverse_geolocate(location["lat"], location["lon"])
                metadata["resolution_method"] = "reverse_geocoding"
            except Exception as e:
                print(f"⚠️ Reverse geocoding failed: {e}")
    
    # Step 4: Inject location context if we have a location
    if resolved_location:
        modified_prompt = CityResolver.inject_location_context(prompt_text, resolved_location)
        metadata["injected_location"] = True
        metadata["injected_location_name"] = resolved_location
        return modified_prompt, resolved_location, metadata
    
    # Step 5: No location available - return original prompt
    metadata["resolution_method"] = "no_location_available"
    return prompt_text, None, metadata

# Convenience functions for integration
def preprocess_prompt_for_weather(prompt_text: str, location: Optional[Dict] = None) -> Dict:
    """
    High-level preprocessor function that returns all the data needed
    for weather processing.
    """
    modified_prompt, resolved_city, metadata = resolve_city_context(prompt_text, location)
    
    return {
        "original_prompt": prompt_text,
        "processed_prompt": modified_prompt,
        "resolved_city": resolved_city,
        "metadata": metadata,
        "should_use_resolved_city": resolved_city is not None
    }

# Test cases for validation
def test_city_resolver():
    """Test the City Resolver with various scenarios."""
    test_cases = [
        # Explicit city cases
        ("What's the weather in Paris?", None, "Paris"),
        ("How's it looking in New York today?", None, "New York"),
        ("Weather for London tomorrow", None, "London"),
        
        # Implicit location cases  
        ("Do I need a coat?", {"name": "Berlin"}, "Berlin"),
        ("Will it rain tonight?", {"name": "Tokyo"}, "Tokyo"),
        ("What's it like outside?", {"name": "Sydney"}, "Sydney"),
        ("Is it hot right now?", {"name": "Miami"}, "Miami"),
        
        # No location context
        ("Tell me about hurricanes", {"name": "Boston"}, None),
        ("What causes rain?", {"name": "Seattle"}, None),
        
        # Reverse geocoding fallback
        ("Do I need an umbrella?", {"lat": 48.8566, "lon": 2.3522}, "Paris")  # Paris coords
    ]
    
    print("🧪 Testing City Resolver...")
    for prompt, location, expected_city in test_cases:
        result = preprocess_prompt_for_weather(prompt, location)
        resolved = result["resolved_city"]
        
        status = "✅" if (resolved and expected_city and expected_city.lower() in resolved.lower()) or (not resolved and not expected_city) else "❌"
        print(f"{status} '{prompt}' → '{result['processed_prompt']}' (City: {resolved})")
    
    print("🧪 City Resolver tests complete!")

if __name__ == "__main__":
    test_city_resolver()