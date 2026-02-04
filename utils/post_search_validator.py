"""
Post-search validation for dealer scraper.

After executing a search, this module validates that dealer cards appeared
and refines selectors if the initial LLM analysis was incorrect.

This runs ONCE per domain to improve accuracy.
"""

from typing import Dict, Optional
from bs4 import BeautifulSoup


class PostSearchValidator:
    """Validates search results and refines selectors based on actual HTML."""

    def __init__(self):
        """Initialize post-search validator."""
        self.validation_cache = {}  # domain -> validation result

    def validate_search_results(
        self,
        html: str,
        url: str,
        expected_config: Dict
    ) -> Dict:
        """
        Validate that search results contain dealer cards.

        Args:
            html: HTML from post-search page
            url: Dealer locator URL
            expected_config: Configuration with expected selectors

        Returns:
            Dictionary with:
            - dealers_found: bool
            - selectors_correct: bool
            - confidence: float (0.0-1.0)
            - needs_refinement: bool
            - suggested_selectors: Dict (if refinement needed)
            - dealer_count: int
        """
        soup = BeautifulSoup(html, 'html.parser')

        # Check expected dealer card selectors
        expected_card_selectors = expected_config.get('selectors', {}).get('dealer_cards', [])
        cards_found = []

        for selector in expected_card_selectors:
            try:
                cards = soup.select(selector)
                if cards:
                    cards_found.extend(cards)
                    break  # Found dealers with this selector
            except Exception as e:
                print(f"Selector error: {selector} - {e}")
                continue

        dealers_found = len(cards_found) > 0
        selectors_correct = dealers_found  # Simplification for now

        if dealers_found:
            print(f"Post-search validation: Found {len(cards_found)} dealers with expected selectors")
            return {
                'dealers_found': True,
                'selectors_correct': True,
                'confidence': 0.9,
                'needs_refinement': False,
                'dealer_count': len(cards_found),
                'notes': f"Found {len(cards_found)} dealers"
            }
        else:
            print("Post-search validation: No dealers found with expected selectors, analyzing HTML...")

            # Try to find dealer cards using heuristics
            suggested = self._analyze_html_for_dealers(soup, html)

            if suggested['dealer_count'] > 0:
                print(f"Found {suggested['dealer_count']} dealers with alternative selectors")
                return {
                    'dealers_found': True,
                    'selectors_correct': False,
                    'confidence': suggested['confidence'],
                    'needs_refinement': True,
                    'suggested_selectors': suggested['selectors'],
                    'dealer_count': suggested['dealer_count'],
                    'notes': suggested['notes']
                }
            else:
                print("No dealers found even with heuristic analysis")
                return {
                    'dealers_found': False,
                    'selectors_correct': False,
                    'confidence': 0.1,
                    'needs_refinement': True,
                    'dealer_count': 0,
                    'notes': 'No dealer cards detected in HTML'
                }

    def _analyze_html_for_dealers(self, soup: BeautifulSoup, html: str) -> Dict:
        """
        Heuristic analysis to find dealer cards when expected selectors fail.

        Looks for:
        - Repeated elements (likely cards/list items)
        - Elements containing dealer-related text (address, phone, name)
        - Common patterns (dealer-*, result-*, card-*, location-*)

        Args:
            soup: BeautifulSoup object
            html: Raw HTML

        Returns:
            Dictionary with suggested selectors and confidence
        """
        # Try common dealer card class patterns
        common_patterns = [
            '[class*="dealer"]',
            '[class*="location"]',
            '[class*="store"]',
            '[class*="result"]',
            '[class*="card"]',
            '[class*="listing"]',
            'li[class*="item"]',
            'div[class*="item"]'
        ]

        best_selector = None
        max_count = 0
        best_elements = []

        for pattern in common_patterns:
            try:
                elements = soup.select(pattern)

                # Filter to elements with substantial content (likely dealer cards, not UI elements)
                substantial = [el for el in elements if len(el.get_text(strip=True)) > 50]

                if len(substantial) > max_count and len(substantial) > 2:
                    max_count = len(substantial)
                    best_selector = pattern
                    best_elements = substantial
            except Exception:
                continue

        if best_selector and max_count > 0:
            # Verify these look like dealer cards (contain address/phone patterns)
            dealer_like_count = 0
            for el in best_elements[:5]:  # Check first 5
                text = el.get_text()
                # Look for address patterns (state abbreviations, zip codes)
                if any(state in text for state in ['CA', 'NY', 'TX', 'FL', 'IL']) or \
                   any(char.isdigit() for char in text):  # Contains numbers (likely address/phone)
                    dealer_like_count += 1

            confidence = min(0.9, dealer_like_count / 5.0 + 0.4)

            print(f"Heuristic found {max_count} potential dealers with selector: {best_selector}")

            return {
                'selectors': {
                    'dealer_cards': [best_selector]
                },
                'confidence': confidence,
                'dealer_count': max_count,
                'notes': f'Found {max_count} cards using heuristic pattern: {best_selector}'
            }
        else:
            return {
                'selectors': {},
                'confidence': 0.1,
                'dealer_count': 0,
                'notes': 'No dealer cards found with heuristics'
            }

    def refine_selectors(self, validation: Dict, original_config: Dict) -> Dict:
        """
        Refine configuration based on validation results.

        Args:
            validation: Result from validate_search_results()
            original_config: Original configuration

        Returns:
            Refined configuration with updated selectors
        """
        if not validation.get('needs_refinement'):
            return original_config

        if not validation.get('suggested_selectors'):
            print("Warning: Refinement needed but no suggestions available")
            return original_config

        # Create refined config
        refined_config = original_config.copy()

        # Update dealer card selectors
        suggested_cards = validation['suggested_selectors'].get('dealer_cards', [])
        if suggested_cards:
            print(f"Refining dealer card selectors: {suggested_cards}")
            refined_config['selectors']['dealer_cards'] = suggested_cards

        # Update confidence metadata
        if 'metadata' not in refined_config:
            refined_config['metadata'] = {}

        refined_config['metadata']['post_search_validated'] = True
        refined_config['metadata']['validation_confidence'] = validation.get('confidence', 0.0)
        refined_config['metadata']['dealer_count'] = validation.get('dealer_count', 0)
        refined_config['metadata']['validation_notes'] = validation.get('notes', '')

        return refined_config

    def refine_selectors_with_llm(
        self,
        html: str,
        url: str,
        original_config: Dict
    ) -> Dict:
        """
        Use LLM to analyze post-search HTML and refine selectors.

        This is more accurate than heuristics but slower.
        Called only when heuristic validation fails.

        Args:
            html: Post-search HTML
            url: Dealer locator URL
            original_config: Original configuration

        Returns:
            Refined configuration
        """
        from .llm_analyzer import LLMAnalyzer

        llm = LLMAnalyzer()

        # Truncate HTML for LLM
        soup = BeautifulSoup(html, 'html.parser')
        text_content = soup.get_text(separator='\n', strip=True)[:8000]

        # Extract sample HTML snippets for common dealer-related elements
        sample_snippets = []
        for pattern in ['[class*="dealer"]', '[class*="location"]', '[class*="result"]']:
            elements = soup.select(pattern)[:2]
            for el in elements:
                snippet = str(el)[:500]  # First 500 chars
                sample_snippets.append(snippet)

        prompt = f"""Analyze this dealer locator page AFTER a zip code search was submitted.

URL: {url}

Expected dealer card selectors: {original_config['selectors']['dealer_cards']}
Expected data fields: {original_config.get('data_fields', {})}

Sample HTML snippets from the page:
{chr(10).join(f"---{chr(10)}{s}{chr(10)}" for s in sample_snippets[:5])}

Page text content (first 8000 chars):
{text_content}

Questions:
1. Did dealer cards/results appear on the page?
2. What CSS selectors should be used to find dealer cards?
3. How confident are you? (0.0-1.0)

Return ONLY valid JSON:
{{
  "dealers_found": true,
  "dealer_cards_selector": ".actual-dealer-card-class",
  "data_fields": {{
    "name": {{"selector": "h3.dealer-name", "type": "text"}},
    "address": {{"selector": ".address", "type": "text"}},
    "phone": {{"selector": "a.phone", "type": "href", "attribute": "href"}},
    "website": {{"selector": "a.website", "type": "href", "attribute": "href"}}
  }},
  "confidence": 0.85,
  "notes": "Found dealers with this selector..."
}}
"""

        try:
            response = llm._call_llm(prompt, max_tokens=2000)
            result = llm._parse_json_response(response)

            if result and result.get('dealers_found'):
                print(f"LLM refinement: confidence {result.get('confidence', 0.0)}")

                # Update config with LLM suggestions
                refined_config = original_config.copy()
                refined_config['selectors']['dealer_cards'] = [result['dealer_cards_selector']]

                if 'data_fields' in result:
                    refined_config['data_fields'] = result['data_fields']

                # Add metadata
                if 'metadata' not in refined_config:
                    refined_config['metadata'] = {}

                refined_config['metadata']['post_search_validated'] = True
                refined_config['metadata']['llm_refined'] = True
                refined_config['metadata']['validation_confidence'] = result.get('confidence', 0.0)
                refined_config['metadata']['validation_notes'] = result.get('notes', '')

                return refined_config
            else:
                print("LLM could not find dealer cards")
                return original_config

        except Exception as e:
            print(f"LLM refinement failed: {e}")
            return original_config


