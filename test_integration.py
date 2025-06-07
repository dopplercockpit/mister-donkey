#test_integration
# Optional: Standalone test function
def test_integration():
    """Test the integrated City Resolver with various scenarios."""
    test_scenarios = [
        # Should prevent GPT hallucination
        {
            "prompt": "Do I need a coat?",
            "location": {"name": "Paris", "lat": 48.8566, "lon": 2.3522},
            "expected_behavior": "Should use Paris, not hallucinate"
        },
        {
            "prompt": "Will it rain tonight?",
            "location": {"name": "London", "lat": 51.5074, "lon": -0.1278},
            "expected_behavior": "Should use London"
        },
        {
            "prompt": "What's the weather in Tokyo?",
            "location": {"name": "Paris", "lat": 48.8566, "lon": 2.3522},
            "expected_behavior": "Should use Tokyo (explicit), ignore Paris"
        },
        {
            "prompt": "How's the climate?",
            "location": {"name": "Berlin", "lat": 52.5200, "lon": 13.4050},
            "expected_behavior": "Should return error or use fallback (no weather context)"
        }
    ]
    
    print("🧪 Testing Integrated City Resolver...")
    for i, scenario in enumerate(test_scenarios, 1):
        print(f"\n--- Test {i}: {scenario['expected_behavior']} ---")
        print(f"Prompt: '{scenario['prompt']}'")
        print(f"Location: {scenario['location']['name']}")
        
        # This would normally call your weather API, but for testing we'll just show the preprocessing
        resolver_result = preprocess_prompt_for_weather(scenario["prompt"], scenario["location"])
        
        print(f"✅ Processed: '{resolver_result['processed_prompt']}'")
        print(f"✅ Resolved City: {resolver_result['resolved_city']}")
        print(f"✅ Method: {resolver_result['metadata']['resolution_method']}")

if __name__ == "__main__":
    test_integration()