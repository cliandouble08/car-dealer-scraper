#!/usr/bin/env python3
"""
Multi-Brand Dealer Scraper

Standalone script for scraping car dealership information from multiple brands.
Uses Selenium for JS-heavy sites, direct HTTP requests for API-based sites.
Supports parallel execution with multiple browser instances.

Usage:
    python scrape_dealers.py --brand ford --zip-codes "02134,10001"
    python scrape_dealers.py --brand ford --zip-file sample_zip_codes.txt
    python scrape_dealers.py --brand ford --zip-file centroid_zip_codes.txt --workers 4
    python scrape_dealers.py --brand all --zip-codes "10001"

Parallel execution:
    Use --workers N to run N browser instances in parallel (4-8 recommended).
    Each worker handles a subset of zip codes concurrently.
"""

import argparse
import time
import re
import json
import csv
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, asdict

import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.remote.webelement import WebElement
from webdriver_manager.chrome import ChromeDriverManager

from config_manager import get_config_manager
from utils.extraction import (
    extract_phone, parse_address, extract_website_url,
    clean_name, extract_distance
)
from utils.jina_reader import get_jina_reader
from utils.llm_analyzer import get_llm_analyzer
from utils.dynamic_config import generate_config_from_analysis


@dataclass
class Dealer:
    """Represents a car dealership."""
    brand: str
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


