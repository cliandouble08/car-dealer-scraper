#!/usr/bin/env python3
"""
LLM Page Analyzer

Analyzes page content using local LLM (Ollama) to extract scraping patterns
and selectors for dealer locator websites.
"""

import os
import json
import re
import requests
from typing import Dict, Any, Optional
from urllib.parse import urlparse


class LLMAnalyzer:
    """Analyzes page structure using local LLM to extract scraping patterns."""

    DEFAULT_ENDPOINT = "http://localhost:11434/api/generate"
    DEFAULT_MODEL = "gemma2:2b"  # Using Gemma2 2B (fast, no thinking mode)
    DEFAULT_TIMEOUT = 120  # Timeout for LLM analysis

    def __init__(
        self,
        endpoint: Optional[str] = None,
        model: Optional[str] = None,
        enabled: bool = True
    ):
        """
        Initialize LLM analyzer.

        Args:
            endpoint: Ollama API endpoint (default: http://localhost:11434/api/generate)
            model: Model name (default: llama3)
            enabled: Whether LLM analysis is enabled
        """
        self.enabled = enabled and os.getenv('LLM_ANALYSIS_ENABLED', 'true').lower() == 'true'
        self.endpoint = endpoint or os.getenv('LLM_ENDPOINT', self.DEFAULT_ENDPOINT)
        self.model = model or os.getenv('LLM_MODEL', self.DEFAULT_MODEL)
        self.timeout = int(os.getenv('LLM_TIMEOUT', str(self.DEFAULT_TIMEOUT)))

    def analyze_page_structure(self, content: str, url: str) -> Optional[Dict[str, Any]]:
        """
        Analyze page content and extract scraping patterns.

        Args:
            content: LLM-friendly page content (from Jina Reader)
            url: Original URL for context

        Returns:
            Dictionary with selectors, interactions, and extraction patterns
        """
        if not self.enabled:
            return None

        if not content or len(content) < 100:
            print("Warning: Content too short for LLM analysis")
            return None

        prompt = self._build_analysis_prompt(content, url)

        try:
            response = self._call_llm(prompt)
            if not response:
                return None

            analysis = self._parse_llm_response(response)
            return analysis

        except Exception as e:
            print(f"Error during LLM analysis: {e}")
            return None

    def _build_analysis_prompt(self, content: str, url: str) -> str:
        """
        Build structured prompt for LLM analysis.

        Args:
            content: Page content
            url: Page URL

        Returns:
            Formatted prompt string
        """
        # Truncate content to keep prompt manageable (4000 chars max)
        content_preview = content[:4000] if len(content) > 4000 else content
        if len(content) > 4000:
            content_preview += "\n\n[... content truncated ...]"

        domain = urlparse(url).netloc

        prompt = f"""You are analyzing a car dealership locator website to extract CSS selectors, interaction patterns, and data field locations for web scraping.

Website URL: {url}
Domain: {domain}

Page Content (LLM-friendly format):
{content_preview}

Your task is to analyze this page and identify EVERYTHING needed to scrape dealer information. Return ONLY valid JSON in this exact format:

{{
  "selectors": {{
    "search_input": ["CSS selector 1", "CSS selector 2"],
    "search_button": ["CSS selector 1"],
    "apply_button": ["CSS selector 1"],
    "view_more_button": ["CSS selector 1"],
    "dealer_cards": ["CSS selector 1", "CSS selector 2"],
    "scroll_container": ["CSS selector 1"]
  }},
  "data_fields": {{
    "name": {{
      "selector": "CSS selector within dealer card",
      "type": "text",
      "fallback_patterns": ["h2", "h3", "[class*='name']"]
    }},
    "address": {{
      "selector": "CSS selector within dealer card",
      "type": "text",
      "fallback_patterns": ["[class*='address']", "[class*='location']"]
    }},
    "phone": {{
      "selector": "CSS selector within dealer card",
      "type": "href",
      "attribute": "href",
      "fallback_patterns": ["a[href^='tel:']", "[class*='phone']"]
    }},
    "website": {{
      "selector": "CSS selector within dealer card",
      "type": "href",
      "attribute": "href",
      "fallback_patterns": ["a[href^='http']", "[class*='website']"]
    }}
  }},
  "interactions": {{
    "search_sequence": ["fill_input", "press_enter"],
    "pagination_type": "view_more",
    "wait_after_search": 4,
    "wait_after_page_load": 3,
    "scroll_delay": 0.5,
    "view_more_delay": 2,
    "click_delay": 0.3
  }},
  "input_fields": {{
    "zip_code": {{
      "selector": "CSS selector",
      "type": "text",
      "required": true
    }},
    "radius": {{
      "selector": "CSS selector for radius dropdown if exists",
      "type": "select",
      "required": false,
      "default_value": "50"
    }}
  }},
  "extraction": {{
    "name_patterns": ["regex pattern 1"],
    "phone_patterns": ["\\\\(?\\\\d{{3}}\\\\)?[-.\\\\s]?\\\\d{{3}}[-.\\\\s]?\\\\d{{4}}"],
    "address_patterns": [".+?,\\\\s*[A-Za-z\\\\s]+,\\\\s*[A-Z]{{2}}\\\\s+\\\\d{{5}}"]
  }},
  "confidence": 0.85,
  "notes": "Additional observations about the page structure"
}}

IMPORTANT Guidelines:
1. **search_input**: Input field for zip codes/city. Look for: input[placeholder*='zip'], input[name*='zip'], input[id*='location']
2. **search_button**: Button to submit search. May be: button[type='submit'], button containing 'Search', 'Find', 'Go'
3. **apply_button**: Button to apply filters (if separate from search). Look for: button containing 'Apply', 'Filter'
4. **view_more_button**: Pagination button. Look for: button containing 'View More', 'Load More', 'Show More', 'See More'
5. **dealer_cards**: Container for each dealer. Look for: li[class*='dealer'], div[class*='dealer'], article[class*='result']
6. **data_fields**: Within each dealer card, identify WHERE each piece of info is located:
   - name: Usually in h2, h3, h4, or div with 'name' class
   - address: Often has 'address', 'location', or contains street/city/state/zip pattern
   - phone: Look for tel: links or elements with 'phone' class
   - website: External links (not to same domain) or elements with 'website' class
7. **interactions.search_sequence**: List the steps needed: ["fill_input", "click_search"] or ["fill_input", "press_enter"]
8. **interactions.pagination_type**: One of "view_more", "scroll", "pagination", or "none"
9. **input_fields**: If there's a radius/distance dropdown, identify it
10. Use valid CSS selectors. The "type" field indicates if we should get text content or an attribute value.
11. **confidence**: 0.0-1.0 based on how certain you are about the selectors
12. If something doesn't exist, use null or empty array []

Return ONLY the JSON, no additional text or markdown formatting. /no_think"""

        return prompt

    def _call_llm(self, prompt: str) -> Optional[str]:
        """
        Call local LLM API (Ollama).

        Args:
            prompt: Prompt to send to LLM

        Returns:
            LLM response text or None if failed
        """
        try:
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1,  # Low temperature for consistent output
                }
            }

            response = requests.post(
                self.endpoint,
                json=payload,
                timeout=self.timeout
            )
            response.raise_for_status()

            result = response.json()
            return result.get('response', '')

        except requests.exceptions.ConnectionError:
            print(f"Error: Cannot connect to LLM at {self.endpoint}")
            print("Make sure Ollama is running: ollama serve")
            return None
        except requests.exceptions.Timeout:
            print(f"Error: LLM request timed out after {self.timeout}s")
            return None
        except Exception as e:
            print(f"Error calling LLM: {e}")
            return None

    def _parse_llm_response(self, response: str) -> Optional[Dict[str, Any]]:
        """
        Parse LLM response and extract JSON.

        Args:
            response: Raw LLM response

        Returns:
            Parsed analysis dictionary or None if parsing failed
        """
        if not response:
            return None

        # Try to extract JSON from response (LLM might add extra text)
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
        else:
            json_str = response.strip()

        # Remove markdown code blocks if present
        json_str = re.sub(r'^```json\s*', '', json_str, flags=re.MULTILINE)
        json_str = re.sub(r'^```\s*', '', json_str, flags=re.MULTILINE)
        json_str = json_str.strip()

        try:
            analysis = json.loads(json_str)

            # Validate structure
            if not isinstance(analysis, dict):
                return None

            # Ensure required keys exist with defaults
            result = {
                'selectors': analysis.get('selectors', {}),
                'data_fields': analysis.get('data_fields', {}),
                'interactions': analysis.get('interactions', {}),
                'input_fields': analysis.get('input_fields', {}),
                'extraction': analysis.get('extraction', {}),
                'confidence': analysis.get('confidence', 0.5),
                'notes': analysis.get('notes', '')
            }

            # Validate selectors structure
            if not isinstance(result['selectors'], dict):
                result['selectors'] = {}

            # Ensure all selector types exist
            for selector_type in ['search_input', 'search_button', 'dealer_cards',
                                  'apply_button', 'view_more_button', 'scroll_container']:
                if selector_type not in result['selectors']:
                    result['selectors'][selector_type] = []

            # Ensure data_fields has required keys with defaults
            if not isinstance(result['data_fields'], dict):
                result['data_fields'] = {}

            default_data_fields = {
                'name': {
                    'selector': None,
                    'type': 'text',
                    'fallback_patterns': ['h2', 'h3', 'h4', "[class*='name']"]
                },
                'address': {
                    'selector': None,
                    'type': 'text',
                    'fallback_patterns': ["[class*='address']", "[class*='location']"]
                },
                'phone': {
                    'selector': None,
                    'type': 'href',
                    'attribute': 'href',
                    'fallback_patterns': ["a[href^='tel:']", "[class*='phone']"]
                },
                'website': {
                    'selector': None,
                    'type': 'href',
                    'attribute': 'href',
                    'fallback_patterns': ["a[href^='http']", "[class*='website']"]
                }
            }
            for field, defaults in default_data_fields.items():
                if field not in result['data_fields']:
                    result['data_fields'][field] = defaults
                else:
                    # Ensure all keys exist in the field
                    for key, value in defaults.items():
                        if key not in result['data_fields'][field]:
                            result['data_fields'][field][key] = value

            # Ensure interactions has required keys
            if not isinstance(result['interactions'], dict):
                result['interactions'] = {}

            default_interactions = {
                'search_sequence': ['fill_input', 'press_enter'],
                'pagination_type': 'view_more',
                'wait_after_search': 4,
                'wait_after_page_load': 3,
                'scroll_delay': 0.5,
                'view_more_delay': 2,
                'click_delay': 0.3
            }
            for key, value in default_interactions.items():
                if key not in result['interactions']:
                    result['interactions'][key] = value

            return result

        except json.JSONDecodeError as e:
            print(f"Error parsing LLM JSON response: {e}")
            print(f"Response was: {response[:500]}")
            return None


# Global instance
_llm_analyzer: Optional[LLMAnalyzer] = None


def get_llm_analyzer() -> LLMAnalyzer:
    """Get or create the global LLM analyzer instance."""
    global _llm_analyzer
    if _llm_analyzer is None:
        _llm_analyzer = LLMAnalyzer()
    return _llm_analyzer
