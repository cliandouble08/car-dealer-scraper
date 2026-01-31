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
    DEFAULT_MODEL = "llama3"
    DEFAULT_TIMEOUT = 120  # LLM analysis can take time

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
        # Truncate content if too long (keep first 8000 chars for context)
        content_preview = content[:8000] if len(content) > 8000 else content
        if len(content) > 8000:
            content_preview += "\n\n[... content truncated ...]"

        domain = urlparse(url).netloc

        prompt = f"""You are analyzing a car dealership locator website to extract CSS selectors and interaction patterns for web scraping.

Website URL: {url}
Domain: {domain}

Page Content (LLM-friendly format):
{content_preview}

Your task is to analyze this page and identify the CSS selectors and patterns needed to scrape dealer information. Return ONLY valid JSON in this exact format:

{{
  "selectors": {{
    "search_input": ["CSS selector 1", "CSS selector 2"],
    "dealer_cards": ["CSS selector 1", "CSS selector 2"],
    "apply_button": ["CSS selector 1"],
    "view_more_button": ["CSS selector 1"],
    "scroll_container": ["CSS selector 1"]
  }},
  "interactions": {{
    "wait_after_search": 4,
    "scroll_delay": 0.5,
    "view_more_delay": 2
  }},
  "extraction": {{
    "name_patterns": ["regex pattern 1", "regex pattern 2"],
    "phone_patterns": ["regex pattern 1"],
    "address_patterns": ["regex pattern 1"]
  }},
  "confidence": 0.85,
  "notes": "Additional observations"
}}

Guidelines:
1. For search_input: Look for input fields where users enter zip codes or city names. Common patterns: input[placeholder*='zip'], input[type='search'], input[name*='zip']
2. For dealer_cards: Look for list items or divs containing dealer information. Common patterns: li[class*='dealer'], div[class*='dealer-card'], article[class*='dealer']
3. For apply_button: Look for buttons that apply filters or submit search. Common patterns: button[type='submit'], button:contains('Apply'), button:contains('Search')
4. For view_more_button: Look for pagination or "load more" buttons. Common patterns: button:contains('View More'), button:contains('Load More')
5. For scroll_container: Look for scrollable divs containing the dealer list. Common patterns: div[class*='results'], div[class*='list']
6. Use valid CSS selectors. For text matching, use XPath-style patterns in notes.
7. Confidence should be 0.0-1.0 based on how certain you are about the selectors.
8. If you cannot find something, use empty array [] or reasonable defaults.

Return ONLY the JSON, no additional text or markdown formatting."""

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
                'interactions': analysis.get('interactions', {}),
                'extraction': analysis.get('extraction', {}),
                'confidence': analysis.get('confidence', 0.5),
                'notes': analysis.get('notes', '')
            }

            # Validate selectors structure
            if not isinstance(result['selectors'], dict):
                result['selectors'] = {}

            # Ensure all selector types exist
            for selector_type in ['search_input', 'dealer_cards', 'apply_button', 
                                 'view_more_button', 'scroll_container']:
                if selector_type not in result['selectors']:
                    result['selectors'][selector_type] = []

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
