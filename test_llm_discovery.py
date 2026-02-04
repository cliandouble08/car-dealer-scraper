#!/usr/bin/env python3
"""
Test script for LLM-based form field discovery.

This script tests the new LLM discovery workflow without actually submitting forms.
"""

import asyncio
import os
from utils.crawl4ai_scraper import Crawl4AIScraper


async def test_discovery():
    """Test LLM discovery on a simple dealer locator."""

    # Set up environment for testing
    os.environ['LLM_ANALYSIS_ENABLED'] = 'true'
    os.environ['LLM_ENDPOINT'] = 'http://localhost:11434/api/generate'
    os.environ['LLM_MODEL'] = 'gemma2:2b'

    scraper = Crawl4AIScraper(headless=False, verbose=True)

    # Test configuration
    config = {
        'selectors': {
            'search_input': ['#searchbox'],
            'search_button': ['button[type="submit"]'],
            'dealer_cards': ['.dealer-card', '.result-item']
        },
        'crawl4ai_interactions': {},
        'interactions': {
            'pagination_type': 'none'
        }
    }

    test_url = "https://www.ford.com/dealerships/"
    test_zip = "10001"

    print("\n" + "="*60)
    print("Testing LLM Discovery Workflow")
    print("="*60)
    print(f"URL: {test_url}")
    print(f"Zip Code: {test_zip}")
    print("="*60 + "\n")

    try:
        html = await scraper.scrape_with_search(
            url=test_url,
            zip_code=test_zip,
            config=config,
            expand_results=False  # Don't expand for initial test
        )

        if html:
            print(f"\n✓ SUCCESS: Received {len(html)} characters of HTML")

            # Check for dealer cards
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')

            # Try common dealer card selectors
            for selector in ['.dealer-card', '[class*="dealer"]', '[class*="result"]']:
                cards = soup.select(selector)
                if cards:
                    print(f"✓ Found {len(cards)} cards with selector: {selector}")
                    break
            else:
                print("⚠ No dealer cards found in HTML")
        else:
            print("\n✗ FAILED: No HTML returned")

    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "="*60)
    print("Test Complete")
    print("="*60 + "\n")


if __name__ == "__main__":
    asyncio.run(test_discovery())