class BaseScraper:
    """Base class for dealer scrapers with auto-detection capabilities."""

    SKIP_NAMES = [
        'search by', 'location', 'name', 'clear', 'advanced search',
        'view map', 'make my dealer', 'chat with dealer', 'dealer website',
        'find more', 'view more', 'load more', 'show more', 'see more'
    ]

    def __init__(self, headless: bool = True, brand: str = "", enable_ai: bool = False):
        """
        Initialize the scraper.

        Args:
            headless: Run browser in headless mode
            brand: Manufacturer brand name (for config loading)
            enable_ai: Enable AI features (Jina Reader and LLM analysis)
        """
        self.headless = headless
        self.brand = brand.lower() if brand else ""
        self.enable_ai = enable_ai
        self.scrape_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.seen_dealers = set()
        self.config_manager = get_config_manager()
        self.config = self.config_manager.get_config(self.brand) if self.brand else {}
        self.interaction_config = self.config_manager.get_interaction_config(self.brand)
        self.extraction_config = self.config_manager.get_extraction_config(self.brand)
        # Initialize AI components with enable_ai flag
        # Create instances and set enabled based on flag (respecting env vars too)
        from utils.jina_reader import JinaReader
        from utils.llm_analyzer import LLMAnalyzer
        self.jina_reader = JinaReader(enabled=enable_ai)
        self.llm_analyzer = LLMAnalyzer(enabled=enable_ai)

    def scrape(self, zip_codes: List[str]) -> List[Dealer]:
        raise NotImplementedError

    def _is_valid_name(self, name: str) -> bool:
        """Check if a name is valid (not a skip pattern)."""
        cleaned = clean_name(name, self.SKIP_NAMES)
        return cleaned is not None

    def _auto_detect_search_input(self, driver: webdriver.Chrome) -> Optional[WebElement]:
        """
        Auto-detect search input field using multiple strategies.

        Args:
            driver: Selenium WebDriver instance

        Returns:
            WebElement if found, None otherwise
        """
        # Get selectors from config or use defaults
        selectors = self.config.get('selectors', {}).get('search_input', [])
        
        # Add common fallback selectors if not in config
        if not selectors:
            selectors = [
                "input[placeholder*='Zip']", "input[placeholder*='zip']",
                "input[placeholder*='City']", "input[placeholder*='city']",
                "input[placeholder*='Location']", "input[placeholder*='location']",
                "input[aria-label*='Zip']", "input[aria-label*='zip']",
                "input[aria-label*='City']", "input[aria-label*='city']",
                "input[type='search']", "input[name*='zip']", "input[name*='city']",
                "input[id*='zip']", "input[id*='city']", "input[class*='zip']",
                "input[class*='search']"
            ]

        for selector in selectors:
            try:
                # Handle :contains() pseudo-selector (not valid CSS)
                if ":contains(" in selector:
                    text_match = re.search(r":contains\('([^']+)'\)", selector)
                    if text_match:
                        text = text_match.group(1)
                        tag = selector.split(":")[0] if ":" in selector else "*"
                        xpath = (
                            f"//{tag}[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{text.lower()}')]"
                        )
                        elements = driver.find_elements(By.XPATH, xpath)
                    else:
                        continue
                else:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)

                for elem in elements:
                    try:
                        if elem.is_displayed() and elem.is_enabled():
                            return elem
                    except Exception:
                        continue
            except Exception:
                continue

        return None

    def _auto_detect_apply_button(self, driver: webdriver.Chrome) -> Optional[WebElement]:
        """
        Auto-detect apply/search button for advanced filter pages.

        Args:
            driver: Selenium WebDriver instance

        Returns:
            WebElement if found, None otherwise
        """
        selectors = self.config.get('selectors', {}).get('apply_button', [])
        button_texts = ["apply", "search", "find", "show results", "view results"]

        for selector in selectors:
            try:
                if ":contains(" in selector:
                    text_match = re.search(r":contains\('([^']+)'\)", selector)
                    if text_match:
                        text = text_match.group(1)
                        xpath = (
                            f"//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{text.lower()}')]"
                            f" | //input[@type='submit' and contains(translate(@value, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{text.lower()}')]"
                            f" | //a[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{text.lower()}')]"
                        )
                        elements = driver.find_elements(By.XPATH, xpath)
                    else:
                        continue
                else:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)

                for elem in elements:
                    try:
                        if elem.is_displayed() and elem.is_enabled():
                            return elem
                    except Exception:
                        continue
            except Exception:
                continue

        # Fallback: search all buttons by text/value
        try:
            buttons = driver.find_elements(By.TAG_NAME, "button")
            inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='submit']")
            for elem in buttons + inputs:
                try:
                    text = (elem.text or elem.get_attribute('value') or "").lower()
                    if any(btn_text in text for btn_text in button_texts):
                        if elem.is_displayed() and elem.is_enabled():
                            return elem
                except Exception:
                    continue
        except Exception:
            pass

        return None

    def _auto_detect_view_more_button(self, driver: webdriver.Chrome) -> Optional[WebElement]:
        """
        Auto-detect "View More" / "Load More" button with multiple text variations.

        Args:
            driver: Selenium WebDriver instance

        Returns:
            WebElement if found, None otherwise
        """
        selectors = self.config.get('selectors', {}).get('view_more_button', [])

        view_more_texts = [
            "view more", "load more", "show more", "see more",
            "view more dealers", "more results", "load additional", "show additional"
        ]

        for selector in selectors:
            try:
                if ":contains(" in selector:
                    text_match = re.search(r":contains\('([^']+)'\)", selector)
                    if text_match:
                        text = text_match.group(1)
                        xpath = (
                            f"//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{text.lower()}')]"
                            f" | //a[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{text.lower()}')]"
                        )
                        elements = driver.find_elements(By.XPATH, xpath)
                    else:
                        continue
                else:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)

                for elem in elements:
                    try:
                        if elem.is_displayed() and elem.is_enabled():
                            return elem
                    except Exception:
                        continue
            except Exception:
                continue

        # Fallback: search all buttons and links by text
        try:
            buttons = driver.find_elements(By.TAG_NAME, "button")
            links = driver.find_elements(By.TAG_NAME, "a")
            for elem in buttons + links:
                try:
                    text = (elem.text or "").lower()
                    if any(vmt in text for vmt in view_more_texts):
                        if elem.is_displayed() and elem.is_enabled():
                            return elem
                except Exception:
                    continue
        except Exception:
            pass

        return None

    def _auto_detect_dealer_cards(self, driver: webdriver.Chrome) -> List[WebElement]:
        """
        Auto-detect dealer card/list item elements.

        Args:
            driver: Selenium WebDriver instance

        Returns:
            List of WebElements representing dealer cards
        """
        selectors = self.config.get('selectors', {}).get('dealer_cards', [])
        
        if not selectors:
            selectors = [
                "li[class*='dealer']", "li[class*='Dealer']",
                "div[class*='dealer']", "div[class*='Dealer']",
                "div[class*='dealer-card']", "div[class*='dealerCard']",
                "div[class*='dealer_item']", "div[class*='dealer-item']",
                "div[class*='result-item']", "div[class*='resultItem']",
                "article[class*='dealer']", "div[data-dealer-id]",
                "div[data-dealer]", "[class*='dealer-listing']",
            ]

        all_cards = []
        seen_elements = set()

        for selector in selectors:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                for elem in elements:
                    try:
                        if not elem.is_displayed():
                            continue
                        
                        # Use element location and size as unique identifier
                        # (more stable than ID which can change)
                        location = elem.location
                        size = elem.size
                        elem_key = f"{location['x']},{location['y']},{size['width']},{size['height']}"
                        
                        if elem_key not in seen_elements:
                            seen_elements.add(elem_key)
                            all_cards.append(elem)
                    except Exception:
                        continue
            except Exception:
                continue

        return all_cards

    def _expand_view_more(self, driver: webdriver.Chrome, scroll_container: Optional[WebElement], desired_count: int = 0) -> int:
        """
        Click "View More" buttons until they disappear or desired count is reached.

        Args:
            driver: Selenium WebDriver instance
            scroll_container: Optional scrollable container element
            desired_count: Stop clicking when dealer count reaches this number (0 means no limit)

        Returns:
            Number of times the "View More" button was clicked
        """
        max_clicks = 60
        click_count = 0

        # Use short delays (list loads quickly)
        if self.enable_ai:
            view_more_delay = self.interaction_config.get('view_more_delay', 2)
            content_load_delay = 0.8
        else:
            view_more_delay = 0.4
            content_load_delay = 0.3

        while click_count < max_clicks:
            if desired_count:
                current_cards = self._auto_detect_dealer_cards(driver)
                if len(current_cards) >= desired_count:
                    break

            view_more_button = self._auto_detect_view_more_button(driver)
            if not view_more_button:
                break

            try:
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", view_more_button)
                time.sleep(0.2)
                driver.execute_script("arguments[0].click();", view_more_button)
                click_count += 1
                time.sleep(view_more_delay)
                time.sleep(content_load_delay)
            except Exception:
                break

        return click_count

    def _find_scroll_container(self, driver: webdriver.Chrome) -> Optional[WebElement]:
        """
        Find scrollable container element.

        Args:
            driver: Selenium WebDriver instance

        Returns:
            WebElement if found, None otherwise
        """
        selectors = self.config.get('selectors', {}).get('scroll_container', [])
        
        if not selectors:
            selectors = [
                "div[class*='results']", "div[class*='list']",
                "div[class*='container']", "[class*='scroll']",
                "[class*='dealer-list']"
            ]

        for selector in selectors:
            try:
                containers = driver.find_elements(By.CSS_SELECTOR, selector)
                for container in containers:
                    try:
                        if container.is_displayed():
                            scroll_height = driver.execute_script(
                                "return arguments[0].scrollHeight", container
                            )
                            client_height = driver.execute_script(
                                "return arguments[0].clientHeight", container
                            )
                            if scroll_height > client_height:
                                return container
                    except Exception:
                        continue
            except Exception:
                continue

        return None

    def _smart_scroll(self, driver: webdriver.Chrome, scroll_container: Optional[WebElement] = None):
        """
        Intelligently scroll to load more content.

        Args:
            driver: Selenium WebDriver instance
            scroll_container: Optional scrollable container element
        """
        # Use shorter delays when AI is disabled for better performance
        # But ensure delays are sufficient for lazy loading
        if self.enable_ai:
            scroll_delay = self.interaction_config.get('scroll_delay', 0.5)
        else:
            scroll_delay = 0.3  # Increased from 0.2 to allow lazy loading

        if scroll_container:
            # Scroll within container
            driver.execute_script(
                "arguments[0].scrollTop += arguments[0].clientHeight * 0.8;",
                scroll_container
            )
        else:
            # Scroll the page
            driver.execute_script("window.scrollBy(0, window.innerHeight * 0.8);")

        time.sleep(scroll_delay)

    def _handle_advanced_search(self, driver: webdriver.Chrome) -> bool:
        """
        Detect and handle advanced search/filter pages that require an "Apply" click.

        Args:
            driver: Selenium WebDriver instance

        Returns:
            True if apply button was found and clicked, False otherwise
        """
        # Use shorter delays when AI is disabled for better performance
        if self.enable_ai:
            wait_after_apply = self.interaction_config.get('wait_after_apply', 3)
        else:
            wait_after_apply = 1.0  # Reduced from 3
        
        apply_button = self._auto_detect_apply_button(driver)
        if apply_button:
            try:
                driver.execute_script("arguments[0].click();", apply_button)
                time.sleep(wait_after_apply)
                return True
            except Exception:
                pass
        
        return False

    def _click_view_more(self, driver: webdriver.Chrome) -> bool:
        """
        Click "View More" button if present. Keeps clicking until no more buttons found.

        Args:
            driver: Selenium WebDriver instance

        Returns:
            True if at least one button was clicked, False otherwise
        """
        # Use shorter delays when AI is disabled for better performance
        # But ensure delays are sufficient for content to load
        if self.enable_ai:
            view_more_delay = self.interaction_config.get('view_more_delay', 2)
            content_load_delay = 1.0
        else:
            view_more_delay = 0.8  # Increased from 0.5 to ensure content loads
            content_load_delay = 0.5  # Increased from 0.3 to ensure content loads
        
        max_clicks = 10  # Maximum clicks per call to prevent infinite loops
        clicked_any = False
        
        for _ in range(max_clicks):
            view_more_button = self._auto_detect_view_more_button(driver)
            if view_more_button:
                try:
                    # Scroll button into view first
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", view_more_button)
                    time.sleep(0.3)  # Increased from 0.2 to ensure button is visible
                    
                    # Click the button
                    driver.execute_script("arguments[0].click();", view_more_button)
                    clicked_any = True
                    time.sleep(view_more_delay)
                    
                    # Wait a bit for new content to load
                    time.sleep(content_load_delay)
                except Exception:
                    break
            else:
                # No more buttons found
                break
        
        return clicked_any

    def _extract_simple_dealer(self, card: WebElement, search_zip: str) -> Optional[Dealer]:
        """
        Fast extraction: use common tags within a card (name, address, phone, website).
        """
        try:
            if not card.is_displayed():
                return None
        except Exception:
            return None

        # Name: prefer header tags, then dealer-name classes
        name = None
        name_selectors = "h3, h4, h2, h5, [class*='dealer-name'], [class*='dealerName']"
        try:
            for elem in card.find_elements(By.CSS_SELECTOR, name_selectors):
                text = (elem.text or "").strip()
                cleaned = clean_name(text, self.SKIP_NAMES)
                if cleaned:
                    name = cleaned
                    break
        except Exception:
            pass

        if not name:
            return None

        # Address: look for address/location classes first
        full_address = ""
        city = ""
        state = ""
        zip_code = ""
        address_selectors = (
            "div[class*='address'], span[class*='address'], "
            "div[class*='location'], span[class*='location'], "
            "div[class*='addr'], span[class*='addr']"
        )
        try:
            address_elems = card.find_elements(By.CSS_SELECTOR, address_selectors)
            for elem in address_elems:
                text = (elem.text or "").strip()
                if text and re.search(r'\d{5}', text):
                    full_address, city, state, zip_code = parse_address(text)
                    break
        except Exception:
            pass

        # Phone: look for tel links
        phone = ""
        try:
            phone_links = card.find_elements(By.CSS_SELECTOR, "a[href^='tel:']")
            if phone_links:
                href = phone_links[0].get_attribute("href") or ""
                phone = href.replace("tel:", "").strip()
        except Exception:
            pass

        # Website: first http link in card (not tel/mail)
        website = ""
        try:
            for link in card.find_elements(By.CSS_SELECTOR, "a[href]"):
                href = (link.get_attribute("href") or "").strip()
                if href.startswith("http") and "mailto:" not in href and "tel:" not in href:
                    website = href
                    break
        except Exception:
            pass

        # Dedupe check
        key = f"{name.lower()}|{full_address.lower()}"
        if key in self.seen_dealers:
            return None
        self.seen_dealers.add(key)

        return Dealer(
            brand=self.brand.capitalize() if self.brand else "Unknown",
            name=name,
            address=full_address,
            city=city,
            state=state,
            zip_code=zip_code,
            phone=phone,
            website=website,
            dealer_type="Standard",
            distance_miles="",
            search_zip=search_zip,
            scrape_date=self.scrape_date,
        )

    def _analyze_new_site(self, url: str) -> bool:
        """
        Analyze a new manufacturer website using LLM to extract scraping patterns.

        Args:
            url: Manufacturer website URL

        Returns:
            True if analysis succeeded and config was generated, False otherwise
        """
        if not self.brand:
            return False
        
        # Skip AI analysis if disabled
        if not self.enable_ai:
            return False

        # Check if LLM config already exists
        if self.config_manager.has_llm_config(self.brand):
            print(f"  Using cached LLM config for {self.brand}")
            # Reload config to include LLM-generated one
            self.config = self.config_manager.get_config(self.brand)
            self.interaction_config = self.config_manager.get_interaction_config(self.brand)
            self.extraction_config = self.config_manager.get_extraction_config(self.brand)
            return True

        print(f"  Analyzing {self.brand} website with LLM...")

        # Step 1: Fetch page content using Jina Reader
        content = self.jina_reader.fetch_page_content(
            url,
            wait_selector=None,  # Let Jina Reader handle dynamic content
            timeout=30,
            streaming=True  # Use streaming for better results with dynamic content
        )

        # Fallback: If Jina Reader fails, we'll skip LLM analysis
        if not content:
            print(f"  Warning: Could not fetch content from Jina Reader, skipping LLM analysis")
            return False

        # Step 2: Analyze with LLM
        analysis_result = self.llm_analyzer.analyze_page_structure(content, url)
        if not analysis_result:
            print(f"  Warning: LLM analysis failed, falling back to auto-detection")
            return False

        confidence = analysis_result.get('confidence', 0.0)
        print(f"  LLM analysis complete (confidence: {confidence:.2f})")

        # Step 3: Generate config from analysis
        config = generate_config_from_analysis(analysis_result, self.brand, url)

        # Step 4: Cache the config
        self.config_manager.cache_llm_config(config, self.brand)

        # Step 5: Reload config to use the new LLM-generated one
        self.config = self.config_manager.get_config(self.brand)
        self.interaction_config = self.config_manager.get_interaction_config(self.brand)
        self.extraction_config = self.config_manager.get_extraction_config(self.brand)

        print(f"  LLM-generated config saved and loaded for {self.brand}")
        return True

    def _extract_with_fallback(self, card: WebElement, search_zip: str) -> Optional[Dealer]:
        """
        Extract dealer information using multiple strategies with fallbacks.

        Args:
            card: Dealer card WebElement
            search_zip: Zip code used for search

        Returns:
            Dealer object or None if extraction fails
        """
        try:
            card_text = card.text
        except Exception:
            return None

        if not card_text or not card_text.strip():
            return None

        lines = [l.strip() for l in card_text.split('\n') if l.strip()]
        if not lines:
            return None

        # Extract name using multiple strategies
        name = None
        name_patterns = self.extraction_config.get('name_patterns', [])
        
        # Try config patterns first
        for pattern in name_patterns:
            for line in lines:
                match = re.match(pattern, line)
                if match:
                    potential_name = match.group(1) if match.groups() else match.group(0)
                    cleaned = clean_name(potential_name, self.SKIP_NAMES)
                    if cleaned:
                        name = cleaned
                        break
            if name:
                break

        # Fallback: try common patterns
        if not name:
            for line in lines:
                # Pattern: "1. Dealer Name"
                match = re.match(r'^\d+\.\s*(.+)', line)
                if match:
                    potential_name = match.group(1).strip()
                    cleaned = clean_name(potential_name, self.SKIP_NAMES)
                    if cleaned:
                        name = cleaned
                        break

                # Pattern: "Dealer Name | Address"
                match = re.match(r'^(.+?)\s*\|', line)
                if match:
                    potential_name = match.group(1).strip()
                    cleaned = clean_name(potential_name, self.SKIP_NAMES)
                    if cleaned:
                        name = cleaned
                        break

        # Last resort: use first non-skip line
        if not name:
            for line in lines:
                cleaned = clean_name(line, self.SKIP_NAMES)
                if cleaned:
                    name = cleaned
                    break

        # Extract address
        full_address = ""
        city = ""
        state = ""
        zip_code = ""
        
        for line in lines:
            if re.search(r'\d{5}', line) and re.search(r'[A-Za-z]', line):
                if not any(s in line.lower() for s in self.SKIP_NAMES):
                    full_address, city, state, zip_code = parse_address(line)
                    break

        # Extract phone
        phone_patterns = self.extraction_config.get('phone_patterns', [])
        phone = extract_phone(card_text, phone_patterns)

        # Extract website
        skip_domains = self.extraction_config.get('skip_domains', [])
        try:
            links = card.find_elements(By.TAG_NAME, "a")
        except Exception:
            links = []
        website = extract_website_url(card_text, links, skip_domains)

        # Extract distance
        distance = extract_distance(card_text)

        # Dealer type detection
        text_lower = card_text.lower()
        types = []
        if 'elite' in text_lower:
            types.append('Elite')
        if 'certified' in text_lower:
            types.append('Certified')
        if 'ev certified' in text_lower or 'ev-certified' in text_lower:
            types.append('EV Certified')

        # Dedupe check
        key = f"{name.lower()}|{full_address.lower()}"
        if key in self.seen_dealers:
            return None
        self.seen_dealers.add(key)

        return Dealer(
            brand=self.brand.capitalize() if self.brand else "Unknown",
            name=name,
            address=full_address,
            city=city,
            state=state,
            zip_code=zip_code,
            phone=phone,
            website=website,
            dealer_type=', '.join(types) if types else 'Standard',
            distance_miles=distance,
            search_zip=search_zip,
            scrape_date=self.scrape_date,
        )


