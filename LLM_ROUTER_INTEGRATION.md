# LLM Router Integration

## Overview

The LLM Router has been successfully integrated as a pre-processing step in the weather app's location resolution pipeline. This replaces fragile regex-based city detection with intelligent semantic understanding powered by GPT.

## What Changed

### New File: `llm_router.py`

Contains three main functions:

1. **`route_request(user_prompt: str) -> dict`**
   - Core LLM function that analyzes user prompts
   - Extracts location entities using OpenAI's function calling
   - Returns: `{"target_location": str|None, "cleaned_prompt": str, "is_location_explicit": bool}`

2. **`resolve_city_context_with_llm(prompt_text: str, location: dict) -> tuple`**
   - Wrapper that matches the `city_resolver.resolve_city_context()` interface
   - Returns: `(modified_prompt, resolved_city, metadata)`

3. **`preprocess_prompt_for_weather_with_llm(prompt_text: str, location: dict) -> dict`**
   - Wrapper that matches the `city_resolver.preprocess_prompt_for_weather()` interface
   - Returns: `{"original_prompt": str, "processed_prompt": str, "resolved_city": str|None, "metadata": dict}`

### Modified File: `process_app_prompt.py`

- **Line 11**: Added import: `from llm_router import preprocess_prompt_for_weather_with_llm`
- **Line 37**: Changed from regex-based resolver to LLM router:
  ```python
  # OLD: resolver_result = preprocess_prompt_for_weather(prompt_text, location)
  # NEW: resolver_result = preprocess_prompt_for_weather_with_llm(prompt_text, location)
  ```
- **Lines 43-48**: Updated logging to reflect LLM router usage
- **Line 104**: Updated diagnostics to track `llm_router` instead of `city_resolver`

## Advantages Over Regex

### Before (Regex-based):
- ❌ Couldn't handle nicknames ("Big Apple" → failed)
- ❌ Mistook idioms for cities ("Holy Toledo" → Toledo, Spain)
- ❌ Required exact patterns ("in Paris" worked, "Paris weather" didn't)
- ❌ No semantic understanding

### After (LLM-based):
- ✅ Handles city nicknames and natural language
- ✅ Filters out idioms and expressions
- ✅ Understands "here", "outside", "local" as user's current location
- ✅ Works with any phrasing or word order
- ✅ Semantic understanding of user intent

## Architecture

```
User Input
    ↓
LLM Router (llm_router.py)
    ↓
Extract: target_location + cleaned_prompt
    ↓
Existing Pipeline (improved_location_resolver.py)
    ↓
Geocode → Validate → Fetch Weather
```

## Test Cases

The LLM router correctly handles:

1. **Explicit cities**: "What's the weather in Tokyo?" → Tokyo
2. **City nicknames**: "Weather in The Big Apple" → The Big Apple
3. **Implicit location**: "What's it like here?" → None (uses GPS)
4. **Idioms**: "Holy Toledo, it's hot!" → None (not a location query)
5. **City with country**: "Is it raining in Paris, France?" → Paris, France
6. **Casual phrases**: "How's it outside?" → None (uses GPS)

## Fallback Behavior

If the LLM router fails (API error, timeout, etc.):
- Returns original prompt unchanged
- Sets `target_location` to `None`
- Falls back to user's geolocation
- Logs error for debugging

## Configuration

The LLM router uses:
- **Model**: Configured in `config.py` via `OPENAI_MODEL` (default: `gpt-4o-mini`)
- **API Key**: Configured in `config.py` via `OPENAI_API_KEY`
- **Temperature**: `0.0` (deterministic output)
- **Function Calling**: Uses OpenAI's structured output for reliability

## Cost Impact

- **Per request**: ~$0.0001 - $0.0005 (with gpt-4o-mini)
- **Monthly estimate** (1000 requests): ~$0.10 - $0.50
- Cost is minimal compared to functionality improvement

## Next Steps

To test in production:
1. Ensure `OPENAI_API_KEY` is set in environment
2. Restart the backend server
3. Monitor logs for "🧠 LLM Router:" messages
4. Test with various natural language prompts

## Rollback

To revert to regex-based routing:

In `process_app_prompt.py` line 37, change:
```python
resolver_result = preprocess_prompt_for_weather_with_llm(prompt_text, location)
```

Back to:
```python
resolver_result = preprocess_prompt_for_weather(prompt_text, location)
```
