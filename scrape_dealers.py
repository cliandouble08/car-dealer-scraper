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
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, asdict

import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager


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
    """Base class for dealer scrapers."""

    SKIP_NAMES = [
        'search by', 'location', 'name', 'clear', 'advanced search',
        'view map', 'make my dealer', 'chat with dealer', 'dealer website',
        'find more', 'view more', 'load more'
    ]

    def __init__(self, headless: bool = True):
        self.headless = headless
        self.scrape_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.seen_dealers = set()

    def scrape(self, zip_codes: List[str]) -> List[Dealer]:
        raise NotImplementedError

    def _is_valid_name(self, name: str) -> bool:
        if not name or len(name) < 3:
            return False
        return not any(skip in name.lower() for skip in self.SKIP_NAMES)


class FordScraper(BaseScraper):
    """Scraper for Ford dealerships."""

    BRAND = "Ford"
    BASE_URL = "https://www.ford.com/dealerships/"

    def __init__(self, headless: bool = True):
        super().__init__(headless)
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

        try:
            for i, zip_code in enumerate(zip_codes):
                print(f"[{i+1}/{len(zip_codes)}] Scraping {self.BRAND} dealers for {zip_code}...")

                try:
                    dealers = self._scrape_zip(zip_code)
                    all_dealers.extend(dealers)
                    print(f"  Found {len(dealers)} dealers")
                except Exception as e:
                    print(f"  Error: {e}")

                time.sleep(2)  # Be polite between requests

        finally:
            if self.driver:
                self.driver.quit()

        return all_dealers

    def _scrape_zip(self, zip_code: str) -> List[Dealer]:
        dealers = []

        # Navigate to page
        self.driver.get(self.BASE_URL)
        time.sleep(3)

        # Handle cookie popup
        try:
            cookie_btn = self.driver.find_element(By.ID, "onetrust-accept-btn-handler")
            if cookie_btn.is_displayed():
                cookie_btn.click()
                time.sleep(1)
        except:
            pass

        # Find and fill search input
        search_box = self._find_search_input()
        if not search_box:
            print(f"  Could not find search input")
            return dealers

        search_box.click()
        search_box.clear()
        time.sleep(0.3)
        search_box.send_keys(zip_code)
        time.sleep(0.5)
        search_box.send_keys(Keys.RETURN)
        time.sleep(4)

        # Extract dealers
        dealers = self._extract_dealers(zip_code)
        return dealers

    def _find_search_input(self):
        for selector in ["input[placeholder*='Zip']", "input[placeholder*='City']",
                         "input[aria-label*='Zip']"]:
            try:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for elem in elements:
                    if elem.is_displayed() and elem.is_enabled():
                        return elem
            except:
                continue
        return None

    def _extract_dealers(self, zip_code: str) -> List[Dealer]:
        dealers = []
        seen_names = set()

        # Find scroll container
        scroll_container = self._find_scroll_container()

        max_iterations = 30
        no_new_count = 0

        for _ in range(max_iterations):
            # Click "View More" button
            self._click_view_more()

            # Find all dealer cards
            dealer_cards = self._find_dealer_cards()
            new_found = False

            for card in dealer_cards:
                dealer = self._parse_card(card, zip_code)
                if dealer and dealer.name.lower() not in seen_names:
                    seen_names.add(dealer.name.lower())
                    dealers.append(dealer)
                    new_found = True

            if not new_found:
                no_new_count += 1
                if no_new_count >= 3:
                    break
            else:
                no_new_count = 0

            # Scroll
            if scroll_container:
                self.driver.execute_script(
                    "arguments[0].scrollTop += arguments[0].clientHeight * 0.8;",
                    scroll_container
                )
            else:
                self.driver.execute_script("window.scrollBy(0, 500);")

            time.sleep(0.5)

        return dealers

    def _find_dealer_cards(self) -> list:
        """Find all dealer card elements on the page."""
        # Try different selectors for dealer cards
        selectors = [
            "li[class*='dealer']",
            "div[class*='dealer-card']",
            "div[class*='result-item']",
            "article[class*='dealer']",
        ]
        for selector in selectors:
            try:
                cards = self.driver.find_elements(By.CSS_SELECTOR, selector)
                if cards:
                    return [c for c in cards if c.is_displayed()]
            except:
                continue
        return []

    def _parse_card(self, card, search_zip: str) -> Optional[Dealer]:
        """Parse a dealer card element to extract all information including website."""
        try:
            card_text = card.text
        except:
            return None

        lines = [l.strip() for l in card_text.split('\n') if l.strip()]
        if not lines:
            return None

        # Find name (starts with number like "1.")
        name = None
        for line in lines:
            if re.match(r'^\d+\.', line):
                name = re.sub(r'^\d+\.\s*', '', line).strip()
                if self._is_valid_name(name):
                    break
                name = None

        if not name:
            return None

        # Find address (contains zip code)
        address = ""
        for line in lines:
            if re.search(r'\d{5}', line) and re.search(r'[A-Za-z]', line):
                if not any(s in line.lower() for s in self.SKIP_NAMES):
                    address = line
                    break

        # Find phone
        phone = ""
        for line in lines:
            match = re.search(r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}', line)
            if match:
                phone = match.group()
                break

        # Find distance
        distance = ""
        for line in lines:
            match = re.search(r'([\d.]+)\s*mi', line.lower())
            if match:
                distance = match.group(1)
                break

        # Extract website from links in the card
        website = self._extract_website_from_card(card)

        # Dealer type
        text_lower = card_text.lower()
        types = []
        if 'elite' in text_lower:
            types.append('Elite')
        if 'certified' in text_lower:
            types.append('Certified')
        if 'ev certified' in text_lower:
            types.append('EV Certified')

        # Dedupe check
        key = f"{name.lower()}|{address.lower()}"
        if key in self.seen_dealers:
            return None
        self.seen_dealers.add(key)

        return Dealer(
            brand=self.BRAND,
            name=name,
            address=address,
            phone=phone,
            website=website,
            dealer_type=', '.join(types) if types else 'Standard',
            distance_miles=distance,
            search_zip=search_zip,
            scrape_date=self.scrape_date,
        )

    def _extract_website_from_card(self, card) -> str:
        """Extract dealer website URL from card element."""
        try:
            # Look for links with "website" or "dealer" in text or href
            links = card.find_elements(By.TAG_NAME, "a")
            for link in links:
                href = link.get_attribute("href") or ""
                text = link.text.lower()

                # Skip ford.com internal links and common non-dealer links
                skip_domains = ['ford.com', 'maps.google', 'tel:', 'mailto:']
                if any(skip in href.lower() for skip in skip_domains):
                    continue

                # Look for dealer website link
                if 'website' in text or 'dealer site' in text:
                    return href

                # Also accept external http links that look like dealer sites
                if href.startswith('http') and not any(skip in href.lower() for skip in skip_domains):
                    return href
        except:
            pass
        return ""

    def _find_scroll_container(self):
        for selector in ["div.dealer-standard", "div.bri-style"]:
            try:
                containers = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for container in containers:
                    if container.is_displayed():
                        sh = self.driver.execute_script("return arguments[0].scrollHeight", container)
                        ch = self.driver.execute_script("return arguments[0].clientHeight", container)
                        if sh > ch:
                            return container
            except:
                continue
        return None

    def _click_view_more(self):
        try:
            buttons = self.driver.find_elements(By.TAG_NAME, "button")
            for btn in buttons:
                if any(p in btn.text.lower() for p in ['view more', 'find more', 'load more']):
                    if btn.is_displayed() and btn.is_enabled():
                        self.driver.execute_script("arguments[0].click();", btn)
                        time.sleep(2)
                        return True
        except:
            pass
        return False

