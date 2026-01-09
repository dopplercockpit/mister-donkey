# File: /mnt/data/city_resolver.py
# Smart City Resolver + preprocess_prompt_for_weather helper for Doppler Tower / Mister Donkey
# This version ensures we include "original_prompt" in the dict, so process_app_prompt.py's
# lookup of resolver_result["original_prompt"] will succeed.

import re
from typing import Dict, Optional, Tuple
from geo_utils_helper import reverse_geolocate

def _cleanup_dangling_in(text: str) -> str:
    cleaned = re.sub(r"\b in\b\s*(?=[,?!.;]|$)", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+([,?!.;])", r"\1", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()

def resolve_city_context(prompt_text: str, location: Optional[Dict] = None) -> Tuple[str, Optional[str], Dict]:
    """
    Main City Resolver function.

    Args:
        prompt_text: Raw user prompt (e.g., "What's the weather in Tokyo?" or
                     "Tell me what's outside")
        location:    Frontend geolocation data, may include:
                     { "lat": 12.34, "lon": 56.78 } OR
                     { "name": "Lyon, France", "lat": 45.76, "lon": 4.83 }

    Returns:
        Tuple[
            modified_prompt: str,          # Prompt with "in CITY" stripped out (or unmodified)
            resolved_city: Optional[str],  # e.g. "Paris" if extracted, otherwise None
            metadata: Dict                 # debug info, e.g. { original_prompt: "...", resolution_method: "...", ... }
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
    modified_prompt: str = text  # By default, return the prompt unchanged

    # REMOVED: location.name early return so explicit city in prompt always wins.
    # if location is not None and isinstance(location, dict) and location.get("name"):
    #     resolved_city = location["name"]
    #     metadata["resolution_method"] = "frontend_location_name"
    #     metadata["resolved_city"] = resolved_city
    #     return modified_prompt, resolved_city, metadata

    # --------------------------------------------------------------------------
    # 2) Look for an explicit “in <city>” phrase in the user's prompt.
    #
    #    We match patterns like "in Tokyo", "in New York", "in Paris.", etc. and
    #    only grab things that look like letters/spaces/hyphens/accented characters.
    #
    #    Regex Explanation:
    #      - r"\b in\s+([A-Za-zÀ-ÖØ-öø-ÿ'’\- ]+?)(?=[?!.;,]|$)"
    #        • \b in\s+         → matches a word boundary, then "in " (at least one space)
    #        • ([A-Za-zÀ-ÖØ-öø-ÿ'’\- ]+?) → a non‐greedy group capturing letters (including accented),
    #                                       spaces, apostrophes, hyphens. E.g. "New York", "Québec", "Rio-de-Janeiro"
    #        • (?=[?!.;,]|$)     → lookahead for punctuation or end‐of‐string so we don't capture trailing words.
    #
    #    After capturing, we filter out obvious filler words like "here", "outside", etc.
    # --------------------------------------------------------------------------
    explicit_pattern = re.compile(
        r"\b in\s+([A-Za-zÀ-ÖØ-öø-ÿ'’\- ]+?)(?=[?!.;,]|$)",
        flags=re.IGNORECASE
    )
    match = explicit_pattern.search(text)
    if match:
        candidate = match.group(1).strip()          # e.g. "Paris" or "New York"
        candidate = re.split(r"\s+in\s+", candidate, maxsplit=1, flags=re.IGNORECASE)[0].strip()
        candidate_title = candidate.title()         # Normalize to Title Case ("new york" → "New York")

        # Reject filler tokens like "here", "outside", etc.
        filler_tokens = {"here", "outside", "it", "this", "that", "now", "today", "tomorrow"}
        if candidate_title.lower() not in filler_tokens:
            resolved_city = candidate_title
            metadata["resolution_method"] = "explicit_regex"
            metadata["resolved_city"] = resolved_city

            # Remove "in {city}" from the prompt so GPT won’t see "weather in Paris in Paris"
            start, end = match.span()
            modified_prompt = (text[:start] + text[end:]).strip()
            # Collapse any accidental double spaces left behind
            modified_prompt = re.sub(r"\s{2,}", " ", modified_prompt).strip()
            modified_prompt = _cleanup_dangling_in(modified_prompt)

            return modified_prompt, resolved_city, metadata
        # else: it was "in here" or "in outside" → ignore, fall through

    # --------------------------------------------------------------------------
    # 3) Check for implicit keywords meaning "use my current location", e.g. “outside”, “around here”
    #    If found, we do NOT set a city here. Let routes.py call reverse_geolocate(lat, lon) later.
    # --------------------------------------------------------------------------
    implicit_keywords = {"outside", "around here", "here", "nearby"}
    lower_text = text.lower()
    for key in implicit_keywords:
        if key in lower_text:
            metadata["resolution_method"] = "implicit_keyword"
            metadata["resolved_city"] = None
            modified_prompt = _cleanup_dangling_in(modified_prompt)
            return modified_prompt, None, metadata

    # --------------------------------------------------------------------------
    # 4) No explicit "in X" and no implicit keyword, but frontend gave us a name.
    #    Use that as a *fallback* label (e.g. "Lyon, France").
    # --------------------------------------------------------------------------

    if location is not None and isinstance(location, dict) and location.get("name"):
        resolved_city = location["name"]
        metadata["resolution_method"] = "frontend_location_name"
        metadata["resolved_city"] = resolved_city
        modified_prompt = _cleanup_dangling_in(modified_prompt)
        return modified_prompt, resolved_city, metadata

    # --------------------------------------------------------------------------
    # 5) Absolute fallback: no city at all. Caller can rely on lat/lon and
    #    reverse_geolocate() later.
    # --------------------------------------------------------------------------
    metadata["resolution_method"] = "none"
    metadata["resolved_city"] = None
    modified_prompt = _cleanup_dangling_in(modified_prompt)
    return modified_prompt, None, metadata

# ------------------------------------------------------------------------------
# Re-create preprocess_prompt_for_weather so process_app_prompt.py finds all keys it expects.
# In particular, process_app_prompt.py does things like:
#     resolver_result["original_prompt"]
#     resolver_result["processed_prompt"]
#     resolver_result["resolved_city"]
#     resolver_result["metadata"][...]
#
# So we include "original_prompt" here. If you need "should_use_resolved_city" or other flags,
# you can add them too, but at minimum we must have "original_prompt" so that there is no KeyError.
# ------------------------------------------------------------------------------
def preprocess_prompt_for_weather(prompt_text: str, location: Optional[Dict] = None) -> Dict:
    """
    Wrapper that calls resolve_city_context() and formats its output as a dict:
      {
        "original_prompt":   prompt_text,
        "processed_prompt":  <str>,
        "resolved_city":     <str or None>,
        "metadata":          <dict>
      }
    This exactly matches what process_app_prompt.py expects to import and index.
    """
    modified_prompt, resolved_city, metadata = resolve_city_context(prompt_text, location or {})

    return {
        "original_prompt":   prompt_text,
        "processed_prompt":  modified_prompt,
        "resolved_city":     resolved_city,
        "metadata":          metadata
    }


# ------------------------------------------------------------------------------
# Optional test harness: run “python city_resolver.py” to exercise a few sample cases.
# ------------------------------------------------------------------------------
def test_city_resolver():
    test_cases = [
        # ( prompt, location dict, expected_city )
        ("What's the weather in Paris?",     {},                           "Paris"),
        ("tell me what's happening in tokyo.", None,                       "Tokyo"),
        ("Can you give me rain chances in New York?", None,                 "New York"),
        ("How's it outside?",                {"lat": 48.85, "lon": 2.35},   None),  # fallback
        ("Do I need an umbrella?",           None,                         None),
        ("Please tell what it's like outside", {"lat": 32.2, "lon": 35.21}, None),
        ("Is it snowing here?",              {"lat": 45.76, "lon": 4.83},   None),
        ("Hey, weather in Québec?",          None,                         "Québec"),
        ("Tell me rain in Rio-de-Janeiro!",  None,                         "Rio-De-Janeiro"),
    ]

    print("🧪 Testing City Resolver + preprocess_prompt_for_weather() ...")
    for prompt, location, expected_city in test_cases:
        modified, resolved, meta = resolve_city_context(prompt, location or {})
        wrapper_output = preprocess_prompt_for_weather(prompt, location or {})
        status = ("✅" if (resolved and expected_city and resolved.lower() == expected_city.lower())
                  or (not resolved and not expected_city) else "❌")
        print(f"{status} '{prompt}' → resolved: {wrapper_output['resolved_city']}, keys: {list(wrapper_output.keys())}")
    print("🧪 Done Testing City Resolver Harness.")


if __name__ == "__main__":
    test_city_resolver()