class FordScraper(BaseScraper):
    """Scraper for Ford dealerships."""

    BRAND = "Ford"
    BASE_URL = "https://www.ford.com/dealerships/"

    def __init__(self, headless: bool = True, enable_ai: bool = False):
        super().__init__(headless, brand=self.BRAND, enable_ai=enable_ai)
        self.driver = None

    def _setup_driver(self):
        options = Options()
        if self.headless:
            options.add_argument("--headless=new")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")
        options.add_argument(
            "user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        options.add_experimental_option("excludeSwitches", ["enable-automation"])

        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=options)

    def scrape(self, zip_codes: List[str]) -> List[Dealer]:
        all_dealers = []
        self._setup_driver()

        # Trigger LLM analysis on first visit (before processing zip codes)
        self._analyze_new_site(self.BASE_URL)

        try:
            for i, zip_code in enumerate(zip_codes):
                print(f"[{i+1}/{len(zip_codes)}] Scraping {self.BRAND} dealers for {zip_code}...")

                try:
                    dealers = self._scrape_zip(zip_code)
                    all_dealers.extend(dealers)
                    print(f"  Found {len(dealers)} dealers")
                except Exception as e:
                    print(f"  Error: {e}")

                # Use shorter delays when AI is disabled for better performance
                delay_between_requests = 2.0 if self.enable_ai else 0.5
                time.sleep(delay_between_requests)

        finally:
            if self.driver:
                self.driver.quit()

        return all_dealers

    def _scrape_zip(self, zip_code: str) -> List[Dealer]:
        dealers = []

        # Use shorter delays when AI is disabled for better performance
        if self.enable_ai:
            wait_after_page_load = self.interaction_config.get('wait_after_page_load', 3)
            click_delay = self.interaction_config.get('click_delay', 0.3)
            wait_after_search = self.interaction_config.get('wait_after_search', 4)
            cookie_delay = 1.0
        else:
            wait_after_page_load = 1.5  # Reduced from 3
            click_delay = 0.1  # Reduced from 0.3
            wait_after_search = 2.0  # Reduced from 4
            cookie_delay = 0.3  # Reduced from 1.0

        # Navigate to page
        self.driver.get(self.BASE_URL)
        time.sleep(wait_after_page_load)

        # Handle cookie popup
        try:
            cookie_btn = self.driver.find_element(By.ID, "onetrust-accept-btn-handler")
            if cookie_btn.is_displayed():
                cookie_btn.click()
                time.sleep(cookie_delay)
        except:
            pass

        # Find and fill search input using auto-detection
        search_box = self._auto_detect_search_input(self.driver)
        if not search_box:
            print(f"  Could not find search input")
            return dealers

        search_box.click()
        search_box.clear()
        time.sleep(click_delay)
        search_box.send_keys(zip_code)
        time.sleep(click_delay)
        search_box.send_keys(Keys.RETURN)
        
        time.sleep(wait_after_search)

        # Handle advanced search if present
        self._handle_advanced_search(self.driver)

        # Wait for dealer cards to appear before starting extraction
        # This ensures the page has loaded initial results
        try:
            WebDriverWait(self.driver, 10).until(
                lambda d: len(self._auto_detect_dealer_cards(d)) > 0
            )
            print(f"  Initial dealer cards detected")
        except Exception:
            print(f"  Warning: No dealer cards found initially, proceeding anyway...")

        # Extract dealers
        dealers = self._extract_dealers(zip_code)
        return dealers

    def _extract_dealers(self, zip_code: str) -> List[Dealer]:
        """
        Extract all dealers with efficient "View More" and scrolling logic.
        """
        dealers = []
        seen_names = set()

        # Find scroll container using auto-detection
        scroll_container = self._find_scroll_container(self.driver)

        desired_count = self.interaction_config.get('desired_dealer_count', 0)

        # Click "View More" until exhausted or desired count reached
        click_count = self._expand_view_more(self.driver, scroll_container, desired_count)
        if click_count:
            print(f"  Clicked 'View More' {click_count} times")

        # Scroll to load any lazy-loaded cards
        stable_checks = 0
        last_count = 0
        max_scroll_checks = 8
        scroll_wait_delay = 0.6 if self.enable_ai else 0.3

        for _ in range(max_scroll_checks):
            self._scroll_to_bottom(self.driver, scroll_container)
            time.sleep(scroll_wait_delay)
            current_cards = self._auto_detect_dealer_cards(self.driver)
            current_count = len(current_cards)
            if current_count == last_count:
                stable_checks += 1
            else:
                stable_checks = 0
                last_count = current_count
            if stable_checks >= 2:
                break

        # Final extraction pass (single scan for speed)
        dealer_cards = self._auto_detect_dealer_cards(self.driver)
        for card in dealer_cards:
            dealer = self._extract_simple_dealer(card, zip_code)
            if not dealer:
                dealer = self._extract_with_fallback(card, zip_code)
            if dealer and dealer.name.lower() not in seen_names:
                seen_names.add(dealer.name.lower())
                dealers.append(dealer)

        print(f"  Extraction complete. Found {len(dealers)} total dealers.")
        return dealers

    def _scroll_to_bottom(self, driver: webdriver.Chrome, scroll_container: Optional[WebElement] = None, force: bool = False):
        """
        Scroll to the absolute bottom of the page/container.
        
        Args:
            driver: Selenium WebDriver instance
            scroll_container: Optional scrollable container element
            force: If True, scroll multiple times to ensure we reach the bottom
        """
        # Use shorter delays when AI is disabled for better performance
        # But ensure delays are sufficient for lazy loading
        if self.enable_ai:
            scroll_delay = self.interaction_config.get('scroll_delay', 0.5)
        else:
            scroll_delay = 0.3  # Increased from 0.2 to allow lazy loading
        
        if force:
            # Force scroll multiple times to ensure we reach the absolute bottom
            for _ in range(3):
                if scroll_container:
                    driver.execute_script(
                        "arguments[0].scrollTop = arguments[0].scrollHeight;",
                        scroll_container
                    )
                else:
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(scroll_delay)
        else:
            # Normal scroll - scroll progressively to trigger lazy loading
            if scroll_container:
                # Get current scroll position
                current_scroll = driver.execute_script("return arguments[0].scrollTop;", scroll_container)
                max_scroll = driver.execute_script("return arguments[0].scrollHeight;", scroll_container)
                client_height = driver.execute_script("return arguments[0].clientHeight;", scroll_container)
                
                # Scroll down by 90% of visible height
                scroll_amount = client_height * 0.9
                new_scroll = min(current_scroll + scroll_amount, max_scroll)
                driver.execute_script("arguments[0].scrollTop = arguments[1];", scroll_container, new_scroll)
            else:
                # Scroll the page progressively
                driver.execute_script("window.scrollBy(0, window.innerHeight * 0.9);")
            time.sleep(scroll_delay)


