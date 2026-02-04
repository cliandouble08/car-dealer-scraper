"""
Crawl4AI-based URL discovery for dealer locator pages.

This module uses Crawl4AI to crawl manufacturer websites and discover dealer locator URLs.
Uses LLM to analyze discovered links and identify the best dealer locator page.
"""

import json
import asyncio
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from urllib.parse import urlparse
from crawl4ai import AsyncWebCrawler
from bs4 import BeautifulSoup


class DealerLocatorDiscovery:
    """Client for Crawl4AI-based URL discovery with LLM filtering."""

    def __init__(
        self,
        cache_dir: str = "data/discovery_cache",
        cache_ttl_days: int = 30,
        max_depth: int = 2
    ):
        """
        Initialize discovery client using Crawl4AI.

        Args:
            cache_dir: Directory for caching discovery results
            cache_ttl_days: Cache TTL in days
            max_depth: Maximum crawl depth (1 = homepage only, 2 = homepage + 1 level)
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_ttl_days = cache_ttl_days
        self.max_depth = max_depth

    def _get_cache_path(self, domain: str) -> Path:
        """Get cache file path for a domain."""
        return self.cache_dir / f"{domain}.json"

    def _is_cache_valid(self, cache_path: Path) -> bool:
        """Check if cached discovery result is still valid."""
        if not cache_path.exists():
            return False

        try:
            with open(cache_path, 'r') as f:
                data = json.load(f)
                cached_at = datetime.fromisoformat(data['cached_at'])
                age = datetime.now() - cached_at
                return age.days < self.cache_ttl_days
        except (json.JSONDecodeError, KeyError, ValueError):
            return False

    def _load_cache(self, domain: str) -> Optional[Dict]:
        """Load cached discovery result."""
        cache_path = self._get_cache_path(domain)
        if self._is_cache_valid(cache_path):
            with open(cache_path, 'r') as f:
                data = json.load(f)
                print(f"Using cached discovery result for {domain} (age: {(datetime.now() - datetime.fromisoformat(data['cached_at'])).days} days)")
                return data
        return None

    def _save_cache(self, domain: str, result: Dict):
        """Save discovery result to cache."""
        cache_path = self._get_cache_path(domain)
        result['cached_at'] = datetime.now().isoformat()
        with open(cache_path, 'w') as f:
            json.dump(result, f, indent=2)
        print(f"Cached discovery result for {domain}")

    async def crawl_for_links(self, url: str) -> Optional[Dict]:
        """
        Use Crawl4AI to discover all links on a manufacturer's homepage.

        Args:
            url: Manufacturer website URL (e.g., https://www.ford.com)

        Returns:
            Dictionary with 'urls' list or None if crawling fails
        """
        try:
            async with AsyncWebCrawler(verbose=False) as crawler:
                print(f"Crawling {url} for dealer locator links...")
                result = await crawler.arun(url=url)

                if result.success and result.html:
                    # Parse HTML to extract all links
                    soup = BeautifulSoup(result.html, 'html.parser')
                    links = []

                    for a_tag in soup.find_all('a', href=True):
                        href = a_tag['href']

                        # Handle protocol-relative URLs (//example.com/path)
                        if href.startswith('//'):
                            parsed = urlparse(url)
                            href = f"{parsed.scheme}:{href}"
                        # Convert relative URLs to absolute
                        elif href.startswith('/'):
                            parsed = urlparse(url)
                            href = f"{parsed.scheme}://{parsed.netloc}{href}"
                        elif not href.startswith('http'):
                            continue  # Skip non-HTTP links

                        # Filter out anchors, mailto, tel, etc.
                        if href.startswith(('http://', 'https://')):
                            links.append(href)

                    # Remove duplicates while preserving order
                    unique_links = list(dict.fromkeys(links))

                    print(f"Discovered {len(unique_links)} unique links from {url}")
                    return {'urls': unique_links, 'success': True}
                else:
                    print(f"Crawl4AI failed to crawl {url}")
                    return None

        except Exception as e:
            print(f"Crawl4AI error: {e}")
            return None

    def _filter_dealer_urls_with_llm(self, urls: List[str], manufacturer_url: str) -> List[Dict[str, any]]:
        """
        Use LLM to filter and score URLs for dealer locator likelihood.

        Args:
            urls: List of URLs from Firecrawl /map
            manufacturer_url: Original manufacturer URL

        Returns:
            List of dicts with 'url' and 'score' keys, sorted by score (descending)
        """
        # Import LLM analyzer (avoid circular import)
        from .llm_analyzer import LLMAnalyzer

        llm = LLMAnalyzer()

        # Filter URLs containing dealer-related keywords first
        dealer_keywords = ['dealer', 'locate', 'find', 'directory', 'locator', 'store']

        # Extensions to skip (images, documents, etc.)
        skip_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.pdf', '.svg', '.ico', '.webp', '.mp4', '.mp3', '.css', '.js', '.xml', '.json']

        filtered_urls = []

        for url in urls:
            url_lower = url.lower()

            # Skip URLs with image/document extensions
            if any(url_lower.endswith(ext) for ext in skip_extensions):
                continue

            # Skip URLs with image/asset paths
            if any(path in url_lower for path in ['/content/dam/', '/assets/', '/static/', '/media/', '/_next/']):
                continue

            if any(keyword in url_lower for keyword in dealer_keywords):
                filtered_urls.append(url)

        if not filtered_urls:
            print(f"No dealer-related URLs found in {len(urls)} URLs")
            return []

        print(f"Filtered to {len(filtered_urls)} dealer-related URLs")

        # Take top 20 most promising URLs to avoid LLM token limits
        filtered_urls = filtered_urls[:20]

        # Ask LLM to score each URL
        prompt = f"""Analyze these URLs from {manufacturer_url} and identify the BEST dealer locator page.

URLs:
{chr(10).join(f"{i+1}. {url}" for i, url in enumerate(filtered_urls))}

Your task:
1. Identify which URL is most likely the main dealer locator/finder page
2. Score each URL from 0.0 to 1.0 (1.0 = definitely the dealer locator)
3. Consider:
   - URL structure (/dealers, /find-a-dealer, /locator, etc.)
   - Avoid subpages like /dealers/specific-dealer-name
   - Prefer shorter, more general paths
   - Avoid API endpoints, media, or utility pages

Return ONLY valid JSON in this format:
{{
  "best_url": "https://www.example.com/dealer-locator/",
  "scored_urls": [
    {{"url": "https://...", "score": 0.95, "reason": "Main dealer locator page"}},
    {{"url": "https://...", "score": 0.7, "reason": "Dealer search with filters"}},
    ...
  ]
}}
"""

        try:
            response = llm._call_llm(prompt, max_tokens=2000)
            result = llm._parse_json_response(response)

            if result and 'scored_urls' in result:
                # Sort by score descending
                scored = sorted(result['scored_urls'], key=lambda x: x.get('score', 0), reverse=True)
                print(f"LLM scored {len(scored)} URLs, best: {scored[0]['url']} (score: {scored[0]['score']})")
                return scored
            else:
                print("LLM response missing 'scored_urls', using heuristic fallback")
                return self._heuristic_url_scoring(filtered_urls)

        except Exception as e:
            print(f"LLM scoring failed: {e}, using heuristic fallback")
            return self._heuristic_url_scoring(filtered_urls)

    def _heuristic_url_scoring(self, urls: List[str]) -> List[Dict[str, any]]:
        """
        Fallback heuristic scoring when LLM fails.

        Prioritizes:
        - Shorter paths (more general)
        - Contains 'dealer' or 'locator' in path
        - Avoids specific dealer names, API endpoints, images
        """
        scored = []

        # Extensions to penalize heavily
        skip_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.pdf', '.svg', '.ico', '.webp', '.mp4', '.mp3', '.css', '.js']

        for url in urls:
            parsed = urlparse(url)
            path = parsed.path.lower()

            # Skip images and other non-HTML resources
            if any(path.endswith(ext) for ext in skip_extensions):
                continue

            # Skip asset paths
            if any(part in path for part in ['/content/dam/', '/assets/', '/static/', '/media/']):
                continue

            score = 0.5  # Base score

            # Boost for dealer/locator keywords
            if 'dealer' in path:
                score += 0.2
            if 'locator' in path or 'find' in path:
                score += 0.2

            # Penalize long paths (likely subpages)
            path_segments = [s for s in path.split('/') if s]
            if len(path_segments) <= 2:
                score += 0.1
            elif len(path_segments) > 3:
                score -= 0.2

            # Penalize specific dealer names (heuristic: contains digits or long segments)
            if any(len(seg) > 15 for seg in path_segments):
                score -= 0.2

            # Boost if path ends with slash (likely a page, not a file)
            if path.endswith('/'):
                score += 0.1

            scored.append({'url': url, 'score': max(0.0, min(1.0, score)), 'reason': 'Heuristic scoring'})

        return sorted(scored, key=lambda x: x['score'], reverse=True)

    async def discover_locator_url(self, manufacturer_url: str) -> Optional[Dict]:
        """
        Discover the dealer locator URL for a manufacturer website.

        This is the main entry point. It:
        1. Checks cache first
        2. Calls Firecrawl /map (if enabled and available)
        3. Filters URLs with LLM
        4. Caches result

        Args:
            manufacturer_url: URL like https://www.ford.com or https://www.toyota.com

        Returns:
            Dictionary with:
            - locator_url: The best dealer locator URL
            - confidence: Score 0.0-1.0
            - method: 'firecrawl' or 'llm_only'
            - all_candidates: List of all scored URLs
        """
        parsed = urlparse(manufacturer_url)
        domain = parsed.netloc.replace('www.', '')

        # Check cache
        cached = self._load_cache(domain)
        if cached:
            return cached

        # Try Crawl4AI first
        crawl_result = await self.crawl_for_links(manufacturer_url)

        if crawl_result and crawl_result.get('success'):
            # Use Crawl4AI discovered URLs
            urls = crawl_result['urls']
            method = 'crawl4ai'
        else:
            # Fallback: Use LLM to guess common dealer locator URLs
            print("Using fallback URL generation")
            urls = self._generate_candidate_urls(manufacturer_url)
            method = 'fallback'

        # Score URLs with LLM
        scored_urls = self._filter_dealer_urls_with_llm(urls, manufacturer_url)

        if not scored_urls:
            print(f"No dealer locator URL found for {manufacturer_url}")
            return None

        # Best result
        best = scored_urls[0]
        result = {
            'locator_url': best['url'],
            'confidence': best['score'],
            'method': method,
            'all_candidates': scored_urls[:5],  # Top 5 only
            'domain': domain
        }

        # Cache result
        self._save_cache(domain, result)

        return result

    def _generate_candidate_urls(self, base_url: str) -> List[str]:
        """
        Generate common dealer locator URL patterns when Firecrawl is unavailable.

        Args:
            base_url: Manufacturer website (e.g., https://www.ford.com)

        Returns:
            List of candidate URLs to check
        """
        parsed = urlparse(base_url)
        base = f"{parsed.scheme}://{parsed.netloc}"

        # Common dealer locator path patterns
        patterns = [
            '/dealerships/',
            '/dealers/',
            '/find-a-dealer/',
            '/dealer-locator/',
            '/locate-dealer/',
            '/locate/',
            '/find-dealer/',
            '/where-to-buy/',
            '/dealer-search/',
            '/locator/',
            '/find/',
            '/dealers/search/',
            '/dealer/',
        ]

        candidates = [base + pattern for pattern in patterns]
        print(f"Generated {len(candidates)} candidate URLs for {base_url}")
        return candidates


# Async test function
async def test_discovery():
    """Test Crawl4AI-based discovery on a known manufacturer."""
    client = DealerLocatorDiscovery()

    result = await client.discover_locator_url("https://www.ford.com")
    if result:
        print("\nDiscovery Result:")
        print(f"  Locator URL: {result['locator_url']}")
        print(f"  Confidence: {result['confidence']}")
        print(f"  Method: {result['method']}")
        print(f"  Top Candidates:")
        for candidate in result['all_candidates'][:3]:
            print(f"    - {candidate['url']} (score: {candidate['score']})")
    else:
        print("Discovery failed")


if __name__ == "__main__":
    asyncio.run(test_discovery())
