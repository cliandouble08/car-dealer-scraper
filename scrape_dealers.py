#!/usr/bin/env python3
"""
Generalized Multi-Website Dealer Scraper

Scrapes car dealership information from arbitrary dealer locator websites.
Uses Jina Reader + local LLM (Llama) to analyze site structure,
then Playwright for browser automation.

Usage:
    python scrape_dealers.py --websites websites.txt --zip-codes "02134,10001"
    python scrape_dealers.py --websites websites.txt --zip-file centroid_zip_codes.txt
    python scrape_dealers.py --websites websites.txt --zip-file centroid_zip_codes.txt --workers 4

Website list format (websites.txt):
    https://www.ford.com/dealerships/
    https://www.toyota.com/dealers/
    https://www.honda.com/find-a-dealer
"""

import argparse
import asyncio
import csv
import json
import os
import re
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, urljoin

from config_manager import get_config_manager
from utils.dynamic_config import generate_config_from_analysis
from utils.extraction import (
    clean_name,
    extract_distance,
    extract_phone,
    extract_website_url,
    parse_address,
)
from utils.jina_reader import JinaReader
from utils.llm_analyzer import LLMAnalyzer


@dataclass
class Dealer:
    """Represents a car dealership."""
    source_url: str
    name: str
    address: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""
    phone: str = ""
    website: str = ""
    dealer_type: str = "Standard"
    distance_miles: str = ""
    search_zip: str = ""
    scrape_date: str = ""