# Registry of available scrapers
SCRAPERS = {
    'ford': FordScraper,
    # Add more scrapers here as they are implemented
    # 'toyota': ToyotaScraper,
    # 'honda': HondaScraper,
}


def _worker_scrape(args: Tuple[str, List[str], bool, bool, int, int]) -> List[Dict]:
    """
    Worker function for parallel scraping.
    Runs in a separate process with its own browser instance.

    Args:
        args: Tuple of (brand, zip_codes, headless, enable_ai, worker_id, total_workers)

    Returns:
        List of dealer dictionaries
    """
    brand, zip_codes, headless, enable_ai, worker_id, total_workers = args

    scraper_class = SCRAPERS.get(brand)
    if not scraper_class:
        return []

    scraper = scraper_class(headless=headless, enable_ai=enable_ai)
    dealers = []

    # Setup driver once for this worker
    scraper._setup_driver()

    try:
        for i, zip_code in enumerate(zip_codes):
            print(f"[Worker {worker_id}/{total_workers}] [{i+1}/{len(zip_codes)}] Scraping {zip_code}...")

            try:
                batch = scraper._scrape_zip(zip_code)
                dealers.extend(batch)
                print(f"[Worker {worker_id}] Found {len(batch)} dealers for {zip_code}")
            except Exception as e:
                print(f"[Worker {worker_id}] Error scraping {zip_code}: {e}")

            time.sleep(1)  # Reduced delay for parallel execution
    finally:
        if scraper.driver:
            scraper.driver.quit()

    # Convert to dicts for pickling across processes
    return [asdict(d) for d in dealers]


