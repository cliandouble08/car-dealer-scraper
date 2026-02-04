"""
Crawl4AI-based dealer scraper.

This module replaces Playwright with Crawl4AI for all browser automation tasks.
Handles form submission, virtual scrolling, and dealer card extraction.
"""

import asyncio
import json
import os
from typing import Dict, List, Optional
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
from crawl4ai.async_configs import CrawlerRunConfig as RunConfig
from crawl4ai.extraction_strategy import LLMExtractionStrategy
from bs4 import BeautifulSoup


class Crawl4AIScraper:
    """Crawl4AI-based scraper for dealer locator pages."""

    def __init__(self, headless: bool = True, verbose: bool = False):
        """
        Initialize Crawl4AI scraper.

        Args:
            headless: Run browser in headless mode
            verbose: Enable verbose logging
        """
        self.headless = headless
        self.verbose = verbose

    @staticmethod
    def _escape_js_string(s: str) -> str:
        """
        Escape a string for safe use in JavaScript code.

        Args:
            s: String to escape

        Returns:
            Escaped string safe for JavaScript
        """
        if not s:
            return s
        # Escape single quotes, backslashes, and newlines
        return s.replace('\\', '\\\\').replace("'", "\\'").replace('\n', '\\n').replace('\r', '\\r')

    def _get_llm_config(self, config: Dict) -> tuple:
        """
        Get LLM provider configuration from environment/config.

        Reuses existing LLM analyzer setup from utils/llm_analyzer.py

        Returns:
            Tuple of (provider, api_token)
        """
        # Check if LLM is enabled
        if not os.getenv('LLM_ANALYSIS_ENABLED', 'true').lower() == 'true':
            raise ValueError("LLM analysis is disabled (LLM_ANALYSIS_ENABLED=false)")

        # Get LLM endpoint and model from environment (same as llm_analyzer.py)
        llm_endpoint = os.getenv('LLM_ENDPOINT', 'http://localhost:11434/api/generate')
        llm_model = os.getenv('LLM_MODEL', 'gemma2:2b')

        # Determine provider format for Crawl4AI
        if 'ollama' in llm_endpoint or ':11434' in llm_endpoint:
            provider = f"ollama/{llm_model}"
            api_token = None  # Ollama doesn't need API token
        elif 'openai' in llm_endpoint or os.getenv('OPENAI_API_KEY'):
            provider = "openai/gpt-4o-mini"
            api_token = os.getenv('OPENAI_API_KEY')
        else:
            # Default to Ollama
            provider = f"ollama/{llm_model}"
            api_token = None

        return provider, api_token

    def _get_selectors_from_config(self, config: Dict) -> Dict[str, str]:
        """
        Extract selectors from config as fallback when LLM discovery fails.

        Returns:
            Dict with same structure as LLM discovery output
        """
        selectors = config.get('selectors', {})

        return {
            'zip_input': selectors.get('search_input', [''])[0] if selectors.get('search_input') else '',
            'submit_button': selectors.get('search_button', [''])[0] if selectors.get('search_button') else '',
            'view_more_button': selectors.get('view_more_button', [''])[0] if selectors.get('view_more_button') else None,
            'dealer_cards': selectors.get('dealer_cards', ['.dealer-card'])[0] if selectors.get('dealer_cards') else '.dealer-card'
        }

    async def _discover_data_fields_with_llm(
        self,
        crawler: AsyncWebCrawler,
        url: str,
        config: Dict,
        session_id: str,
        process_iframes: bool = False
    ) -> Dict[str, Dict]:
        """
        Discover data field selectors from search results page using LLM.

        After the search is submitted and dealer cards appear, this method
        analyzes the actual results to understand how dealer information
        is structured and labeled.

        Args:
            crawler: Active AsyncWebCrawler instance
            url: Page URL
            config: Configuration dict
            session_id: Current session ID
            process_iframes: Whether to process iframe content

        Returns:
            Dict with data field configurations: {
                'name': {'selector': 'h2.dealer-name', 'type': 'text'},
                'address': {'selector': '.dealer-address', 'type': 'text'},
                'phone': {'selector': 'a.phone', 'type': 'href', 'attribute': 'href'},
                'website': {'selector': 'a.website', 'type': 'href', 'attribute': 'href'}
            }
        """
        try:
            llm_instruction = """
            Analyze this dealer search results page and identify how dealer information is structured.

            For EACH dealer card/listing, identify the CSS selectors for:

            1. DEALER NAME: The dealership name
               - Look for headings (h1, h2, h3, h4)
               - Common patterns: .dealer-name, .name, .title, .dealership-name
               - Return the most specific selector

            2. ADDRESS: The street address, city, state, zip
               - May be a single element or multiple elements
               - Common patterns: .address, .location, .dealer-address
               - Look for text containing street numbers and zip codes

            3. PHONE NUMBER: The phone contact
               - Look for <a href="tel:..."> links
               - Common patterns: .phone, .tel, .contact-phone, a[href^="tel:"]
               - Return the selector and whether it's in href attribute or text

            4. WEBSITE: The dealer's website URL
               - Look for external links (not the current domain)
               - Common patterns: .website, .dealer-website, a.external-link
               - Return the selector for the link element

            5. DISTANCE: Distance from search location (optional)
               - Look for text like "5.2 miles", "10 km away"
               - Common patterns: .distance, .miles, .proximity

            Return JSON format:
            {
                "name": {
                    "selector": "CSS_SELECTOR",
                    "type": "text"
                },
                "address": {
                    "selector": "CSS_SELECTOR",
                    "type": "text"
                },
                "phone": {
                    "selector": "CSS_SELECTOR",
                    "type": "text or href",
                    "attribute": "href (if type is href)"
                },
                "website": {
                    "selector": "CSS_SELECTOR",
                    "type": "href",
                    "attribute": "href"
                },
                "distance": {
                    "selector": "CSS_SELECTOR",
                    "type": "text"
                }
            }

            Rules:
            - Provide selectors RELATIVE to the dealer card (not absolute document selectors)
            - Use the MOST SPECIFIC selector (ID > class > attribute > tag)
            - Test that selectors uniquely identify the field within each card
            - Return null for fields that don't exist
            """

            # Get LLM configuration
            provider, api_token = self._get_llm_config(config)

            extraction_strategy = LLMExtractionStrategy(
                provider=provider,
                api_token=api_token,
                instruction=llm_instruction,
                schema={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "object",
                            "properties": {
                                "selector": {"type": "string"},
                                "type": {"type": "string"}
                            }
                        },
                        "address": {
                            "type": "object",
                            "properties": {
                                "selector": {"type": "string"},
                                "type": {"type": "string"}
                            }
                        },
                        "phone": {
                            "type": "object",
                            "properties": {
                                "selector": {"type": "string"},
                                "type": {"type": "string"},
                                "attribute": {"type": ["string", "null"]}
                            }
                        },
                        "website": {
                            "type": "object",
                            "properties": {
                                "selector": {"type": "string"},
                                "type": {"type": "string"},
                                "attribute": {"type": "string"}
                            }
                        },
                        "distance": {
                            "type": ["object", "null"],
                            "properties": {
                                "selector": {"type": "string"},
                                "type": {"type": "string"}
                            }
                        }
                    },
                    "required": ["name", "address", "phone", "website"]
                }
            )

            run_config = CrawlerRunConfig(
                session_id=session_id,
                extraction_strategy=extraction_strategy,
                js_only=True,
                page_timeout=60000,
                process_iframes=process_iframes,
                remove_overlay_elements=True
            )

            if self.verbose:
                print(f"  Data Field Discovery: Analyzing search results structure...")

            result = await crawler.arun(url=url, config=run_config)

            if result.success and result.extracted_content:
                data_fields = json.loads(result.extracted_content)

                if self.verbose:
                    print(f"  Data Field Discovery: Found selectors:")
                    for field_name, field_config in data_fields.items():
                        if field_config and isinstance(field_config, dict):
                            print(f"    - {field_name}: {field_config.get('selector', 'N/A')}")

                return data_fields
            else:
                if self.verbose:
                    print(f"  Data Field Discovery: Failed, using config defaults")
                return {}

        except Exception as e:
            if self.verbose:
                print(f"  Data Field Discovery failed: {e}")
            return {}

    async def discover_form_fields_with_llm(
        self,
        crawler: AsyncWebCrawler,
        url: str,
        config: Dict,
        process_iframes: bool = False,
        session_id: str = None
    ) -> Dict[str, str]:
        """
        Discover form field selectors using LLM analysis.

        Uses LLMExtractionStrategy to understand page content and identify:
        - Zip code input field (or postal code, location search)
        - Submit/search button
        - Optional: radius/distance selector
        - Optional: "View More" / "Load More" button

        Args:
            crawler: Active AsyncWebCrawler instance
            url: Page URL to analyze
            config: Configuration dict
            process_iframes: Whether to process iframe content (auto-detected)

        Returns:
            Dict with CSS selectors: {
                'zip_input': '#zipcode-input',
                'submit_button': 'button.search-btn',
                'view_more_button': 'button.load-more'  (optional),
                'dealer_cards': 'div.dealer-card'
            }
        """
        try:
            # Create LLM extraction strategy with specific instructions
            llm_instruction = """
            Analyze this dealer locator page and identify the form elements needed to search for dealers by zip code.

            You must identify:
            1. ZIP CODE INPUT: The input field where users enter their zip code, postal code, or location
               - Return the most specific CSS selector (prefer ID, then name, then class)
               - Example selectors: input#zipCode, input[name="postal"], input[placeholder*="zip"]

            2. SUBMIT BUTTON: The button that submits the dealer search
               - Return CSS selector for the primary search/submit button
               - Example selectors: button.search-btn, button[type="submit"], input[value="Search"]

            3. VIEW MORE BUTTON (optional): Button to load additional results
               - Return CSS selector if found
               - Common text: "View More", "Load More", "Show More", "See All"
               - Example selectors: button.load-more, a.show-more

            4. DEALER CARDS: The container/card that holds individual dealer information
               - Return CSS selector for each dealer result card
               - Example selectors: div.dealer-card, li.dealer-result, article.dealer

            Return JSON format:
            {
                "zip_input": "CSS_SELECTOR",
                "submit_button": "CSS_SELECTOR",
                "view_more_button": "CSS_SELECTOR or null",
                "dealer_cards": "CSS_SELECTOR"
            }

            Rules:
            - Use the MOST SPECIFIC selector possible (ID > name > class > tag)
            - Verify selectors are unique (no duplicates)
            - Consider accessibility attributes (aria-label, role)
            - For input fields, prefer selectors with type, name, or placeholder attributes
            - For buttons, check both <button> and <input type="submit">
            - Return null for optional fields if not found
            """

            # Get LLM configuration (reuses existing setup)
            provider, api_token = self._get_llm_config(config)

            extraction_strategy = LLMExtractionStrategy(
                provider=provider,
                api_token=api_token,
                instruction=llm_instruction,
                schema={
                    "type": "object",
                    "properties": {
                        "zip_input": {"type": "string"},
                        "submit_button": {"type": "string"},
                        "view_more_button": {"type": ["string", "null"]},
                        "dealer_cards": {"type": "string"}
                    },
                    "required": ["zip_input", "submit_button", "dealer_cards"]
                }
            )

            run_config = CrawlerRunConfig(
                session_id=session_id,  # Use same session to avoid re-navigation
                extraction_strategy=extraction_strategy,
                page_timeout=60000,
                process_iframes=process_iframes,  # Enable iframe processing if detected
                remove_overlay_elements=True  # Remove cookie popups and overlays
            )

            if self.verbose:
                print(f"  LLM Discovery: Analyzing page structure...")
                if process_iframes:
                    print(f"  LLM Discovery: Processing iframe content")

            result = await crawler.arun(url=url, config=run_config)

            if result.success and result.extracted_content:
                selectors = json.loads(result.extracted_content)

                # Validate that selectors were found
                if not selectors.get('zip_input'):
                    if self.verbose:
                        print(f"  LLM Discovery: Failed to identify zip code input field")
                    raise ValueError("LLM failed to identify zip code input field")
                if not selectors.get('submit_button'):
                    if self.verbose:
                        print(f"  LLM Discovery: Failed to identify submit button")
                    raise ValueError("LLM failed to identify submit button")

                if self.verbose:
                    print(f"  LLM Discovery: Found selectors:")
                    print(f"    - Zip input: {selectors.get('zip_input')}")
                    print(f"    - Submit button: {selectors.get('submit_button')}")
                    print(f"    - View more button: {selectors.get('view_more_button', 'N/A')}")
                    print(f"    - Dealer cards: {selectors.get('dealer_cards')}")

                return selectors
            else:
                if self.verbose:
                    print(f"  LLM Discovery: Failed to extract content")
                raise ValueError("LLM extraction failed")

        except Exception as e:
            if self.verbose:
                print(f"  LLM Discovery failed: {e}, falling back to config-based selectors")
            # Fallback to config-based selectors
            return self._get_selectors_from_config(config)

    def build_js_code_from_config(self, config: Dict, zip_code: str) -> str:
        """
        DEPRECATED: This method is deprecated in favor of LLM-based discovery.
        Use discover_form_fields_with_llm() instead.

        Kept for backward compatibility and as fallback when LLM is disabled.

        Build JavaScript code from configuration templates.

        Replaces placeholders:
        - {SEARCH_SELECTOR} -> actual search input selector
        - {ZIP_CODE} -> the zip code to search
        - {BUTTON_SELECTOR} -> search button selector
        - {LOAD_MORE_SELECTOR} -> load more button selector

        Args:
            config: Configuration dictionary with crawl4ai_interactions section
            zip_code: Zip code to search for

        Returns:
            JavaScript code to execute for search submission
        """
        interactions = config.get('crawl4ai_interactions', {})
        selectors = config.get('selectors', {})

        # Get selectors
        search_selector = selectors.get('search_input', [''])[0] if selectors.get('search_input') else ''
        button_selector = selectors.get('search_button', [''])[0] if selectors.get('search_button') else ''

        # Get search action template (with fallback to simple default)
        search_action = interactions.get('search_action', {})
        search_template = search_action.get('code_template', '')

        # Fallback if template is empty or malformed
        if not search_template or "''" in search_template:
            search_template = """
const input = document.querySelector('{SEARCH_SELECTOR}');
if (input) {
    input.value = '{ZIP_CODE}';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
}
"""

        # Get submit action template (with fallback)
        submit_action = interactions.get('search_submit', {})
        submit_template = submit_action.get('code_template', '')

        # Fallback if template is empty or malformed
        if not submit_template or "''" in submit_template:
            submit_template = """
const btn = document.querySelector('{BUTTON_SELECTOR}');
if (btn) {
    btn.click();
} else {
    const input = document.querySelector('{SEARCH_SELECTOR}');
    if (input) {
        input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true }));
    }
}
"""

        # Replace placeholders
        search_code = search_template.replace('{SEARCH_SELECTOR}', search_selector)
        search_code = search_code.replace('{ZIP_CODE}', zip_code)

        submit_code = submit_template.replace('{BUTTON_SELECTOR}', button_selector)
        submit_code = submit_code.replace('{SEARCH_SELECTOR}', search_selector)

        # Combine into full script
        full_script = f"""
(async () => {{
    // Fill search input
    {search_code}

    // Wait a bit for any autocomplete/validation
    await new Promise(r => setTimeout(r, 1000));

    // Submit search
    {submit_code}

    // Wait for results to load
    await new Promise(r => setTimeout(r, 2000));

    return true;
}})();
"""

        return full_script

    def build_load_more_js(self, config: Dict) -> str:
        """
        Build JavaScript for clicking "Load More" / "View More" buttons.

        Args:
            config: Configuration dictionary

        Returns:
            JavaScript code that clicks Load More button if visible
        """
        interactions = config.get('crawl4ai_interactions', {})
        selectors = config.get('selectors', {})

        load_more_selector = selectors.get('view_more_button', [''])[0] if selectors.get('view_more_button') else ''

        if not load_more_selector:
            return "return false;"

        load_more_action = interactions.get('load_more_action', {})
        template = load_more_action.get('code_template', '')

        if template:
            js_code = template.replace('{LOAD_MORE_SELECTOR}', load_more_selector)
        else:
            # Default implementation
            js_code = f"""
const btn = document.querySelector('{load_more_selector}');
if (btn && btn.offsetParent !== null) {{
    btn.click();
    await new Promise(r => setTimeout(r, 1500));
    return true;
}}
return false;
"""

        return js_code

    async def scrape_with_search(
        self,
        url: str,
        zip_code: str,
        config: Dict,
        expand_results: bool = True
    ) -> Optional[str]:
        """
        Scrape dealer locator page with zip code search using LLM-based discovery.

        New Workflow:
        1. Navigate to URL and discover form fields with LLM
        2. Fill search input with zip code (session-based)
        3. Submit search and wait for dealer cards
        4. Optionally expand results (Load More / scroll)
        5. Return final HTML

        Args:
            url: Dealer locator URL
            zip_code: Zip code to search
            config: Configuration dictionary
            expand_results: Whether to click "View More" buttons

        Returns:
            HTML string of search results page, or None if failed
        """
        session_id = f"dealer_search_{zip_code}_{id(self)}"

        try:
            # Check if config specifies direct URL navigation (bypasses form submission)
            use_direct_url = config.get('interactions', {}).get('use_direct_url', False)
            url_template = config.get('interactions', {}).get('url_template', '')

            if use_direct_url and url_template:
                # Use direct URL navigation instead of form submission
                if self.verbose:
                    print(f"  Using direct URL navigation (bypassing form submission)")

                direct_url = url_template.replace('{ZIP_CODE}', zip_code)
                if self.verbose:
                    print(f"  Direct URL: {direct_url}")

                browser_config = BrowserConfig(
                    headless=self.headless,
                    verbose=self.verbose
                )

                async with AsyncWebCrawler(config=browser_config) as crawler:
                    # Wait longer for AJAX-loaded dealers
                    wait_time = config.get('interactions', {}).get('wait_after_page_load', 15)

                    run_config = CrawlerRunConfig(
                        page_timeout=45000,  # 45 second timeout
                        delay_before_return_html=wait_time,  # Wait for AJAX dealers
                        js_code="""
                        // Wait for dealer cards to load
                        (async () => {
                            console.log('[DEBUG] Waiting for dealers to load via AJAX...');

                            const maxWait = 30;  // 30 seconds

                            for (let i = 0; i < maxWait; i++) {
                                await new Promise(r => setTimeout(r, 1000));

                                // Look for phone numbers (tel: links) as indicator dealers loaded
                                const phones = document.querySelectorAll('a[href^="tel:"]');

                                // Look for specific dealer-related text
                                const bodyText = document.body.innerText.toLowerCase();
                                const hasDistances = bodyText.includes('mi away') || bodyText.includes('miles') || bodyText.includes('mi.');

                                // Look for various dealer card selectors
                                const possibleCards = document.querySelectorAll(
                                    'li.dealer-results-item, .dealer-card, .dealer-listing, [data-dealer-id], ' +
                                    '[class*="dealer-result"], li[role="listitem"]'
                                );

                                if (phones.length > 2) {  // More than just help line numbers
                                    console.log(`[DEBUG] Found ${phones.length} phone numbers after ${i+1}s`);
                                    console.log('[DEBUG] Has distances:', hasDistances);
                                    console.log('[DEBUG] Possible dealer cards:', possibleCards.length);

                                    if (hasDistances || possibleCards.length > 5) {
                                        console.log('[DEBUG] Dealer data appears to be loaded!');
                                        await new Promise(r => setTimeout(r, 2000));  // Wait 2 more seconds
                                        return true;
                                    }
                                }

                                if (i % 5 === 0 && i > 0) {
                                    console.log(`[DEBUG] Still waiting... (${i+1}s, phones: ${phones.length}, distances: ${hasDistances})`);
                                }
                            }

                            console.log('[DEBUG] Timeout - dealers may not have loaded');
                            return false;
                        })();
                        """
                    )

                    result = await crawler.arun(url=direct_url, config=run_config)

                    if result.success:
                        if self.verbose:
                            print(f"  Successfully loaded direct URL (HTML length: {len(result.html)} chars)")

                        return result.html
                    else:
                        print(f"  Failed to load direct URL: {result.error_message if hasattr(result, 'error_message') else 'Unknown'}")
                        return None

            # Configure browser
            browser_config = BrowserConfig(
                headless=self.headless,
                verbose=self.verbose
            )

            async with AsyncWebCrawler(config=browser_config) as crawler:
                # Step 1: Navigate and discover form fields with LLM
                if self.verbose:
                    print(f"  Navigating to {url}")
                    print(f"  Executing search for zip code: {zip_code}")

                # Check if page has iframes and enable iframe processing if needed
                initial_config = CrawlerRunConfig(
                    session_id=session_id,  # CRITICAL: Use session_id from the start
                    page_timeout=30000,
                    delay_before_return_html=3  # Wait for JS to load and render
                )
                initial_result = await crawler.arun(url=url, config=initial_config)

                has_iframes = False
                if initial_result.success and initial_result.html:
                    has_iframes = '<iframe' in initial_result.html.lower()
                    if has_iframes and self.verbose:
                        print(f"  Detected iframes on page, enabling iframe processing")

                    # Log the initial HTML length to verify page loaded
                    if self.verbose:
                        print(f"  Initial HTML length: {len(initial_result.html)} characters")

                discovered_selectors = await self.discover_form_fields_with_llm(crawler, url, config, has_iframes, session_id)

                # Validate LLM results
                if not discovered_selectors.get('zip_input'):
                    if self.verbose:
                        print(f"  Warning: No zip input discovered, falling back to config")
                    discovered_selectors = self._get_selectors_from_config(config)

                # Step 2: Fill form with LLM-discovered selectors
                # Escape selectors for JavaScript
                zip_input_selector = self._escape_js_string(discovered_selectors['zip_input'])

                fill_js = f"""
                console.log('[DEBUG] Looking for zip input with selector:', '{zip_input_selector}');
                const input = document.querySelector('{zip_input_selector}');
                if (input) {{
                    console.log('[DEBUG] Found zip input:', input);
                    console.log('[DEBUG] Input type:', input.type, 'Current value:', input.value);
                    input.value = '{zip_code}';
                    input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    input.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    console.log('[DEBUG] Filled zip code:', input.value);
                }} else {{
                    console.error('[DEBUG] Zip input NOT FOUND with selector:', '{zip_input_selector}');
                    // Try to find any input that might be the zip code field
                    const allInputs = document.querySelectorAll('input');
                    console.log('[DEBUG] All input fields on page:', allInputs.length);
                    allInputs.forEach((inp, idx) => {{
                        console.log(`[DEBUG] Input ${{idx}}:`, inp.type, inp.name, inp.placeholder, inp.id);
                    }});
                }}
                """

                config_fill = CrawlerRunConfig(
                    session_id=session_id,
                    js_code=fill_js,
                    js_only=True,
                    page_timeout=30000,
                    process_iframes=has_iframes,
                    remove_overlay_elements=True
                )

                fill_result = await crawler.arun(url=url, config=config_fill)

                if not fill_result.success:
                    if self.verbose:
                        print(f"  Warning: Form fill failed")

                # Step 3: Submit form and wait for dealer cards
                # Escape selectors for JavaScript
                submit_button_selector = self._escape_js_string(discovered_selectors['submit_button'])
                dealer_card_selector = self._escape_js_string(discovered_selectors.get('dealer_cards', '.dealer-card'))

                submit_js = f"""
                (async () => {{
                    console.log('[DEBUG] Looking for submit button');

                    // First, try to find the right button by text content (more reliable than generic selector)
                    const allButtons = Array.from(document.querySelectorAll('button'));
                    console.log('[DEBUG] All buttons on page:', allButtons.length);

                    // Try to find buttons with search-related text, excluding "Advanced Search"
                    const searchButtons = allButtons.filter(b => {{
                        const text = b.textContent.trim().toLowerCase();
                        const isVisible = b.offsetParent !== null;
                        const isNotAdvanced = !text.includes('advanced');
                        const isSearchRelated = text.includes('search') || text.includes('find') || text.includes('locate') || text === '' && b.type === 'submit';

                        console.log(`[DEBUG] Button: "${{text}}", visible: ${{isVisible}}, notAdvanced: ${{isNotAdvanced}}, searchRelated: ${{isSearchRelated}}`);

                        return isVisible && isNotAdvanced && (isSearchRelated || b.type === 'submit' && !text.includes('adv'));
                    }});

                    console.log('[DEBUG] Found', searchButtons.length, 'potential search buttons');

                    let btn = null;

                    // Prioritize buttons with explicit search text
                    const explicitSearchBtn = searchButtons.find(b => {{
                        const text = b.textContent.trim().toLowerCase();
                        return text === 'search' || text === 'find dealers' || text === 'locate';
                    }});

                    if (explicitSearchBtn) {{
                        btn = explicitSearchBtn;
                        console.log('[DEBUG] Using explicit search button:', btn.textContent.trim());
                    }} else if (searchButtons.length > 0) {{
                        btn = searchButtons[0];
                        console.log('[DEBUG] Using first available button:', btn.textContent.trim());
                    }} else {{
                        // Fallback to original selector
                        btn = document.querySelector('{submit_button_selector}');
                        if (btn) {{
                            console.log('[DEBUG] Using fallback selector button:', btn.textContent.trim());
                        }}
                    }}

                    if (btn) {{
                        console.log('[DEBUG] Final button selected:', btn.textContent.trim());
                        console.log('[DEBUG] Button type:', btn.type);
                        console.log('[DEBUG] Button visible:', btn.offsetParent !== null);

                        // Check if button is inside a form with an action
                        const form = btn.closest('form');
                        if (form) {{
                            console.log('[DEBUG] Button is in a form');
                            console.log('[DEBUG] Form action:', form.action || '(none)');
                            console.log('[DEBUG] Form method:', form.method || '(none)');

                            // Prevent form submission/navigation
                            form.addEventListener('submit', (e) => {{
                                console.log('[DEBUG] Preventing form submission');
                                e.preventDefault();
                                return false;
                            }}, {{ capture: true }});
                        }}

                        btn.click();
                        console.log('[DEBUG] Clicked button');

                        // Wait a bit to see if Advanced Search modal opened or results loaded
                        await new Promise(r => setTimeout(r, 2000));

                        // Check if Advanced Search modal/filters appeared and need to be dismissed
                        const applyButtons = Array.from(document.querySelectorAll('button')).filter(b => {{
                            const text = b.textContent.trim().toLowerCase();
                            const isVisible = b.offsetParent !== null;
                            return isVisible && (text === 'apply' || text === 'done' || text === 'close');
                        }});

                        if (applyButtons.length > 0) {{
                            console.log('[DEBUG] Found Apply/Done/Close button, clicking it to dismiss modal');
                            applyButtons[0].click();
                            console.log('[DEBUG] Clicked Apply button');
                            await new Promise(r => setTimeout(r, 1000));
                        }}
                    }} else {{
                        console.error('[DEBUG] Submit button NOT FOUND with selector:', '{submit_button_selector}');
                        // Try to find any button that might be the submit button
                        const allButtons = document.querySelectorAll('button');
                        console.log('[DEBUG] All buttons on page:', allButtons.length);
                        allButtons.forEach((b, idx) => {{
                            console.log(`[DEBUG] Button ${{idx}}:`, b.type, b.textContent.trim(), b.className);
                        }});

                        // Fallback to Enter key
                        console.log('[DEBUG] Trying Enter key fallback');
                        const input = document.querySelector('{zip_input_selector}');
                        if (input) {{
                            console.log('[DEBUG] Pressing Enter on input');
                            input.dispatchEvent(new KeyboardEvent('keydown', {{
                                key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true
                            }}));
                            input.dispatchEvent(new KeyboardEvent('keypress', {{
                                key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true
                            }}));
                        }} else {{
                            console.error('[DEBUG] Cannot press Enter - input not found');
                        }}
                    }}

                    // Wait for dealer cards to appear after submit
                    console.log('[DEBUG] Waiting for dealer cards with selector:', '{dealer_card_selector}');
                    const maxWait = 30; // 30 seconds max
                    for (let i = 0; i < maxWait; i++) {{
                        await new Promise(r => setTimeout(r, 1000));
                        const cards = document.querySelectorAll('{dealer_card_selector}');
                        if (cards && cards.length > 0) {{
                            console.log(`[DEBUG] Found ${{cards.length}} dealer cards after ${{i+1}} seconds`);
                            return true;
                        }}

                        // Every 5 seconds, try to find potential dealer elements
                        if (i % 5 === 0) {{
                            const anyCards = document.querySelectorAll('[class*="dealer"], [class*="location"], [class*="result"], [class*="store"], li, article');
                            console.log(`[DEBUG] After ${{i+1}}s - Potential dealer elements found:`, anyCards.length);

                            // Check if URL changed (indicates navigation happened)
                            console.log('[DEBUG] Current URL:', window.location.href);
                        }}
                    }}

                    console.error('[DEBUG] Timeout - no dealer cards found after 30 seconds');
                    console.log('[DEBUG] Final URL:', window.location.href);

                    // Try finding ANY elements that might be dealer cards
                    const anyCards = document.querySelectorAll('[class*="dealer"], [class*="location"], [class*="result"], [class*="store"]');
                    console.log('[DEBUG] Found', anyCards.length, 'potential dealer elements');
                    if (anyCards.length > 0) {{
                        console.log('[DEBUG] Sample element classes:', anyCards[0].className);
                    }}

                    return false;
                }})();
                """

                config_submit = CrawlerRunConfig(
                    session_id=session_id,
                    js_code=submit_js,
                    js_only=True,
                    wait_until="networkidle",
                    delay_before_return_html=2,
                    page_timeout=60000,
                    process_iframes=has_iframes,
                    remove_overlay_elements=True
                )

                result = await crawler.arun(url=url, config=config_submit)

                if not result.success:
                    print(f"  Crawl failed: {result.error_message if hasattr(result, 'error_message') else 'Unknown error'}")
                    # Clean up session
                    try:
                        await crawler.crawler_strategy.kill_session(session_id)
                    except:
                        pass
                    return None

                html = result.html

                # Check if dealer cards appeared
                soup = BeautifulSoup(html, 'html.parser')
                cards = soup.select(dealer_card_selector)

                if not cards:
                    print(f"  Warning: No dealer cards found after search (selector: {dealer_card_selector})")

                    # Save HTML for debugging
                    import os
                    from urllib.parse import urlparse
                    domain = urlparse(url).netloc.replace('www.', '')
                    debug_dir = os.path.join(os.getcwd(), 'debug_html')
                    os.makedirs(debug_dir, exist_ok=True)
                    debug_path = os.path.join(debug_dir, f"{domain}_{zip_code}_debug.html")

                    with open(debug_path, 'w', encoding='utf-8') as f:
                        f.write(f"<!-- Debug HTML for {domain} with zip {zip_code} -->\n")
                        f.write(f"<!-- Searched for dealer cards with selector: {dealer_card_selector} -->\n")
                        f.write(f"<!-- Zip input selector: {zip_input_selector} -->\n")
                        f.write(f"<!-- Submit button selector: {submit_button_selector} -->\n")
                        f.write(html)

                    print(f"  DEBUG: Saved HTML to {debug_path}")

                    # Try heuristic discovery of dealer cards
                    heuristic_patterns = [
                        '[class*="dealer"]', '[class*="location"]', '[class*="result"]',
                        '[class*="store"]', '[data-dealer-id]', '[data-location-id]',
                        'article[class*="result"]', 'li[class*="location"]',
                        'div[itemtype*="LocalBusiness"]'
                    ]

                    for pattern in heuristic_patterns:
                        potential_cards = soup.select(pattern)
                        if len(potential_cards) >= 3:
                            print(f"  DEBUG: Heuristic found {len(potential_cards)} potential cards with: {pattern}")
                            break

                    # Continue anyway - post-validation will catch this

                # Step 3.5: RE-ANALYZE the search results page with LLM to discover data field selectors
                if self.verbose:
                    print(f"  Re-analyzing search results page to discover data field selectors...")

                data_field_selectors = await self._discover_data_fields_with_llm(
                    crawler, url, config, session_id, has_iframes
                )

                if data_field_selectors:
                    # Update discovered_selectors with the data field information
                    discovered_selectors['data_fields'] = data_field_selectors
                    if self.verbose:
                        print(f"  Discovered data fields: {list(data_field_selectors.keys())}")

                # Step 4: Expand results if needed (with LLM-discovered View More selector)
                if expand_results:
                    pagination_type = config.get('interactions', {}).get('pagination_type', 'none')

                    if pagination_type == 'view_more':
                        html = await self._expand_with_view_more(
                            crawler, url, html, discovered_selectors, session_id, has_iframes
                        )
                    elif pagination_type == 'virtual_scroll':
                        html = await self._expand_with_virtual_scroll(
                            crawler, url, config, session_id, has_iframes
                        )
                    elif pagination_type == 'scroll':
                        html = await self._expand_with_scroll(
                            crawler, url, config, session_id, has_iframes
                        )

                if self.verbose:
                    print(f"  Final HTML length: {len(html)} characters")

                # Store discovered selectors in HTML as a data attribute for later use
                # This is a workaround to pass the discovered selectors back to the caller
                if discovered_selectors.get('data_fields'):
                    # Inject discovered selectors as JSON comment at the start of HTML
                    selector_json = json.dumps(discovered_selectors)
                    html = f"<!-- DISCOVERED_SELECTORS: {selector_json} -->\n{html}"

                # Clean up session (but NOT in headless=False mode to keep browser open)
                if self.headless:
                    try:
                        await crawler.crawler_strategy.kill_session(session_id)
                    except Exception as e:
                        if self.verbose:
                            print(f"  Warning: Failed to kill session: {e}")
                else:
                    if self.verbose:
                        print(f"  Keeping session open for inspection (headless=False)")

                return html

        except Exception as e:
            print(f"  Crawl4AI scraping error: {e}")
            if self.verbose:
                import traceback
                traceback.print_exc()
            return None

    async def _expand_with_view_more(
        self,
        crawler: AsyncWebCrawler,
        url: str,
        html: str,
        discovered_selectors: Dict[str, str],
        session_id: str,
        process_iframes: bool = False
    ) -> str:
        """
        Click "View More" / "Load More" buttons using LLM-discovered selector.

        Args:
            crawler: Active crawler instance
            url: Current URL
            html: Current HTML
            discovered_selectors: Dict with 'view_more_button' key from LLM discovery
            session_id: Session ID to maintain browser state
            process_iframes: Whether to process iframe content

        Returns:
            Expanded HTML with all results
        """
        view_more_selector = discovered_selectors.get('view_more_button')

        if not view_more_selector:
            if self.verbose:
                print("  No View More button discovered by LLM, skipping expansion")
            return html

        if self.verbose:
            print(f"  Attempting to expand results with View More button (selector: {view_more_selector})")

        # Build click script using LLM-discovered selector
        # Escape selector for JavaScript
        view_more_escaped = self._escape_js_string(view_more_selector)

        load_more_js = f"""
        const btn = document.querySelector('{view_more_escaped}');
        if (btn && btn.offsetParent !== null) {{
            btn.click();
            await new Promise(r => setTimeout(r, 1500));
            return true;
        }}
        return false;
        """

        max_clicks = 30  # Maximum expansion iterations

        for i in range(max_clicks):
            run_config = RunConfig(
                session_id=session_id,
                js_code=load_more_js,
                js_only=True,
                wait_until="domcontentloaded",
                page_timeout=60000,
                delay_before_return_html=1,
                process_iframes=process_iframes,
                remove_overlay_elements=True
            )

            result = await crawler.arun(url=url, config=run_config)

            if result.success:
                new_html = result.html
                if len(new_html) > len(html):
                    if self.verbose:
                        print(f"    Click {i+1}: Loaded more dealers (+{len(new_html) - len(html)} chars)")
                    html = new_html
                else:
                    if self.verbose:
                        print(f"    Click {i+1}: No more dealers to load")
                    break
            else:
                break

        return html

    async def _expand_with_virtual_scroll(
        self,
        crawler: AsyncWebCrawler,
        url: str,
        config: Dict,
        session_id: str,
        process_iframes: bool = False
    ) -> str:
        """
        Use virtual scrolling for infinite scroll pages.

        Args:
            crawler: Active crawler instance
            url: Current URL
            config: Configuration
            session_id: Session ID to maintain browser state
            process_iframes: Whether to process iframe content

        Returns:
            HTML after virtual scrolling
        """
        virtual_scroll_config = config.get('crawl4ai_interactions', {}).get('virtual_scroll', {})

        if not virtual_scroll_config.get('enabled', False):
            return await self._expand_with_scroll(crawler, url, config, session_id, process_iframes)

        scroll_count = virtual_scroll_config.get('scroll_count', 30)
        container_selector = virtual_scroll_config.get('container_selector', 'body')

        if self.verbose:
            print(f"  Using virtual scroll (container: {container_selector}, scrolls: {scroll_count})")

        # Build scroll script
        # Escape selector for JavaScript
        container_escaped = self._escape_js_string(container_selector)

        scroll_js = f"""
(async () => {{
    const container = document.querySelector('{container_escaped}');
    if (!container) return false;

    for (let i = 0; i < {scroll_count}; i++) {{
        container.scrollTop += container.clientHeight;
        await new Promise(r => setTimeout(r, 500));
    }}

    return true;
}})();
"""

        run_config = RunConfig(
            session_id=session_id,
            js_code=scroll_js,
            js_only=True,
            wait_until="domcontentloaded",
            page_timeout=60000,
            delay_before_return_html=2,
            process_iframes=process_iframes,
            remove_overlay_elements=True
        )

        result = await crawler.arun(url=url, config=run_config)

        if result.success:
            return result.html
        else:
            return ""

    async def _expand_with_scroll(
        self,
        crawler: AsyncWebCrawler,
        url: str,
        config: Dict,
        session_id: str,
        process_iframes: bool = False
    ) -> str:
        """
        Use regular scrolling to load lazy-loaded content.

        Args:
            crawler: Active crawler instance
            url: Current URL
            config: Configuration
            session_id: Session ID to maintain browser state
            process_iframes: Whether to process iframe content

        Returns:
            HTML after scrolling
        """
        scroll_count = config.get('interactions', {}).get('max_scroll_attempts', 10)

        if self.verbose:
            print(f"  Using regular scroll (scrolls: {scroll_count})")

        scroll_js = f"""
(async () => {{
    for (let i = 0; i < {scroll_count}; i++) {{
        window.scrollBy(0, window.innerHeight);
        await new Promise(r => setTimeout(r, 500));
    }}

    return true;
}})();
"""

        run_config = RunConfig(
            session_id=session_id,
            js_code=scroll_js,
            js_only=True,
            wait_until="domcontentloaded",
            page_timeout=60000,
            delay_before_return_html=2,
            process_iframes=process_iframes,
            remove_overlay_elements=True
        )

        result = await crawler.arun(url=url, config=run_config)

        if result.success:
            return result.html
        else:
            return ""