class GenericDealerScraper:
    """
    Generic scraper that works with any dealer locator website.
    Uses LLM analysis to understand site structure and Playwright for automation.
    """

    SKIP_NAMES = [
        'search by', 'location', 'name', 'clear', 'advanced search',
        'view map', 'make my dealer', 'chat with dealer', 'dealer website',
        'find more', 'view more', 'load more', 'show more', 'see more',
        'locate dealer', 'find a dealer', 'dealer locator', 'search dealers',
        'zip code', 'use current location', 'update matches',
        'filter by services', 'dealerships found', 'dealers found',
        'available vehicles', 'available dealer services',
        "today's sales hours", 'sales & services hours',
        'view dealer inventory', 'get directions', 'miles away'
    ]

    def __init__(
        self,
        url: str,
        headless: bool = True,
        enable_ai: bool = True
    ):
        """
        Initialize the generic scraper.

        Args:
            url: Dealer locator URL to scrape
            headless: Run browser in headless mode
            enable_ai: Enable AI features (Jina Reader and LLM analysis)
        """
        self.url = url
        self.domain = self._extract_domain(url)
        self.headless = headless
        self.enable_ai = enable_ai
        self.debug = os.getenv("SCRAPER_DEBUG", "false").lower() == "true"
        self.scrape_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.seen_dealers = set()

        # Initialize AI components
        self.jina_reader = JinaReader(enabled=enable_ai)
        self.llm_analyzer = LLMAnalyzer(enabled=enable_ai)

        # Configuration (loaded after analysis)
        self.config_manager = get_config_manager()
        self.config: Dict[str, Any] = {}
        self.selectors: Dict[str, Any] = {}
        self.data_fields: Dict[str, Any] = {}
        self.interactions: Dict[str, Any] = {}

        # Playwright browser/page (initialized in scrape)
        self.browser = None
        self.context = None
        self.page = None

    @staticmethod
    def _extract_domain(url: str) -> str:
        """Extract clean domain from URL."""
        if not url:
            return ""
        parsed = urlparse(url)
        return parsed.netloc.replace('www.', '')

    @staticmethod
    def _is_jina_404_content(content: str) -> bool:
        """Detect Jina Reader 404 content payloads."""
        if not content:
            return False
        content_lower = content.lower()
        return (
            "target url returned error 404" in content_lower
            or "\n404\n" in content_lower
            or "sorry! this page does not exist" in content_lower
        )

    @staticmethod
    def _normalize_locator_path(path: str) -> str:
        """Normalize locator path for deduplication."""
        if not path:
            return ""
        normalized = path.strip().rstrip('/')
        return normalized.lower()

    async def analyze_site(self) -> bool:
        """
        Analyze the website structure using Jina Reader and LLM.

        Returns:
            True if analysis succeeded and config was generated
        """
        if not self.enable_ai:
            print(f"  AI disabled, using default selectors")
            self._load_default_config()
            return False

        # Step 0: Check if config already exists for initial domain
        # Note: We check again after discovery if the domain changes
        if self.config_manager.has_llm_config(self.domain):
            print(f"  Using cached LLM config for {self.domain}")
            self._load_cached_config()

            # Check if we should redirect based on cached config
            cached_base_url = self.config.get('base_url')
            if cached_base_url:
                # If cached URL is a sub-path of current URL (e.g. /dealers vs /), redirect
                # Or if they are different and current is root-ish
                cached_path = urlparse(cached_base_url).path.rstrip('/')
                current_path = urlparse(self.url).path.rstrip('/')
                
                # If cached path is longer/more specific than current path, use it
                if len(cached_path) > len(current_path) and self.domain == self._extract_domain(cached_base_url):
                    print(f"  > Redirecting to known locator URL from cache: {cached_base_url}")
                    self.url = cached_base_url
                    return True

            # If URLs match or no better URL in cache, we assume cache is good for current URL
            return True

        print(f"  Analyzing {self.url} with LLM...")

        # Step 1: Fetch content for initial analysis/discovery
        artifacts = self.jina_reader.save_analysis_artifacts(self.url)
        if not artifacts or not artifacts.get('content'):
            print(f"  Warning: Could not fetch content, using default selectors")
            self._load_default_config()
            return False

        # Step 2: Locator Discovery (Is this the right page?)
        print("  Checking if this is the dealer locator page...")
        discovery_result = self.llm_analyzer.find_dealer_locator_url(
            artifacts['content'],
            self.url
        )

        if discovery_result and not discovery_result.get('is_locator', False):
            locator_path = discovery_result.get('locator_url')
            locator_candidates = discovery_result.get('locator_candidates', [])
            candidate_paths = []
            seen_candidates = set()
            for candidate in [locator_path] + locator_candidates:
                normalized = self._normalize_locator_path(candidate)
                if not normalized or normalized in seen_candidates:
                    continue
                seen_candidates.add(normalized)
                candidate_paths.append(candidate)

            for locator_path in candidate_paths:
                # Construct full URL
                new_url = urljoin(self.url, locator_path)
                print(f"  > Discovery: Redirecting to actual locator: {new_url}")

                # Update scraper state
                self.url = new_url
                self.domain = self._extract_domain(new_url)

                # Check cache for the new domain
                if self.config_manager.has_llm_config(self.domain):
                    print(f"  Using cached LLM config for {self.domain}")
                    self._load_cached_config()
                    return True

                # Re-fetch content for the actual locator page
                print(f"  Fetching content from locator: {self.url}...")
                artifacts = self.jina_reader.save_analysis_artifacts(self.url)
                if not artifacts or not artifacts.get('content'):
                    print(
                        "  Warning: Could not fetch locator content, "
                        "trying next candidate if available"
                    )
                    continue
                if self._is_jina_404_content(artifacts.get('content', '')):
                    print(
                        "  Warning: Locator returned 404 content, "
                        "trying next candidate if available"
                    )
                    artifacts = None
                    continue
                break

            if not artifacts or not artifacts.get('content'):
                print(
                    "  Warning: Could not fetch locator content, "
                    "using default selectors"
                )
                self._load_default_config()
                return False
        else:
             print("  Confirmed: This appears to be the dealer locator page.")

        # Step 3: Analyze page structure with LLM
        analysis_result = self.llm_analyzer.analyze_page_structure(
            artifacts['content'],
            self.url
        )
        if not analysis_result:
            print(f"  Warning: LLM analysis failed, using default selectors")
            self._load_default_config()
            return False

        confidence = analysis_result.get('confidence', 0.0)
        print(f"  LLM analysis complete (confidence: {confidence:.2f})")

        # Step 4: Generate and cache config
        config = generate_config_from_analysis(analysis_result, self.domain, self.url)
        self.config_manager.cache_llm_config(config, self.domain)

        # Step 5: Save analysis summary for troubleshooting
        self._save_analysis_summary(analysis_result, artifacts.get('content_path', ''))

        # Step 6: Load the config
        self._load_cached_config()
        print(f"  LLM-generated config saved for {self.domain}")

        return True

    def _save_analysis_summary(self, analysis_result: Dict[str, Any], content_path: str):
        """
        Save a human-readable summary of the LLM analysis for troubleshooting.

        Args:
            analysis_result: The LLM analysis output
            content_path: Path to the content file
        """
        try:
            # Get the directory from content_path or create one
            if content_path:
                summary_dir = Path(content_path).parent
            else:
                summary_dir = Path("data/analysis") / self.domain
                summary_dir.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            summary_path = summary_dir / f"{timestamp}_analysis_summary.txt"

            with open(summary_path, 'w', encoding='utf-8') as f:
                f.write(f"LLM Analysis Summary for {self.domain}\n")
                f.write(f"{'='*60}\n")
                f.write(f"URL: {self.url}\n")
                f.write(f"Timestamp: {timestamp}\n")
                f.write(f"Confidence: {analysis_result.get('confidence', 0.0):.2f}\n")
                f.write(f"\n{'='*60}\n")
                f.write("SELECTORS IDENTIFIED\n")
                f.write(f"{'='*60}\n\n")

                selectors = analysis_result.get('selectors', {})
                for selector_type, selector_list in selectors.items():
                    f.write(f"{selector_type}:\n")
                    if isinstance(selector_list, list):
                        for s in selector_list:
                            f.write(f"  - {s}\n")
                    else:
                        f.write(f"  {selector_list}\n")
                    f.write("\n")

                f.write(f"{'='*60}\n")
                f.write("DATA FIELDS (for extracting dealer info)\n")
                f.write(f"{'='*60}\n\n")

                data_fields = analysis_result.get('data_fields', {})
                for field_name, field_config in data_fields.items():
                    f.write(f"{field_name}:\n")
                    if isinstance(field_config, dict):
                        for k, v in field_config.items():
                            f.write(f"  {k}: {v}\n")
                    else:
                        f.write(f"  {field_config}\n")
                    f.write("\n")

                f.write(f"{'='*60}\n")
                f.write("INTERACTIONS\n")
                f.write(f"{'='*60}\n\n")

                interactions = analysis_result.get('interactions', {})
                for k, v in interactions.items():
                    f.write(f"{k}: {v}\n")

                f.write(f"\n{'='*60}\n")
                f.write("NOTES\n")
                f.write(f"{'='*60}\n\n")
                f.write(analysis_result.get('notes', 'No additional notes'))
                f.write("\n")

            print(f"  Saved analysis summary to {summary_path}")

        except Exception as e:
            print(f"  Warning: Failed to save analysis summary: {e}")

    def _load_cached_config(self):
        """Load configuration from cache."""
        self.config = self.config_manager.get_config(self.domain)
        self.selectors = self.config.get('selectors', {})
        self.data_fields = self.config.get('data_fields', {})
        self.interactions = self.config.get('interactions', {})

    def _load_default_config(self):
        """Load default configuration."""
        self.config = self.config_manager.get_config('')  # Gets base config
        self.selectors = self.config.get('selectors', {})
        self.data_fields = self.config.get('data_fields', {})
        self.interactions = self.config.get('interactions', {})

    async def scrape(self, zip_codes: List[str]) -> List[Dealer]:
        """
        Scrape dealers for all provided zip codes.

        Args:
            zip_codes: List of zip codes to search

        Returns:
            List of Dealer objects
        """
        # Import playwright here to avoid import errors if not installed
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            print("Error: Playwright not installed. Run: pip install playwright")
            print("Then run: playwright install chromium")
            return []

        all_dealers = []

        # First, analyze the site
        await self.analyze_site()

        async with async_playwright() as p:
            # Launch browser
            self.browser = await p.chromium.launch(
                headless=self.headless,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-http2',  # Avoid HTTP2 protocol errors
                ]
            )

            await self._create_new_context()

            try:
                consecutive_errors = 0
                max_consecutive_errors = 5

                for i, zip_code in enumerate(zip_codes):
                    print(f"[{i+1}/{len(zip_codes)}] Scraping {self.domain} for {zip_code}...")

                    try:
                        dealers = await self._scrape_zip(zip_code)
                        all_dealers.extend(dealers)
                        print(f"  Found {len(dealers)} dealers")
                        consecutive_errors = 0  # Reset on success

                    except Exception as e:
                        error_msg = str(e)
                        print(f"  Error scraping {zip_code}: {error_msg}")
                        consecutive_errors += 1

                        # If we hit HTTP2/connection errors, recreate context
                        if 'ERR_HTTP2' in error_msg or 'net::' in error_msg:
                            print(f"  Connection error detected, recreating browser context...")
                            await self._recreate_context()
                            await asyncio.sleep(3)  # Extra delay after recreating

                        # If too many consecutive errors, take a longer break
                        if consecutive_errors >= max_consecutive_errors:
                            print(f"  Too many consecutive errors, taking a 30s break...")
                            await self._recreate_context()
                            await asyncio.sleep(30)
                            consecutive_errors = 0

                        continue

                    # Delay between requests (longer to avoid rate limiting)
                    delay = self.interactions.get('wait_after_search', 2)
                    await asyncio.sleep(max(delay, 2))

                    # Recreate context every 50 requests to avoid stale connections
                    if (i + 1) % 50 == 0:
                        print(f"  Refreshing browser context after {i+1} requests...")
                        await self._recreate_context()

            finally:
                await self.browser.close()

        return all_dealers

    async def _create_new_context(self):
        """Create a new browser context and page."""
        self.context = await self.browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent=(
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            )
        )
        self.page = await self.context.new_page()

    async def _recreate_context(self):
        """Close current context and create a new one."""
        try:
            if self.context:
                await self.context.close()
        except Exception:
            pass
        await self._create_new_context()

        return all_dealers

    async def _scrape_zip(self, zip_code: str) -> List[Dealer]:
        """
        Scrape dealers for a single zip code.

        Args:
            zip_code: Zip code to search

        Returns:
            List of Dealer objects
        """
        dealers = []

        # Get timing config
        wait_after_page_load = self.interactions.get('wait_after_page_load', 3)
        wait_after_search = self.interactions.get('wait_after_search', 4)
        click_delay = self.interactions.get('click_delay', 0.3)

        # Navigate to page with retry logic
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Use 'domcontentloaded' instead of 'networkidle' for faster loading
                await self.page.goto(self.url, wait_until='domcontentloaded', timeout=60000)
                await asyncio.sleep(wait_after_page_load)
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"  Retry {attempt + 1}/{max_retries} after error: {e}")
                    await asyncio.sleep(2)
                    continue
                print(f"  Error loading page: {e}")
                return dealers

        # Handle cookie popup
        await self._handle_cookie_popup()

        # Handle location modal/popup if present (e.g., Acura prompt)
        await self._handle_location_prompt(zip_code)

        # Optional debug: log candidate inputs and frames
        if self.debug:
            await self._debug_log_inputs()

        # Find and fill search input
        search_input = await self._find_search_input()
        if not search_input:
            print(f"  Could not find search input")
            return dealers

        try:
            await search_input.click()
            await search_input.fill('')  # Clear
            await asyncio.sleep(click_delay)
            await search_input.fill(zip_code)
            await asyncio.sleep(click_delay)
            await self._select_zip_suggestion(search_input, zip_code)

            # Execute search sequence
            search_sequence = self.interactions.get('search_sequence', ['fill_input', 'press_enter'])
            if 'click_search' in search_sequence:
                search_button = await self._find_search_button()
                if search_button:
                    await search_button.click()
                else:
                    await search_input.press('Enter')
            else:
                await search_input.press('Enter')

            await asyncio.sleep(wait_after_search)

        except Exception as e:
            print(f"  Error interacting with search: {e}")
            return dealers

        # Handle "Apply" button if present
        await self._handle_apply_button()

        # Wait for dealer cards
        try:
            await self.page.wait_for_selector(
                self._get_dealer_card_selector(),
                timeout=10000
            )
        except Exception:
            print(f"  Warning: No dealer cards found initially")
            if await self._handle_search_this_area_button():
                try:
                    await self.page.wait_for_selector(
                        self._get_dealer_card_selector(),
                        timeout=10000
                    )
                except Exception:
                    print(f"  Warning: No dealer cards found after map search")

        # Expand results (View More / scroll)
        await self._expand_results()

        # Extract dealers
        dealers = await self._extract_dealers(zip_code)

        return dealers

    async def _handle_cookie_popup(self):
        """Handle common cookie consent popups."""
        cookie_selectors = [
            '#onetrust-accept-btn-handler',
            '[id*="cookie"] button',
            '[class*="cookie"] button',
            'button:has-text("Accept")',
            'button:has-text("Accept All")',
        ]
        for selector in cookie_selectors:
            try:
                btn = await self.page.query_selector(selector)
                if btn and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(0.5)
                    return
            except Exception:
                continue

    async def _handle_search_this_area_button(self) -> bool:
        """Click a map-based 'Search This Area' button if present."""
        button_selectors = [
            "button:has-text('Search This Area')",
            "button:has-text('Search this area')",
            "button[aria-label*='search this area' i]",
            "button[title*='search this area' i]",
        ]
        try:
            button = await self._find_visible_element(button_selectors)
            if button:
                await button.click()
                await asyncio.sleep(self.interactions.get('wait_after_search', 2))
                return True
        except Exception:
            return False
        return False

    async def _handle_location_prompt(self, zip_code: str) -> bool:
        """Handle location modal that requires zip input before results load."""
        dialog = await self._find_visible_dialog()
        if not dialog:
            return False

        input_selectors = [
            "input[placeholder*='ZIP' i]",
            "input[placeholder*='zip' i]",
            "input[aria-label*='ZIP' i]",
            "input[name*='zip' i]",
            "input[id*='zip' i]",
        ]
        modal_input = await self._find_visible_element(input_selectors, root=dialog)
        if not modal_input:
            return False

        try:
            await modal_input.click()
            await modal_input.fill('')
            await asyncio.sleep(0.2)
            await modal_input.fill(zip_code)
            await asyncio.sleep(0.2)
            await self._select_zip_suggestion(modal_input, zip_code, root=dialog)

            # Try submit via Enter first
            try:
                await modal_input.press('Enter')
            except Exception:
                pass

            # Try an explicit search button if present
            button_selectors = [
                "button[type='submit']",
                "button:has-text('Search')",
                "button:has-text('Find')",
                "button[aria-label*='search' i]",
                "button[title*='search' i]",
            ]
            modal_button = await self._find_visible_element(button_selectors, root=dialog)
            if modal_button:
                await modal_button.click()

            await asyncio.sleep(self.interactions.get('wait_after_search', 2))
            return True
        except Exception:
            return False

    async def _select_zip_suggestion(self, input_element, zip_code: str, root=None) -> bool:
        """Select a suggested zip option if a dropdown appears."""
        suggestion_wait = self.interactions.get('suggestion_wait', 0.8)
        max_attempts = self.interactions.get('suggestion_attempts', 2)
        container_selectors = [
            "[role='listbox']",
            ".pac-container",
            ".ui-menu",
            ".autocomplete-suggestions",
            ".suggestions",
            "[class*='suggest']",
            "[id*='suggest']",
            "[class*='autocomplete']",
            "[class*='typeahead']",
        ]
        option_selectors = [
            "[role='option']",
            "li[role='option']",
            "li[role='menuitem']",
            ".pac-item",
            ".ui-menu-item",
            ".ui-menu-item-wrapper",
            ".autocomplete-suggestion",
            ".suggestion",
            "li",
        ]

        for _ in range(max_attempts):
            container = await self._find_visible_element(container_selectors, root=root)
            if not container and root is not None:
                container = await self._find_visible_element(container_selectors)

            if container:
                option = await self._find_visible_suggestion_option(
                    container,
                    option_selectors,
                    zip_code=zip_code
                )
                if not option:
                    option = await self._find_visible_suggestion_option(
                        container,
                        option_selectors
                    )
                if option:
                    try:
                        await option.click()
                        await asyncio.sleep(0.2)
                        return True
                    except Exception:
                        pass

                try:
                    await input_element.press('ArrowDown')
                    await asyncio.sleep(0.1)
                    await input_element.press('Enter')
                    await asyncio.sleep(0.2)
                    return True
                except Exception:
                    pass

            await asyncio.sleep(suggestion_wait)

        return False

    async def _find_visible_suggestion_option(self, container, selectors, zip_code: str = ""):
        """Find a visible suggestion option inside a container."""
        zip_code_lower = zip_code.lower()
        for selector in selectors:
            try:
                elements = await container.query_selector_all(selector)
                for element in elements:
                    if not await element.is_visible():
                        continue
                    if zip_code_lower:
                        try:
                            text = (await element.inner_text()).strip().lower()
                        except Exception:
                            text = ""
                        if text and zip_code_lower in text:
                            return element
                    else:
                        return element
            except Exception:
                continue
        return None

    async def _find_visible_dialog(self):
        """Find a visible modal/dialog container."""
        dialog_selectors = [
            "[role='dialog']",
            "[aria-modal='true']",
            ".modal",
            "[class*='modal']",
            "[class*='popup']",
        ]
        for selector in dialog_selectors:
            try:
                elements = await self.page.query_selector_all(selector)
                for element in elements:
                    if await element.is_visible():
                        return element
            except Exception:
                continue
        return None

    async def _find_visible_element(self, selectors, root=None):
        """Find the first visible element matching any selector."""
        search_root = root or self.page
        for selector in selectors:
            try:
                elements = await search_root.query_selector_all(selector)
                for element in elements:
                    if await element.is_visible():
                        return element
            except Exception:
                continue

        if root is None:
            element = await self._find_visible_element_in_frames(selectors)
            if element:
                return element
            return await self._find_visible_element_in_shadow_dom(selectors)
        return None

    async def _find_visible_element_in_frames(self, selectors):
        """Find the first visible element matching selectors in nested frames."""
        try:
            frames = self.page.frames
        except Exception:
            return None

        for frame in frames:
            if frame == self.page.main_frame:
                continue
            for selector in selectors:
                try:
                    elements = await frame.query_selector_all(selector)
                    for element in elements:
                        if await element.is_visible():
                            return element
                except Exception:
                    continue
        return None

    async def _find_visible_element_in_shadow_dom(self, selectors):
        """Find the first visible element matching selectors in shadow DOM."""
        script = """
        (selectors) => {
            function isVisible(el) {
                if (!el || !el.getBoundingClientRect) {
                    return false;
                }
                const style = window.getComputedStyle(el);
                if (!style || style.display === 'none' || style.visibility === 'hidden') {
                    return false;
                }
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            }

            const roots = [document];
            while (roots.length) {
                const root = roots.shift();
                if (!root || !root.querySelectorAll) {
                    continue;
                }
                for (const selector of selectors) {
                    const matches = root.querySelectorAll(selector);
                    for (const el of matches) {
                        if (isVisible(el)) {
                            return el;
                        }
                    }
                }
                const all = root.querySelectorAll('*');
                for (const el of all) {
                    if (el.shadowRoot) {
                        roots.push(el.shadowRoot);
                    }
                }
            }
            return null;
        }
        """
        for frame in self.page.frames:
            try:
                handle = await frame.evaluate_handle(script, selectors)
                element = handle.as_element()
                if element:
                    return element
            except Exception:
                continue
        return None

    async def _debug_log_inputs(self):
        """Log candidate input elements and frame URLs for debugging."""
        selectors = self.selectors.get('search_input', [])
        fallbacks = [
            "input[placeholder*='Zip' i]",
            "input[placeholder*='zip' i]",
            "input[placeholder*='City' i]",
            "input[placeholder*='Location' i]",
            "input[aria-label*='Zip' i]",
            "input[type='search']",
            "input[name*='zip' i]",
            "input[id*='zip' i]",
        ]
        all_selectors = selectors + fallbacks

        print("  [debug] Searching for input candidates...")
        await self._debug_log_inputs_in_frame(self.page.main_frame, all_selectors)

        for frame in self.page.frames:
            if frame == self.page.main_frame:
                continue
            await self._debug_log_inputs_in_frame(frame, all_selectors)

    async def _debug_log_inputs_in_frame(self, frame, selectors):
        """Log candidate inputs in a specific frame."""
        try:
            frame_url = frame.url
        except Exception:
            frame_url = "<unknown>"

        candidates = []
        for selector in selectors:
            try:
                elements = await frame.query_selector_all(selector)
                for element in elements:
                    try:
                        if not await element.is_visible():
                            continue
                        attrs = {
                            "id": await element.get_attribute("id"),
                            "name": await element.get_attribute("name"),
                            "placeholder": await element.get_attribute("placeholder"),
                            "type": await element.get_attribute("type"),
                        }
                        candidates.append((selector, attrs))
                    except Exception:
                        continue
            except Exception:
                continue

        if candidates:
            print(f"  [debug] Frame: {frame_url}")
            for selector, attrs in candidates[:10]:
                print(f"  [debug] selector={selector} attrs={attrs}")

    async def _find_search_input(self):
        """Find the search input field."""
        selectors = self.selectors.get('search_input', [])

        # Add common fallbacks
        fallbacks = [
            "input[placeholder*='Zip' i]",
            "input[placeholder*='zip' i]",
            "input[placeholder*='City' i]",
            "input[placeholder*='Location' i]",
            "input[aria-label*='Zip' i]",
            "input[type='search']",
            "input[name*='zip' i]",
            "input[id*='zip' i]",
        ]

        all_selectors = selectors + fallbacks

        element = await self._find_visible_element(all_selectors)
        if element:
            return element

        return None

    async def _find_search_button(self):
        """Find the search/submit button."""
        selectors = self.selectors.get('search_button', [])

        fallbacks = [
            "button[type='submit']",
            "button:has-text('Search')",
            "button:has-text('Find')",
            "button:has-text('Go')",
            "input[type='submit']",
        ]

        all_selectors = selectors + fallbacks

        element = await self._find_visible_element(all_selectors)
        if element:
            return element

        return None

    async def _handle_apply_button(self):
        """Handle apply/filter button if present."""
        selectors = self.selectors.get('apply_button', [])

        fallbacks = [
            "button:has-text('Apply')",
            "button:has-text('Filter')",
            "button:has-text('Show Results')",
        ]

        all_selectors = selectors + fallbacks
        wait_after_apply = self.interactions.get('wait_after_apply', 2)

        for selector in all_selectors:
            try:
                element = await self.page.query_selector(selector)
                if element and await element.is_visible():
                    await element.click()
                    await asyncio.sleep(wait_after_apply)
                    return True
            except Exception:
                continue

        return False

    def _get_dealer_card_selector(self) -> str:
        """Get the primary selector for dealer cards."""
        selectors = self.selectors.get('dealer_cards', [])
        if selectors:
            return selectors[0]
        return "div[class*='dealer'], li[class*='dealer'], article[class*='result']"

    async def _expand_results(self):
        """Expand results by clicking View More or scrolling."""
        pagination_type = self.interactions.get('pagination_type', 'view_more')
        view_more_delay = self.interactions.get('view_more_delay', 2)
        scroll_delay = self.interactions.get('scroll_delay', 0.5)

        if pagination_type == 'view_more':
            # Click "View More" until exhausted
            max_clicks = 30
            for _ in range(max_clicks):
                view_more_btn = await self._find_view_more_button()
                if not view_more_btn:
                    break

                try:
                    await view_more_btn.scroll_into_view_if_needed()
                    await asyncio.sleep(0.2)
                    await view_more_btn.click()
                    await asyncio.sleep(view_more_delay)
                except Exception:
                    break

        elif pagination_type == 'scroll':
            # Scroll to load more
            last_count = 0
            stable_checks = 0
            max_scrolls = 20

            for _ in range(max_scrolls):
                await self.page.evaluate('window.scrollBy(0, window.innerHeight * 0.8)')
                await asyncio.sleep(scroll_delay)

                cards = await self.page.query_selector_all(self._get_dealer_card_selector())
                current_count = len(cards)

                if current_count == last_count:
                    stable_checks += 1
                    if stable_checks >= 3:
                        break
                else:
                    stable_checks = 0
                    last_count = current_count

    async def _find_view_more_button(self):
        """Find View More / Load More button."""
        selectors = self.selectors.get('view_more_button', [])

        fallbacks = [
            "button:has-text('View More')",
            "button:has-text('Load More')",
            "button:has-text('Show More')",
            "button:has-text('See More')",
            "a:has-text('View More')",
            "a:has-text('Load More')",
            "[class*='view-more']",
            "[class*='load-more']",
        ]

        all_selectors = selectors + fallbacks

        for selector in all_selectors:
            try:
                element = await self.page.query_selector(selector)
                if element and await element.is_visible():
                    return element
            except Exception:
                continue

        return None

    async def _extract_dealers(self, zip_code: str) -> List[Dealer]:
        """
        Extract dealer information from the page.

        Args:
            zip_code: Search zip code

        Returns:
            List of Dealer objects
        """
        dealers = []
        seen_keys = set()

        # Get all dealer cards (try all selectors, then frames if needed)
        selectors = self.selectors.get('dealer_cards', [])
        if not selectors:
            selectors = [
                "div[class*='dealer']",
                "li[class*='dealer']",
                "article[class*='result']",
            ]

        cards = []
        for selector in selectors:
            try:
                cards.extend(await self.page.query_selector_all(selector))
            except Exception:
                continue

        if not cards:
            cards = await self._query_selector_all_in_frames(selectors)

        print(f"  Processing {len(cards)} dealer cards...")

        for card in cards:
            try:
                dealer = await self._extract_dealer_from_card(card, zip_code)
                if dealer:
                    # Deduplication
                    dedupe_key = f"{dealer.name.lower()}|{dealer.address.lower()}"
                    if dedupe_key not in seen_keys:
                        seen_keys.add(dedupe_key)
                        dealers.append(dealer)
            except Exception:
                continue

        return dealers

    async def _query_selector_all_in_frames(self, selectors):
        """Query selectors across nested frames."""
        results = []
        try:
            frames = self.page.frames
        except Exception:
            return results

        for frame in frames:
            if frame == self.page.main_frame:
                continue
            for selector in selectors:
                try:
                    elements = await frame.query_selector_all(selector)
                    for element in elements:
                        try:
                            if await element.is_visible():
                                results.append(element)
                        except Exception:
                            continue
                except Exception:
                    continue
        return results

    async def _extract_dealer_from_card(self, card, zip_code: str) -> Optional[Dealer]:
        """
        Extract dealer info from a single card element.

        Args:
            card: Playwright element handle for dealer card
            zip_code: Search zip code

        Returns:
            Dealer object or None
        """
        try:
            is_visible = await card.is_visible()
            if not is_visible:
                return None
        except Exception:
            return None

        # Get card text for fallback extraction
        try:
            card_text = await card.inner_text()
        except Exception:
            return None

        if not card_text or not card_text.strip():
            return None

        # Extract name
        name = await self._extract_field_from_card(card, 'name', card_text)
        if not name:
            return None

        # Clean name
        name = clean_name(name, self.SKIP_NAMES)
        if not name:
            return None

        # Extract address
        address_text = await self._extract_field_from_card(card, 'address', card_text)
        full_address, city, state, zip_code_found = "", "", "", ""
        if address_text:
            full_address, city, state, zip_code_found = parse_address(address_text)

        # Extract phone
        phone = await self._extract_field_from_card(card, 'phone', card_text)
        if not phone:
            # Fallback: extract from text
            phone = extract_phone(card_text, [])
        # Clean phone number (remove tel:// prefix)
        if phone:
            phone = phone.replace('tel://', '').replace('tel:', '').strip()

        # Extract website
        website = await self._extract_field_from_card(card, 'website', card_text)
        if not website:
            # Fallback: find links
            try:
                links = await card.query_selector_all('a[href]')
                link_elements = []
                for link in links:
                    href = await link.get_attribute('href')
                    if href:
                        link_elements.append(type('obj', (object,), {'get_attribute': lambda s, h=href: h})())
                website = extract_website_url(card_text, link_elements, [])
            except Exception:
                pass

        # Extract distance
        distance = extract_distance(card_text)

        # Skip cards that don't look like dealer entries
        has_address = bool(full_address or zip_code_found or (city and state))
        if not has_address and not phone and not website:
            return None

        # Dealer type
        text_lower = card_text.lower()
        types = []
        if 'elite' in text_lower:
            types.append('Elite')
        if 'certified' in text_lower:
            types.append('Certified')
        if 'ev certified' in text_lower or 'ev-certified' in text_lower:
            types.append('EV Certified')

        return Dealer(
            source_url=self.url,
            name=name,
            address=full_address,
            city=city,
            state=state,
            zip_code=zip_code_found,
            phone=phone or "",
            website=website or "",
            dealer_type=', '.join(types) if types else 'Standard',
            distance_miles=distance,
            search_zip=zip_code,
            scrape_date=self.scrape_date,
        )

    async def _extract_field_from_card(
        self,
        card,
        field_name: str,
        card_text: str
    ) -> Optional[str]:
        """
        Extract a specific field from a dealer card.

        Args:
            card: Playwright element handle
            field_name: Field name (name, address, phone, website)
            card_text: Fallback text content

        Returns:
            Extracted value or None
        """
        field_config = self.data_fields.get(field_name, {})
        selector = field_config.get('selector')
        field_type = field_config.get('type', 'text')
        attribute = field_config.get('attribute', 'href')
        fallback_patterns = field_config.get('fallback_patterns', [])

        # Try main selector
        if selector:
            try:
                element = await card.query_selector(selector)
                if element:
                    if field_type == 'href':
                        value = await element.get_attribute(attribute)
                    else:
                        value = await element.inner_text()
                    if value:
                        return value.strip()
            except Exception:
                pass

        # Try fallback patterns
        for pattern in fallback_patterns:
            try:
                element = await card.query_selector(pattern)
                if element:
                    if field_type == 'href':
                        value = await element.get_attribute(attribute)
                    else:
                        value = await element.inner_text()
                    if value:
                        return value.strip()
            except Exception:
                continue

        # Field-specific fallbacks from text
        if field_name == 'name':
            lines = [l.strip() for l in card_text.split('\n') if l.strip()]
            for line in lines:
                # Skip obvious non-names
                if any(skip in line.lower() for skip in self.SKIP_NAMES):
                    continue
                if len(line) > 3 and len(line) < 100:
                    return line

        elif field_name == 'phone':
            return extract_phone(card_text, [])

        elif field_name == 'address':
            # Look for lines with zip code pattern
            lines = card_text.split('\n')
            for line in lines:
                if re.search(r'\d{5}', line):
                    return line.strip()

        return None