def scrape_parallel(brand: str, zip_codes: List[str], headless: bool = True,
                    workers: int = 4, enable_ai: bool = False) -> List[Dealer]:
    """
    Scrape dealers using multiple parallel browser instances.

    Args:
        brand: Brand to scrape
        zip_codes: List of zip codes to search
        headless: Run browsers in headless mode
        workers: Number of parallel browser instances
        enable_ai: Enable AI features (Jina Reader and LLM analysis)

    Returns:
        List of deduplicated Dealer objects
    """
    if brand not in SCRAPERS:
        print(f"Unknown brand: {brand}")
        return []

    # Limit workers to available zip codes
    workers = min(workers, len(zip_codes))

    if workers <= 1:
        # Fall back to sequential for single worker
        scraper = SCRAPERS[brand](headless=headless, enable_ai=enable_ai)
        return scraper.scrape(zip_codes)

    # Split zip codes among workers
    chunks = [[] for _ in range(workers)]
    for i, zc in enumerate(zip_codes):
        chunks[i % workers].append(zc)

    # Filter out empty chunks
    chunks = [c for c in chunks if c]
    actual_workers = len(chunks)

    print(f"\nStarting {actual_workers} parallel browser instances...")
    print(f"Distributing {len(zip_codes)} zip codes across workers")
    for i, chunk in enumerate(chunks):
        print(f"  Worker {i+1}: {len(chunk)} zip codes")
    print()

    # Prepare worker arguments
    worker_args = [
        (brand, chunk, headless, enable_ai, i+1, actual_workers)
        for i, chunk in enumerate(chunks)
    ]

    # Run workers in parallel
    all_dealer_dicts = []
    with ProcessPoolExecutor(max_workers=actual_workers) as executor:
        futures = {executor.submit(_worker_scrape, args): args[3] for args in worker_args}

        for future in as_completed(futures):
            worker_id = futures[future]
            try:
                dealer_dicts = future.result()
                all_dealer_dicts.extend(dealer_dicts)
                print(f"[Worker {worker_id}] Completed with {len(dealer_dicts)} dealers")
            except Exception as e:
                print(f"[Worker {worker_id}] Failed with error: {e}")

    # Convert back to Dealer objects and deduplicate
    seen = set()
    dealers = []
    for d in all_dealer_dicts:
        key = f"{d['name'].lower()}|{d['address'].lower()}"
        if key not in seen:
            seen.add(key)
            dealers.append(Dealer(**d))

    print(f"\nTotal unique dealers after deduplication: {len(dealers)}")
    return dealers


