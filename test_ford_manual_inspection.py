#!/usr/bin/env python
"""
Manual inspection script for Ford.com dealer locator
Run this with visible browser to see what's actually happening
"""
import asyncio
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig
from bs4 import BeautifulSoup

async def test_ford_manual():
    url = "https://www.ford.com/dealerships/?zipcode=10001"

    print("=" * 70)
    print("FORD.COM DEALER LOCATOR MANUAL INSPECTION")
    print("=" * 70)
    print(f"\nNavigating to: {url}")
    print("Browser will stay open for 60 seconds for manual inspection")
    print("\nPlease observe:")
    print("  1. Do dealer cards appear on the page?")
    print("  2. How long does it take for them to load?")
    print("  3. What are the HTML classes/IDs of dealer cards?")
    print("  4. Right-click on a dealer card and inspect element")
    print("=" * 70)

    async with AsyncWebCrawler(headless=False, verbose=True) as crawler:
        config = CrawlerRunConfig(
            page_timeout=30000,
            delay_before_return_html=20  # Wait 20 seconds
        )

        result = await crawler.arun(url=url, config=config)

        if result.success:
            soup = BeautifulSoup(result.html, 'html.parser')

            print("\n" + "=" * 70)
            print("ANALYSIS OF CAPTURED HTML")
            print("=" * 70)

            # Check for phone links
            phones = soup.find_all('a', href=lambda h: h and h.startswith('tel:'))
            print(f"\n✓ Phone links found: {len(phones)}")
            for phone in phones:
                print(f"    {phone.get('href')}")

            # Check for common dealer selectors
            print("\n✓ Testing common dealer card selectors:")
            test_selectors = [
                'li.dealer-results-item',
                '.dealer-card',
                '[data-dealer-id]',
                '[class*="dealer-result"]',
                'article',
                'li[role="listitem"]',
            ]

            for selector in test_selectors:
                count = len(soup.select(selector))
                print(f"    {selector}: {count} elements")

            # Save HTML
            with open('/tmp/ford_manual_inspection.html', 'w') as f:
                f.write(result.html)
            print(f"\n✓ Full HTML saved to: /tmp/ford_manual_inspection.html")

            print("\n" + "=" * 70)
            print("BROWSER WILL STAY OPEN FOR 60 SECONDS")
            print("Please inspect the page and note:")
            print("  - Dealer card HTML structure")
            print("  - CSS selectors (classes, IDs)")
            print("  - Any error messages or loading indicators")
            print("=" * 70)

            await asyncio.sleep(60)
        else:
            print(f"\n❌ Failed to load page: {result.error_message if hasattr(result, 'error_message') else 'Unknown'}")

if __name__ == "__main__":
    asyncio.run(test_ford_manual())