# Test function
def test_validator():
    """Test validator with sample HTML."""
    sample_html = """
    <html>
    <body>
        <div class="dealer-result">
            <h3>Bob's Auto Dealership</h3>
            <p class="address">123 Main St, New York, NY 10001</p>
            <a href="tel:555-1234">(555) 123-4567</a>
        </div>
        <div class="dealer-result">
            <h3>Jane's Car Store</h3>
            <p class="address">456 Elm St, New York, NY 10002</p>
            <a href="tel:555-5678">(555) 567-8901</a>
        </div>
    </body>
    </html>
    """

    config = {
        'selectors': {
            'dealer_cards': ['.dealer-card']  # Wrong selector
        }
    }

    validator = PostSearchValidator()

    # Should detect wrong selector and suggest .dealer-result
    validation = validator.validate_search_results(sample_html, "https://example.com", config)

    print("\nValidation Result:")
    print(f"  Dealers Found: {validation['dealers_found']}")
    print(f"  Selectors Correct: {validation['selectors_correct']}")
    print(f"  Needs Refinement: {validation['needs_refinement']}")
    print(f"  Confidence: {validation['confidence']}")

    if validation['needs_refinement']:
        refined = validator.refine_selectors(validation, config)
        print(f"\nRefined Selectors:")
        print(f"  {refined['selectors']['dealer_cards']}")


if __name__ == "__main__":
    test_validator()
