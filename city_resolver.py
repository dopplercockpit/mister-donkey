# city_resolver.py
# Smart City Resolver Preprocessor for Doppler Tower
# Prevents GPT from hallucinating locations by injecting context before GPT processing

import re
from typing import Dict, Optional, Tuple
from geo_utils_helper import reverse_geolocate

def resolve_city_context(prompt_text: str, location: Optional[Dict] = None) -> Tuple[str, Optional[str], Dict]:
    """
    Main City Resolver function.

    Args:
        prompt_text: Raw user prompt (e.g., "What's the weather in Tokyo?" or "Tell me what's outside")
        location:    Frontend geolocation data, may include:
                     { "lat": 12.34, "lon": 56.78 } or { "name": "Lyon, France", "lat": 45.76, "lon": 4.83 }

    Returns:
        Tuple[
            modified_prompt: str            # Prompt with "in CITY" stripped out, OR unmodified if none found
            resolved_city:   Optional[str]  # e.g. "Paris" if we extracted it, otherwise None
            metadata:        Dict           # info like { original_prompt: "...", resolution_method: "regex", ... }
        ]
    """
    metadata = {
        "original_prompt": prompt_text,
        "resolution_method": None,
        "injected_location": False,
        "injected_location_name": None,
        "resolved_city": None
    }

    text = prompt_text.strip()
    resolved_city: Optional[str] = None
    modified_prompt: str = text  # By default, we’ll return the prompt unchanged

    # 1) If the frontend already gave us a "name" (e.g. user clicked "Yep, that's right" on Lyon), use that:
    if location is not None and isinstance(location, dict) and location.get("name"):
        resolved_city = location["name"]
        metadata["resolution_method"] = "frontend_location_name"
        # We don't strip out any text from prompt_text because the user didn't type "in Paris"; 
        # they just clicked "Yes, that's right." We let the main engine handle it from here.
        metadata["resolved_city"] = resolved_city
        return modified_prompt, resolved_city, metadata

    # 2) Look for an explicit “in <city>” phrase in the user's prompt.
    #    We only match patterns like "in Tokyo", "in New York", "in Paris.", etc.
    #
    #    Explanation of the regex:
    #      - r"\b in\s+([A-Za-zÀ-ÖØ-öø-ÿ'’\- ]+?)(?:[?!.,]|$)"
    #        • \b in\s+  → matches a word boundary, then "in " (with at least one space)
    #        • ([A-Za-zÀ-ÖØ-öø-ÿ'’\- ]+?) → a non‐greedy capture group of letters (including accented), spaces,
    #                                    apostrophes, hyphens (e.g. "New-York", "Québec").
    #        • (?:[?!.,]|$) → lookahead for punctuation or end‐of‐string so we only grab the actual city,
    #                        not trailing words like "in London now please".
    #
    #    We ignore “in here” or “in outside” by checking common filler words after “in”.
    explicit_pattern = re.compile(r"\b in\s+([A-Za-zÀ-ÖØ-öø-ÿ'’\- ]+?)(?=[?!.;,]|$)", flags=re.IGNORECASE)

    match = explicit_pattern.search(text)
    if match:
        candidate = match.group(1).strip()  # e.g. "Paris" or "New York"
        # Convert to Title Case for consistency (“new york” → “New York”)
        candidate_title = candidate.title()

        # Ignore obviously non‐city filler words: “here”, “outside”, “it”, “this”, etc.
        filler_tokens = {"here", "outside", "it", "this", "that", "now", "today", "tomorrow"}
        if candidate_title.lower() not in filler_tokens:
            resolved_city = candidate_title
            metadata["resolution_method"] = "explicit_regex"
            metadata["resolved_city"] = resolved_city

            # Remove the “in {city}” from the prompt, so GPT doesn’t see “What’s the weather in Paris in Paris?”
            start, end = match.span()
            # e.g. text = "What's the weather in Paris?" → modified_prompt = "What's the weather?"
            modified_prompt = (text[:start] + text[end:]).strip()
            # If removing left behind double spaces, collapse them:
            modified_prompt = re.sub(r"\s{2,}", " ", modified_prompt).strip()

            return modified_prompt, resolved_city, metadata
        # else: it was “in here” or “in outside”—we’ll ignore it and fall through

    # 3) Check for implicit keywords that mean "my current location"; e.g., “outside”, “around here”
    #    Only do this if we haven’t already found an explicit city above.
    implicit_keywords = {"outside", "around here", "here", "nearby"}
    lower_text = text.lower()
    for key in implicit_keywords:
        if key in lower_text:
            # The user is asking about their own environment, so we’ll wait for the routes-layer
            # to do a reverse_geolocate(lat, lon) if lat/lon came from the front-end.
            metadata["resolution_method"] = "implicit_keyword"
            metadata["resolved_city"] = None
            return modified_prompt, None, metadata

    # 4) If the front-end provided lat/lon but we didn’t get a resolved_city above, 
    #    let the caller (in routes.py) do a reverse_geocode. 
    #    We don’t do it here, because we only want to return a string city if we’re 100% sure.
    metadata["resolution_method"] = "none"
    metadata["resolved_city"] = None
    return modified_prompt, None, metadata


# -------------- TEST HARNESS (runs if you do “python city_resolver.py”) ----------------
def test_city_resolver():
    test_cases = [
        # prompt                           , location object , expected_city
        ("What's the weather in Paris?",   {},                "Paris"),
        ("tell me what's happening in tokyo.", None,           "Tokyo"),
        ("Can you give me rain chances in New York?", None,      "New York"),
        ("How's it outside?",              {"lat": 48.85, "lon": 2.35}, None),  # should fall back to reverse geocode by lat/lon
        ("Do I need an umbrella?",          None,             None),  # no "in X"
        ("Please tell what it's like outside", {"lat": 32.2, "lon": 35.21}, None),
        ("Is it snowing here?",             {"lat": 45.76, "lon": 4.83}, None),
        ("Hey, weather in Québec?",         None,             "Québec"),
        ("Tell me rain in Rio-de-Janeiro!", None,             "Rio-De-Janeiro"),
    ]

    print("🧪 Testing City Resolver...")
    for prompt, location, expected_city in test_cases:
        processed_prompt, resolved, meta = resolve_city_context(prompt, location or {})
        status = "✅" if ((resolved and expected_city and resolved.lower() == expected_city.lower())
                         or (not resolved and not expected_city)) else "❌"
        print(f"{status} '{prompt}' → processed: '{processed_prompt}' | Resolved City: {resolved} | Method: {meta['resolution_method']}")
    print("🧪 City Resolver tests complete!")

if __name__ == "__main__":
    test_city_resolver()
