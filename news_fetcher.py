# news_fetcher.py
# Fetches contextual news for location-based weather responses
# Integrates with NewsAPI.org

import os
import requests
from typing import List, Dict, Optional
import time
from logger_config import setup_logger, log_api_call

# Configure logging
logger = setup_logger("mister_donkey.news")

NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "").strip()
NEWS_API_URL = "https://newsapi.org/v2/everything"

def get_location_news(location_name: str, country_code: Optional[str] = None, max_results: int = 3) -> List[Dict]:
    """
    Fetch top news headlines for a location using NewsAPI.org.

    Args:
        location_name: City or region name (e.g., "Caracas", "New York")
        country_code: Optional 2-letter country code (e.g., "ve", "us")
        max_results: Number of articles to return (default: 3)

    Returns:
        List of article dicts with keys: title, description, url, publishedAt, source
        Returns empty list on failure (fails silently with error logging)
    """
    if not NEWSAPI_KEY:
        logger.warning("⚠️ NEWSAPI_KEY not set in environment variables, skipping news fetch")
        return []

    # Build search query - exclude sports to focus on meaningful news
    query = f"{location_name} -sport -sports -game -match -football -basketball -baseball"
    if country_code:
        query += f" {country_code}"

    params = {
        "q": query,
        "language": "en",
        "sortBy": "relevancy",
        "pageSize": max_results,
        "apiKey": NEWSAPI_KEY
    }

    try:
        start_time = time.time()
        logger.info(f"📰 Fetching news for: {location_name}")

        response = requests.get(NEWS_API_URL, params=params, timeout=5)
        duration_ms = (time.time() - start_time) * 1000

        response.raise_for_status()
        data = response.json()

        # Check for API errors
        if data.get("status") != "ok":
            error_msg = data.get("message", "Unknown error")
            log_api_call("NewsAPI", "error", duration_ms, f"{location_name} - {error_msg}")
            return []

        articles = data.get("articles", [])[:max_results]

        # Clean and format articles
        cleaned_articles = []
        for article in articles:
            # Skip articles with null or missing titles
            if not article.get("title") or article.get("title") == "[Removed]":
                continue

            cleaned_articles.append({
                "title": article.get("title", ""),
                "description": (article.get("description") or "")[:200],  # Truncate for prompt
                "url": article.get("url", ""),
                "published": article.get("publishedAt", ""),
                "source": article.get("source", {}).get("name", "Unknown")
            })

        log_api_call("NewsAPI", "success", duration_ms, f"{location_name} - {len(cleaned_articles)} articles")
        return cleaned_articles

    except requests.exceptions.Timeout:
        log_api_call("NewsAPI", "error", 5000, f"{location_name} - Timeout (>5s)")
        return []
    except requests.exceptions.RequestException as e:
        log_api_call("NewsAPI", "error", 0, f"{location_name} - {str(e)}")
        return []
    except Exception as e:
        logger.error(f"❌ Unexpected error fetching news for {location_name}: {str(e)}", exc_info=True)
        log_api_call("NewsAPI", "error", 0, f"{location_name} - Unexpected: {str(e)}")
        return []


def format_news_for_prompt(articles: List[Dict]) -> str:
    """
    Format news articles for GPT prompt context.
    Creates a concise summary suitable for personality integration.

    Args:
        articles: List of article dicts from get_location_news()

    Returns:
        Formatted string with headlines and descriptions, or empty string if no articles
    """
    if not articles:
        return ""

    news_lines = []
    for i, article in enumerate(articles, 1):
        # Format: "1. [Source] Title - Description"
        line = f"{i}. [{article['source']}] {article['title']}"
        if article.get('description'):
            line += f" - {article['description']}"
        news_lines.append(line)

    return "\n".join(news_lines)


def extract_country_code(location_name: str) -> Optional[str]:
    """
    Attempt to extract country code from location name if it contains country.

    Examples:
        "Paris, France" -> "fr"
        "New York, USA" -> "us"
        "Tokyo" -> None

    Args:
        location_name: Full location string (e.g., "City, Country")

    Returns:
        2-letter country code or None
    """
    # Simple country mapping for common cases
    country_map = {
        "USA": "us",
        "United States": "us",
        "US": "us",
        "UK": "gb",
        "United Kingdom": "gb",
        "France": "fr",
        "Germany": "de",
        "Spain": "es",
        "Italy": "it",
        "Canada": "ca",
        "Australia": "au",
        "Japan": "jp",
        "China": "cn",
        "India": "in",
        "Brazil": "br",
        "Mexico": "mx",
        "Russia": "ru",
        "Venezuela": "ve",
        "Ukraine": "ua",
        "Israel": "il",
        "Palestine": "ps",
        "Egypt": "eg",
        "South Africa": "za",
        "Nigeria": "ng",
        "Kenya": "ke"
    }

    # Check if location contains a comma (likely "City, Country" format)
    if "," in location_name:
        parts = location_name.split(",")
        country_part = parts[-1].strip()

        # Look for match in country map
        for country, code in country_map.items():
            if country.lower() in country_part.lower():
                return code

    return None
