#!/usr/bin/env python3
"""
Quick integration test for the LLM router.
Tests various prompt scenarios to ensure proper location extraction.
"""

from llm_router import preprocess_prompt_for_weather_with_llm

def test_llm_router():
    """Test various prompt scenarios"""

    test_cases = [
        {
            "prompt": "What's the weather in Tokyo?",
            "expected_city": "Tokyo",
            "expected_explicit": True,
            "description": "Explicit city mention"
        },
        {
            "prompt": "Tell me the weather in The Big Apple",
            "expected_city": "The Big Apple",
            "expected_explicit": True,
            "description": "City nickname"
        },
        {
            "prompt": "What's the weather like here?",
            "expected_city": None,
            "expected_explicit": False,
            "description": "Implicit location (here)"
        },
        {
            "prompt": "How's it outside?",
            "expected_city": None,
            "expected_explicit": False,
            "description": "Implicit location (outside)"
        },
        {
            "prompt": "Is it raining in Paris, France?",
            "expected_city": "Paris, France",
            "expected_explicit": True,
            "description": "City with country"
        },
        {
            "prompt": "Holy Toledo, is it hot today!",
            "expected_city": None,
            "expected_explicit": False,
            "description": "Idiom that should NOT be interpreted as city"
        }
    ]

    print("🧪 Testing LLM Router Integration\n")
    print("=" * 60)

    for i, test in enumerate(test_cases, 1):
        print(f"\nTest {i}: {test['description']}")
        print(f"Prompt: \"{test['prompt']}\"")

        try:
            result = preprocess_prompt_for_weather_with_llm(test['prompt'])

            resolved_city = result.get("resolved_city")
            is_explicit = result.get("metadata", {}).get("is_location_explicit")
            cleaned_prompt = result.get("processed_prompt")

            # Check if results match expectations
            city_match = resolved_city == test["expected_city"]
            explicit_match = is_explicit == test["expected_explicit"]

            status = "✅ PASS" if (city_match and explicit_match) else "❌ FAIL"

            print(f"{status}")
            print(f"  Resolved City: {resolved_city} (expected: {test['expected_city']})")
            print(f"  Is Explicit: {is_explicit} (expected: {test['expected_explicit']})")
            print(f"  Cleaned Prompt: \"{cleaned_prompt}\"")

        except Exception as e:
            print(f"❌ ERROR: {e}")

    print("\n" + "=" * 60)
    print("🧪 Test Complete\n")


if __name__ == "__main__":
    test_llm_router()