def load_websites(websites_file: str) -> List[str]:
    """Load website URLs from a text file."""
    urls = []

    if not os.path.exists(websites_file):
        print(f"Error: Website file not found: {websites_file}")
        return urls

    with open(websites_file, 'r') as f:
        for line in f:
            line = line.strip()
            # Skip empty lines and comments
            if not line or line.startswith('#'):
                continue
            # Strip inline comments
            if '#' in line:
                line = line.split('#')[0].strip()
            if line and line.startswith(('http://', 'https://')):
                urls.append(line)

    return urls


def load_zip_codes(zip_codes_arg: str, zip_file: str) -> List[str]:
    """Load zip codes from arguments or file."""
    codes = []

    if zip_codes_arg:
        codes = [z.strip() for z in zip_codes_arg.split(",") if z.strip()]

    if zip_file and os.path.exists(zip_file):
        with open(zip_file, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '#' in line:
                    line = line.split('#')[0].strip()
                if line and line not in codes:
                    codes.append(line)

    return codes if codes else ["10001"]


def save_results(dealers: List[Dealer], output_dir: str, domain: str):
    """Save dealers to CSV and JSON files."""
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Clean domain for filename
    clean_domain = domain.replace('.', '_')

    # CSV
    csv_path = os.path.join(output_dir, f"{clean_domain}_dealers_{timestamp}.csv")
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        if dealers:
            writer = csv.DictWriter(f, fieldnames=asdict(dealers[0]).keys())
            writer.writeheader()
            for d in dealers:
                writer.writerow(asdict(d))
    print(f"Saved CSV: {csv_path}")

    # JSON
    json_path = os.path.join(output_dir, f"{clean_domain}_dealers_{timestamp}.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump([asdict(d) for d in dealers], f, indent=2)
    print(f"Saved JSON: {json_path}")


async def scrape_website(
    url: str,
    zip_codes: List[str],
    headless: bool = True,
    enable_ai: bool = True
) -> List[Dealer]:
    """
    Scrape a single website for dealers.

    Args:
        url: Dealer locator URL
        zip_codes: List of zip codes
        headless: Run browser in headless mode
        enable_ai: Enable AI features

    Returns:
        List of Dealer objects
    """
    scraper = GenericDealerScraper(url, headless=headless, enable_ai=enable_ai)
    return await scraper.scrape(zip_codes)


def _worker_scrape(args: Tuple[str, List[str], bool, bool]) -> List[Dict]:
    """
    Worker function for parallel scraping.

    Args:
        args: Tuple of (url, zip_codes, headless, enable_ai)

    Returns:
        List of dealer dictionaries
    """
    url, zip_codes, headless, enable_ai = args

    # Run async scraper in sync context
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        dealers = loop.run_until_complete(
            scrape_website(url, zip_codes, headless, enable_ai)
        )
        return [asdict(d) for d in dealers]
    except Exception as e:
        print(f"Worker error for {url}: {e}")
        return []
    finally:
        loop.close()


def scrape_parallel(
    url: str,
    zip_codes: List[str],
    headless: bool = True,
    workers: int = 4,
    enable_ai: bool = True
) -> List[Dealer]:
    """
    Scrape dealers using multiple parallel processes.

    Args:
        url: Dealer locator URL
        zip_codes: List of zip codes
        headless: Run in headless mode
        workers: Number of parallel workers
        enable_ai: Enable AI features

    Returns:
        List of deduplicated Dealer objects
    """
    workers = min(workers, len(zip_codes), 8)

    if workers <= 1:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(
                scrape_website(url, zip_codes, headless, enable_ai)
            )
        finally:
            loop.close()

    # Split zip codes among workers
    chunks = [[] for _ in range(workers)]
    for i, zc in enumerate(zip_codes):
        chunks[i % workers].append(zc)

    chunks = [c for c in chunks if c]
    actual_workers = len(chunks)

    print(f"\nStarting {actual_workers} parallel workers...")
    print(f"Distributing {len(zip_codes)} zip codes across workers")

    worker_args = [
        (url, chunk, headless, enable_ai)
        for chunk in chunks
    ]

    all_dealer_dicts = []
    with ProcessPoolExecutor(max_workers=actual_workers) as executor:
        futures = {executor.submit(_worker_scrape, args): i for i, args in enumerate(worker_args)}

        for future in as_completed(futures):
            worker_id = futures[future]
            try:
                dealer_dicts = future.result()
                all_dealer_dicts.extend(dealer_dicts)
                print(f"[Worker {worker_id + 1}] Completed with {len(dealer_dicts)} dealers")
            except Exception as e:
                print(f"[Worker {worker_id + 1}] Failed: {e}")

    # Deduplicate
    seen = set()
    dealers = []
    for d in all_dealer_dicts:
        key = f"{d['name'].lower()}|{d['address'].lower()}"
        if key not in seen:
            seen.add(key)
            dealers.append(Dealer(**d))

    print(f"\nTotal unique dealers after deduplication: {len(dealers)}")
    return dealers


async def main_async():
    """Async main function."""
    parser = argparse.ArgumentParser(
        description="Scrape car dealership information from multiple websites"
    )
    parser.add_argument(
        "--websites",
        type=str,
        required=True,
        help="Text file with website URLs (one per line)"
    )
    parser.add_argument(
        "--zip-codes",
        type=str,
        help="Comma-separated zip codes"
    )
    parser.add_argument(
        "--zip-file",
        type=str,
        help="File with zip codes (one per line)"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="output",
        help="Output directory"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=True,
        help="Run browser in headless mode (default)"
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Run browser with visible window"
    )
    parser.add_argument(
        "--workers", "-w",
        type=int,
        default=1,
        help="Number of parallel workers per website (default: 1)"
    )
    parser.add_argument(
        "--enable-ai",
        action="store_true",
        default=True,
        help="Enable AI features (Jina Reader + LLM analysis)"
    )
    parser.add_argument(
        "--disable-ai",
        action="store_true",
        help="Disable AI features, use default selectors"
    )
    parser.add_argument(
        "--list-websites",
        action="store_true",
        help="List websites from the file and exit"
    )

    args = parser.parse_args()

    # Load websites
    websites = load_websites(args.websites)
    if not websites:
        print("No valid websites found in the file")
        return

    if args.list_websites:
        print("\nWebsites to scrape:")
        for url in websites:
            print(f"  - {url}")
        return

    # Configuration
    headless = not args.no_headless
    workers = max(1, args.workers)
    enable_ai = args.enable_ai and not args.disable_ai

    if enable_ai:
        print("AI features enabled - using Jina Reader and LLM analysis")
    else:
        print("AI features disabled - using default selectors")

    # Load zip codes
    zip_codes = load_zip_codes(args.zip_codes, args.zip_file)
    print(f"Loaded {len(zip_codes)} zip codes")
    print(f"Loaded {len(websites)} websites to scrape")

    # Scrape each website
    all_dealers = []
    for i, url in enumerate(websites):
        domain = GenericDealerScraper._extract_domain(url)
        print(f"\n{'='*60}")
        print(f"[{i+1}/{len(websites)}] Scraping {domain}...")
        print(f"URL: {url}")
        if workers > 1:
            print(f"Using {workers} parallel workers")
        print(f"{'='*60}")

        if workers > 1:
            dealers = scrape_parallel(
                url, zip_codes,
                headless=headless,
                workers=workers,
                enable_ai=enable_ai
            )
        else:
            dealers = await scrape_website(
                url, zip_codes,
                headless=headless,
                enable_ai=enable_ai
            )

        if dealers:
            print(f"\nTotal {domain} dealers found: {len(dealers)}")
            save_results(dealers, args.output_dir, domain)
            all_dealers.extend(dealers)
        else:
            print(f"\nNo dealers found for {domain}")

    print(f"\n{'='*60}")
    print(f"COMPLETE: Found {len(all_dealers)} dealers across all websites")
    print(f"{'='*60}")


def main():
    """Synchronous main entry point."""
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