# Registry of available scrapers
SCRAPERS = {
    'ford': FordScraper,
    # Add more scrapers here as they are implemented
    # 'toyota': ToyotaScraper,
    # 'honda': HondaScraper,
}


def _worker_scrape(args: Tuple[str, List[str], bool, int, int]) -> List[Dict]:
    """
    Worker function for parallel scraping.
    Runs in a separate process with its own browser instance.

    Args:
        args: Tuple of (brand, zip_codes, headless, worker_id, total_workers)

    Returns:
        List of dealer dictionaries
    """
    brand, zip_codes, headless, worker_id, total_workers = args

    scraper_class = SCRAPERS.get(brand)
    if not scraper_class:
        return []

    scraper = scraper_class(headless=headless)
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
                    workers: int = 4) -> List[Dealer]:
    """
    Scrape dealers using multiple parallel browser instances.

    Args:
        brand: Brand to scrape
        zip_codes: List of zip codes to search
        headless: Run browsers in headless mode
        workers: Number of parallel browser instances

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
        scraper = SCRAPERS[brand](headless=headless)
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
        (brand, chunk, headless, i+1, actual_workers)
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
                if line and not line.startswith('#') and line not in codes:
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

    args = parser.parse_args()

    if args.list_brands:
        print("\nAvailable brands:")
        for brand in SCRAPERS.keys():
            print(f"  - {brand}")
        return

    headless = not args.no_headless
    workers = max(1, args.workers)

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
            dealers = scrape_parallel(brand, zip_codes, headless=headless, workers=workers)
        else:
            scraper = SCRAPERS[brand](headless=headless)
            dealers = scraper.scrape(zip_codes)

        all_dealers.extend(dealers)

        print(f"\nTotal {brand} dealers found: {len(dealers)}")
        save_results(dealers, args.output_dir, brand)

    print(f"\n{'='*60}")
    print(f"COMPLETE: Found {len(all_dealers)} dealers across all brands")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