# Test function
async def test_scraper():
    """Test Crawl4AI scraper on a known dealer locator."""
    config = {
        'selectors': {
            'search_input': ['#searchbox'],
            'search_button': ['button[type="submit"]'],
            'dealer_cards': ['.dealer-card', '.result-item']
        },
        'crawl4ai_interactions': {
            'search_action': {
                'code_template': """
                    const input = document.querySelector('{SEARCH_SELECTOR}');
                    if (input) {
                        input.value = '{ZIP_CODE}';
                        input.dispatchEvent(new Event('input', { bubbles: true }));
                    }
                """,
                'wait_after': 2,
                'wait_for': 'css:.dealer-card'
            },
            'search_submit': {
                'code_template': """
                    const btn = document.querySelector('{BUTTON_SELECTOR}');
                    if (btn) btn.click();
                """
            }
        },
        'interactions': {
            'pagination_type': 'view_more'
        }
    }

    scraper = Crawl4AIScraper(headless=False, verbose=True)

    html = await scraper.scrape_with_search(
        url="https://www.ford.com/dealerships/",
        zip_code="10001",
        config=config
    )

    if html:
        print(f"\nScrape successful! HTML length: {len(html)}")
        soup = BeautifulSoup(html, 'html.parser')
        cards = soup.select('.dealer-card')
        print(f"Found {len(cards)} dealer cards")
    else:
        print("\nScrape failed")


if __name__ == "__main__":
    asyncio.run(test_scraper())