def load_zip_codes(zip_codes_arg: str, zip_file: str) -> List[str]:
    """Load zip codes from arguments or file."""
    codes = []

    if zip_codes_arg:
        codes = [z.strip() for z in zip_codes_arg.split(",") if z.strip()]

    if zip_file and os.path.exists(zip_file):
        with open(zip_file, 'r') as f:
            for line in f:
                line = line.strip()
                # Skip empty lines and comment-only lines
                if not line or line.startswith('#'):
                    continue
                
                # Strip inline comments (everything after #)
                if '#' in line:
                    line = line.split('#')[0].strip()
                
                # Only add if there's still content after stripping
                if line and line not in codes:
                    codes.append(line)

    return codes if codes else ["10001"]


def save_results(dealers: List[Dealer], output_dir: str, brand: str):
    """Save dealers to CSV and JSON files."""
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # CSV
    csv_path = os.path.join(output_dir, f"{brand}_dealers_{timestamp}.csv")
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        if dealers:
            writer = csv.DictWriter(f, fieldnames=asdict(dealers[0]).keys())
            writer.writeheader()
            for d in dealers:
                writer.writerow(asdict(d))
    print(f"Saved CSV: {csv_path}")

    # JSON
    json_path = os.path.join(output_dir, f"{brand}_dealers_{timestamp}.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump([asdict(d) for d in dealers], f, indent=2)
    print(f"Saved JSON: {json_path}")


def main():
    parser = argparse.ArgumentParser(description="Scrape car dealership information")
    parser.add_argument("--brand", type=str, default="ford",
                        help="Brand to scrape (ford, toyota, all)")
    parser.add_argument("--zip-codes", type=str,
                        help="Comma-separated zip codes")
    parser.add_argument("--zip-file", type=str,
                        help="File with zip codes (one per line)")
    parser.add_argument("--output-dir", type=str, default="output",
                        help="Output directory")
    parser.add_argument("--headless", action="store_true", default=True,
                        help="Run browser in headless mode")
    parser.add_argument("--no-headless", action="store_true",
                        help="Run browser with visible window")
    parser.add_argument("--workers", "-w", type=int, default=1,
                        help="Number of parallel browser instances (default: 1)")
    parser.add_argument("--list-brands", action="store_true",
                        help="List available brands")
    parser.add_argument("--enable-ai", action="store_true",
                        help="Enable AI features (Jina Reader and LLM analysis)")
    parser.add_argument("--disable-ai", action="store_true",
                        help="Disable AI features, use basic auto-detection only (default: disabled)")

    args = parser.parse_args()

    if args.list_brands:
        print("\nAvailable brands:")
        for brand in SCRAPERS.keys():
            print(f"  - {brand}")
        return

    headless = not args.no_headless
    workers = max(1, args.workers)
    
    # Determine AI feature status (default: disabled, only enable if --enable-ai is explicitly used)
    enable_ai = args.enable_ai and not args.disable_ai
    if enable_ai:
        print("AI features enabled - using Jina Reader and LLM analysis")
    else:
        print("AI features disabled - using basic auto-detection only")

    # Load zip codes
    zip_codes = load_zip_codes(args.zip_codes, args.zip_file)
    print(f"Loaded {len(zip_codes)} zip codes")

    # Determine brands to scrape
    if args.brand.lower() == 'all':
        brands = list(SCRAPERS.keys())
    else:
        brands = [args.brand.lower()]

    # Validate brands
    for brand in brands:
        if brand not in SCRAPERS:
            print(f"Unknown brand: {brand}")
            print(f"Available: {', '.join(SCRAPERS.keys())}")
            return

    # Scrape each brand
    all_dealers = []
    for brand in brands:
        print(f"\n{'='*60}")
        print(f"Scraping {brand.upper()} dealerships...")
        if workers > 1:
            print(f"Using {workers} parallel browser instances")
        print(f"{'='*60}")

        if workers > 1:
            dealers = scrape_parallel(brand, zip_codes, headless=headless, workers=workers, enable_ai=enable_ai)
        else:
            scraper = SCRAPERS[brand](headless=headless, enable_ai=enable_ai)
            dealers = scraper.scrape(zip_codes)

        all_dealers.extend(dealers)

        print(f"\nTotal {brand} dealers found: {len(dealers)}")
        save_results(dealers, args.output_dir, brand)

    print(f"\n{'='*60}")
    print(f"COMPLETE: Found {len(all_dealers)} dealers across all brands")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
