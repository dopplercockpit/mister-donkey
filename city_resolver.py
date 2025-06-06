# File: /mnt/data/city_resolver.py
# Description: Smart City Resolver Preprocessor for Doppler Tower / Mister Donkey
#              We had removed preprocess_prompt_for_weather in our last iteration, but
#              process_app_prompt.py still expects to import it. This updated file
#              restores a minimal stub for preprocess_prompt_for_weather so that
#              your imports no longer fail. It simply calls resolve_city_context()
#              and packages its output into a dict.

import re
from typing import Dict, Optional, Tuple
from geo_utils_helper import reverse_geolocate

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
    modified_prompt: str = text  # By default, we’ll return the prompt unchanged

    # --------------------------------------------------------------------------
    # 1) If the frontend already gave us a "name" (e.g. user clicked "Yep, that's right"),
    #    use that directly:
    # --------------------------------------------------------------------------
    if location is not None and isinstance(location, dict) and location.get("name"):
        resolved_city = location["name"]
        metadata["resolution_method"] = "frontend_location_name"
        metadata["resolved_city"] = resolved_city
        return modified_prompt, resolved_city, metadata

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
    #                                       spaces, apostrophes, and hyphens. e.g. "New York", "Québec", "Rio-de-Janeiro"
    #        • (?=[?!.;,]|$)     → lookahead for punctuation or end‐of‐string so we don't capture trailing words.
    #
    #    After we capture, we check that it isn't a filler word like "here" or "outside".
    # --------------------------------------------------------------------------
    explicit_pattern = re.compile(r"\b in\s+([A-Za-zÀ-ÖØ-öø-ÿ'’\- ]+?)(?=[?!.;,]|$)", flags=re.IGNORECASE)
    match = explicit_pattern.search(text)
    if match:
        candidate = match.group(1).strip()  # e.g. "Paris" or "New York"
        candidate_title = candidate.title()  # Normalize to Title Case

        # We reject obvious filler tokens like “here”, “outside”, etc.
        filler_tokens = {"here", "outside", "it", "this", "that", "now", "today", "tomorrow"}
        if candidate_title.lower() not in filler_tokens:
            resolved_city = candidate_title
            metadata["resolution_method"] = "explicit_regex"
            metadata["resolved_city"] = resolved_city

            # Remove “in {city}” from the prompt so GPT won’t see “weather in Paris in Paris”
            start, end = match.span()
            modified_prompt = (text[:start] + text[end:]).strip()
            # Collapse any double spaces if they appear
            modified_prompt = re.sub(r"\s{2,}", " ", modified_prompt).strip()
            return modified_prompt, resolved_city, metadata
        # else: it was “in here” or “in outside” → ignore and fall through

    # --------------------------------------------------------------------------
    # 3) Check for implicit keywords that mean “my current location”: e.g. “outside”, “around here”
    #    If found, we do NOT set a city here. We let routes.py do reverse‐geolocate(lat, lon).
    # --------------------------------------------------------------------------
    implicit_keywords = {"outside", "around here", "here", "nearby"}
    lower_text = text.lower()
    for key in implicit_keywords:
        if key in lower_text:
            metadata["resolution_method"] = "implicit_keyword"
            metadata["resolved_city"] = None
            return modified_prompt, None, metadata

    # --------------------------------------------------------------------------
    # 4) No explicit “in X” and no “name” from the front‐end → fallback to “none”
    #    The caller (routes.py) will check if lat/lon exists and run reverse_geolocate().
    # --------------------------------------------------------------------------
    metadata["resolution_method"] = "none"
    metadata["resolved_city"] = None
    return modified_prompt, None, metadata


# ------------------------------------------------------------------------------
# This helper was originally “missing,” which caused the ImportError in process_app_prompt.py.
# We re-create it here as a thin wrapper over resolve_city_context(), returning a dict with keys:
#    { "processed_prompt": ..., "resolved_city": ..., "metadata": { ... } }
# So that process_app_prompt.py’s import no longer fails.
# ------------------------------------------------------------------------------
def preprocess_prompt_for_weather(prompt_text: str, location: Optional[Dict] = None) -> Dict:
    """
    Wrapper that calls resolve_city_context() and formats its output as a dict:
      {
        "processed_prompt": <str>,
        "resolved_city":    <str or None>,
        "metadata":         <dict>
      }
    This matches exactly what process_app_prompt.py expects to import.
    """
    modified_prompt, resolved_city, metadata = resolve_city_context(prompt_text, location or {})
    return {
        "processed_prompt": modified_prompt,
        "resolved_city": resolved_city,
        "metadata": metadata
    }


# ------------------------------------------------------------------------------
# Optional test harness: run “python city_resolver.py” to exercise a few sample cases.
# You can leave this in place; it will only run when you invoke the module directly.
# ------------------------------------------------------------------------------
def test_city_resolver():
    test_cases = [
        # ( prompt                            , location dict                , expected_city )
        ("What's the weather in Paris?",     {},                             "Paris"),
        ("tell me what's happening in tokyo.", None,                          "Tokyo"),
        ("Can you give me rain chances in New York?", None,                    "New York"),
        ("How's it outside?",                {"lat": 48.85, "lon": 2.35},     None),  # fallback to reverse
        ("Do I need an umbrella?",           None,                          None),  # no “in X”
        ("Please tell what it's like outside", {"lat": 32.2, "lon": 35.21},   None),
        ("Is it snowing here?",              {"lat": 45.76, "lon": 4.83},     None),
        ("Hey, weather in Québec?",          None,                          "Québec"),
        ("Tell me rain in Rio-de-Janeiro!",  None,                          "Rio-De-Janeiro"),
    ]

    print("🧪 Testing City Resolver + preprocess_prompt_for_weather() ...")
    for i, (prompt, location, expected_city) in enumerate(test_cases, 1):
        proc_prompt, resolved, meta = resolve_city_context(prompt, location or {})
        # Check our low-level resolve_city_context first:
        status1 = ("✅" if ((resolved and expected_city and resolved.lower() == expected_city.lower())
                         or (not resolved and not expected_city)) else "❌")
        print(f"{status1} [resolve_city_context] '{prompt}' → Resolved City: {resolved}  (Method: {meta['resolution_method']})")
        # Now check the wrapper:
        wrapper_output = preprocess_prompt_for_weather(prompt, location or {})
        status2 = ("✅" if (wrapper_output["resolved_city"] == expected_city) else "❌")
        print(f"   {status2} [preprocess_prompt_for_weather] returned → {wrapper_output}")
    print("🧪 Done Testing City Resolver Harness.")


if __name__ == "__main__":
    test_city_resolver()
