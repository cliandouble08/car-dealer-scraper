#!/usr/bin/env python3
"""
Crawl4AI URL Discovery

Uses Crawl4AI to extract all URLs from a website and identify the dealer locator page.
"""

import asyncio
import os
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

try:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
    CRAWL4AI_AVAILABLE = True
except ImportError:
    CRAWL4AI_AVAILABLE = False
    AsyncWebCrawler = None
    BrowserConfig = None
    CrawlerRunConfig = None


class Crawl4AIDiscovery:
    """
    Discovers dealer locator URLs using Crawl4AI for link extraction
    and LLM for intelligent selection.
    """

    # Keywords that indicate a dealer locator page
    LOCATOR_KEYWORDS = [
        'dealer', 'dealers', 'dealership', 'dealerships',
        'locator', 'locate', 'location', 'locations',
        'find', 'finder', 'search', 'directory',
        'store', 'stores', 'retailer', 'retailers',
        'showroom', 'showrooms', 'branch', 'branches'
    ]

    # Negative keywords to filter out
    NEGATIVE_KEYWORDS = [
        'incentive', 'offer', 'build', 'price', 'compare', 'inventory',
        'preowned', 'pre-owned', 'used', 'lease', 'apr', 'credit',
        'quote', 'estimate', 'payment', 'test-drive', 'schedule',
        'finance', 'financing', 'parts', 'service', 'accessories',
        'recall', 'warranty', 'owner', 'manual', 'brochure',
        'news', 'press', 'media', 'blog', 'career', 'jobs',
        'about', 'contact', 'privacy', 'terms', 'legal', 'sitemap',
        'login', 'signin', 'register', 'account', 'cart', 'checkout'
    ]

    # High-value path patterns that strongly indicate dealer locator
    HIGH_VALUE_PATTERNS = [
        r'/dealer[s]?(?:/|$)',
        r'/find-a-dealer',
        r'/find-dealer',
        r'/dealer-locator',
        r'/locate-dealer',
        r'/dealership[s]?(?:/|$)',
        r'/location[s]?(?:/|$)',
        r'/store-locator',
        r'/find-a-store',
        r'/retailer[s]?(?:/|$)',
    ]

    def __init__(self, llm_analyzer=None, headless: bool = True):
        """
        Initialize Crawl4AI discovery.

        Args:
            llm_analyzer: LLMAnalyzer instance for intelligent URL selection
            headless: Whether to run browser in headless mode
        """
        self.llm_analyzer = llm_analyzer
        self.headless = headless
        self.enabled = CRAWL4AI_AVAILABLE

        if not CRAWL4AI_AVAILABLE:
            print("Warning: crawl4ai not installed. Run: pip install crawl4ai")

    async def discover_urls(self, url: str) -> Dict[str, Any]:
        """
        Crawl a website and extract all internal URLs.

        Args:
            url: Base URL to crawl

        Returns:
            Dict with 'internal_links', 'external_links', 'markdown', 'success'
        """
        if not self.enabled:
            return {
                'success': False,
                'error': 'crawl4ai not available',
                'internal_links': [],
                'external_links': [],
                'markdown': ''
            }

        browser_config = BrowserConfig(
            headless=self.headless,
            viewport_width=1920,
            viewport_height=1080,
        )

        crawler_config = CrawlerRunConfig(
            page_timeout=30000,
            remove_overlay_elements=True,
        )

        try:
            async with AsyncWebCrawler(config=browser_config) as crawler:
                result = await crawler.arun(url=url, config=crawler_config)

                if not result.success:
                    return {
                        'success': False,
                        'error': 'Crawl failed',
                        'internal_links': [],
                        'external_links': [],
                        'markdown': ''
                    }

                # Extract links from result
                internal_links = []
                external_links = []

                # Handle different result formats
                if hasattr(result, 'links') and result.links:
                    if isinstance(result.links, dict):
                        internal_links = result.links.get('internal', [])
                        external_links = result.links.get('external', [])
                    elif isinstance(result.links, list):
                        # If links is a list, categorize them
                        base_domain = urlparse(url).netloc.replace('www.', '')
                        for link in result.links:
                            link_url = link if isinstance(link, str) else link.get('href', '')
                            if link_url:
                                link_domain = urlparse(link_url).netloc.replace('www.', '')
                                if link_domain == base_domain or not link_domain:
                                    internal_links.append(link_url)
                                else:
                                    external_links.append(link_url)

                # Normalize internal links to full URLs
                normalized_internal = []
                for link in internal_links:
                    if isinstance(link, dict):
                        link = link.get('href', '')
                    if link:
                        full_url = urljoin(url, link)
                        normalized_internal.append(full_url)

                return {
                    'success': True,
                    'internal_links': list(set(normalized_internal)),
                    'external_links': external_links,
                    'markdown': result.markdown if hasattr(result, 'markdown') else '',
                    'html': result.html if hasattr(result, 'html') else ''
                }

        except Exception as e:
            print(f"Error during Crawl4AI discovery: {e}")
            return {
                'success': False,
                'error': str(e),
                'internal_links': [],
                'external_links': [],
                'markdown': ''
            }

    def _score_url(self, url: str) -> Tuple[int, str]:
        """
        Score a URL based on how likely it is to be a dealer locator.

        Args:
            url: URL to score

        Returns:
            Tuple of (score, reason)
        """
        url_lower = url.lower()
        path = urlparse(url).path.lower()
        score = 0
        reasons = []

        # Check high-value patterns (strong indicators)
        for pattern in self.HIGH_VALUE_PATTERNS:
            if re.search(pattern, path):
                score += 10
                reasons.append(f"matches pattern: {pattern}")

        # Check for locator keywords in path
        for keyword in self.LOCATOR_KEYWORDS:
            if keyword in path:
                score += 3
                reasons.append(f"contains keyword: {keyword}")

        # Check for negative keywords (reduce score)
        for neg_keyword in self.NEGATIVE_KEYWORDS:
            if neg_keyword in path:
                score -= 5
                reasons.append(f"negative keyword: {neg_keyword}")

        # Prefer shorter paths (more likely to be main pages)
        path_depth = len([p for p in path.split('/') if p])
        if path_depth <= 2:
            score += 2
            reasons.append(f"shallow path depth: {path_depth}")
        elif path_depth > 4:
            score -= 2
            reasons.append(f"deep path: {path_depth}")

        # Avoid hash fragments (usually not separate pages)
        if '#' in url:
            score -= 3
            reasons.append("contains hash fragment")

        # Avoid query parameters (often filters/searches)
        if '?' in url:
            score -= 1
            reasons.append("contains query params")

        return score, "; ".join(reasons) if reasons else "no specific indicators"

    def filter_locator_candidates(self, urls: List[str], base_url: str) -> List[Dict[str, Any]]:
        """
        Filter and score URLs to find dealer locator candidates.

        Args:
            urls: List of URLs to filter
            base_url: Original base URL for context

        Returns:
            List of candidate dicts with 'url', 'score', 'reason', sorted by score
        """
        base_domain = urlparse(base_url).netloc.replace('www.', '')
        candidates = []
        seen_normalized = set()

        for url in urls:
            # Skip empty or javascript URLs
            if not url or url.startswith('javascript:') or url.startswith('mailto:'):
                continue

            # Normalize URL
            full_url = urljoin(base_url, url)
            url_domain = urlparse(full_url).netloc.replace('www.', '')

            # Only consider internal links
            if url_domain != base_domain:
                continue

            # Deduplicate by path (ignore query strings for dedup)
            normalized = urlparse(full_url)._replace(query='', fragment='').geturl()
            if normalized in seen_normalized:
                continue
            seen_normalized.add(normalized)

            # Score the URL
            score, reason = self._score_url(full_url)

            # Only include if score is positive
            if score > 0:
                candidates.append({
                    'url': full_url,
                    'score': score,
                    'reason': reason
                })

        # Sort by score descending
        candidates.sort(key=lambda x: x['score'], reverse=True)

        return candidates

    def select_best_locator_with_llm(
        self,
        candidates: List[Dict[str, Any]],
        base_url: str,
        page_content: str = ""
    ) -> Optional[Dict[str, Any]]:
        """
        Use LLM to select the best dealer locator URL from candidates.

        Args:
            candidates: List of candidate URLs with scores
            base_url: Original base URL
            page_content: Optional page content for additional context

        Returns:
            Dict with 'is_locator', 'locator_url', 'confidence', 'locator_candidates'
        """
        if not self.llm_analyzer or not self.llm_analyzer.enabled:
            # Fallback to heuristic selection
            if candidates:
                best = candidates[0]
                return {
                    'is_locator': False,
                    'locator_url': best['url'],
                    'confidence': min(0.9, best['score'] / 20),
                    'locator_candidates': [c['url'] for c in candidates[:5]]
                }
            return None

        # Check if current page is already the locator
        current_path = urlparse(base_url).path.lower()
        current_score, _ = self._score_url(base_url)

        if current_score >= 10:
            # Current page looks like a locator, verify with content
            if page_content and self._content_has_locator_signals(page_content):
                return {
                    'is_locator': True,
                    'locator_url': None,
                    'confidence': 0.9,
                    'locator_candidates': [c['url'] for c in candidates[:5]]
                }

        # Prepare candidate list for LLM
        if not candidates:
            return {
                'is_locator': current_score >= 5,
                'locator_url': None,
                'confidence': 0.5,
                'locator_candidates': []
            }

        # Format candidates for LLM
        candidate_list = "\n".join([
            f"- {c['url']} (score: {c['score']})"
            for c in candidates[:15]  # Limit to top 15
        ])

        prompt = f"""You are analyzing a car manufacturer's website to find the "Find a Dealer" or "Dealer Locator" page.

Website Base URL: {base_url}

I have discovered these candidate URLs that might be the dealer locator page:

{candidate_list}

Your task:
1. Analyze the URLs and select the ONE that is most likely to be the dealer locator page
2. The dealer locator is where users enter a zip code to find nearby dealers
3. Look for patterns like /dealer, /dealers, /find-a-dealer, /dealerships, /locations

Return ONLY valid JSON:
{{
  "locator_url": "the best URL from the list",
  "confidence": 0.0-1.0,
  "reasoning": "brief explanation"
}}

Return ONLY the JSON. /no_think"""

        try:
            response = self.llm_analyzer._call_llm(prompt)
            if not response:
                # Fallback to top candidate
                return {
                    'is_locator': False,
                    'locator_url': candidates[0]['url'] if candidates else None,
                    'confidence': 0.6,
                    'locator_candidates': [c['url'] for c in candidates[:5]]
                }

            # Parse LLM response
            result = self.llm_analyzer._parse_llm_response(response)
            if result and result.get('locator_url'):
                return {
                    'is_locator': False,
                    'locator_url': result['locator_url'],
                    'confidence': result.get('confidence', 0.7),
                    'locator_candidates': [c['url'] for c in candidates[:5]]
                }

            # Fallback to top candidate
            return {
                'is_locator': False,
                'locator_url': candidates[0]['url'] if candidates else None,
                'confidence': 0.6,
                'locator_candidates': [c['url'] for c in candidates[:5]]
            }

        except Exception as e:
            print(f"Error in LLM selection: {e}")
            # Fallback to top candidate
            return {
                'is_locator': False,
                'locator_url': candidates[0]['url'] if candidates else None,
                'confidence': 0.5,
                'locator_candidates': [c['url'] for c in candidates[:5]]
            }

    def _content_has_locator_signals(self, content: str) -> bool:
        """
        Check if page content has signals that it's a dealer locator page.

        Args:
            content: Page content (markdown or text)

        Returns:
            True if content suggests this is a locator page
        """
        content_lower = content.lower()

        # Check for zip code input indicators
        zip_signals = ['zip', 'postal', 'enter your location', 'find near']
        has_zip = any(signal in content_lower for signal in zip_signals)

        # Check for dealer-related content
        dealer_signals = ['dealer', 'dealership', 'find a', 'locate']
        has_dealer = any(signal in content_lower for signal in dealer_signals)

        return has_zip and has_dealer

    async def find_dealer_locator(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Main method to find the dealer locator URL for a website.

        Args:
            url: Website URL to analyze

        Returns:
            Dict with 'is_locator', 'locator_url', 'confidence', 'locator_candidates'
        """
        print(f"  Discovering URLs with Crawl4AI...")

        # Step 1: Crawl the page and extract all URLs
        crawl_result = await self.discover_urls(url)

        if not crawl_result['success']:
            print(f"  Warning: Crawl failed - {crawl_result.get('error', 'unknown error')}")
            return None

        internal_links = crawl_result['internal_links']
        print(f"  Found {len(internal_links)} internal links")

        # Step 2: Filter and score candidates
        candidates = self.filter_locator_candidates(internal_links, url)
        print(f"  Identified {len(candidates)} potential locator URLs")

        if candidates:
            # Show top candidates for debugging
            for i, c in enumerate(candidates[:3]):
                print(f"    {i+1}. {c['url']} (score: {c['score']})")

        # Step 3: Use LLM to select the best one
        result = self.select_best_locator_with_llm(
            candidates,
            url,
            crawl_result.get('markdown', '')
        )

        return result


# Sync wrapper for the async function
def find_dealer_locator_sync(
    url: str,
    llm_analyzer=None,
    headless: bool = True
) -> Optional[Dict[str, Any]]:
    """
    Synchronous wrapper for find_dealer_locator.

    Args:
        url: Website URL to analyze
        llm_analyzer: LLMAnalyzer instance
        headless: Whether to run browser in headless mode

    Returns:
        Dict with 'is_locator', 'locator_url', 'confidence', 'locator_candidates'
    """
    discovery = Crawl4AIDiscovery(llm_analyzer=llm_analyzer, headless=headless)
    return asyncio.run(discovery.find_dealer_locator(url))


# Global instance
_crawl4ai_discovery: Optional[Crawl4AIDiscovery] = None


def get_crawl4ai_discovery(llm_analyzer=None, headless: bool = True) -> Crawl4AIDiscovery:
    """Get or create the global Crawl4AI discovery instance."""
    global _crawl4ai_discovery
    if _crawl4ai_discovery is None:
        _crawl4ai_discovery = Crawl4AIDiscovery(llm_analyzer=llm_analyzer, headless=headless)
    return _crawl4ai_discovery
