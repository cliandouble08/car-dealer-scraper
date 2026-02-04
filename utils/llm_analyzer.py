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
    DEFAULT_MAX_TOKENS = 1500  # Max tokens for LLM response

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
        self.max_tokens = int(os.getenv('LLM_MAX_TOKENS', str(self.DEFAULT_MAX_TOKENS)))

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
            if analysis:
                return analysis

            # Retry with a smaller, more concise prompt to avoid truncation
            print("Warning: LLM response parsing failed, retrying with concise prompt")
            concise_prompt = self._build_analysis_prompt(content, url, max_chars=3000, concise=True)
            response = self._call_llm(concise_prompt)
            if not response:
                return None
            return self._parse_llm_response(response)

        except Exception as e:
            print(f"Error during LLM analysis: {e}")
            return None

    def _extract_relevant_content(self, content: str, max_chars: int = 8000) -> str:
        """
        Extract relevant parts of content for analysis.
        Prioritizes keywords like 'dealer', 'locator', 'find'.
        """
        if not content or len(content) <= 4000:
            return content

        # Always include the header (first 2000 chars)
        extracted = content[:2000]
        
        # Keywords to search for
        keywords = ['dealer', 'locator', 'locations', 'find', 'store', 'search']
        
        # Find occurrences and extract context
        # Convert to lower for case-insensitive search but keep original indices
        content_lower = content.lower()
        
        found_indices = []
        for keyword in keywords:
            for match in re.finditer(keyword, content_lower):
                start = max(0, match.start() - 200)
                end = min(len(content), match.end() + 200)
                found_indices.append((start, end))
        
        # Merge overlapping ranges
        if not found_indices:
            return extracted + "\n\n[...]\n\n" + content[-2000:]
            
        found_indices.sort()
        merged_indices = []
        if found_indices:
            curr_start, curr_end = found_indices[0]
            for start, end in found_indices[1:]:
                if start < curr_end:
                    curr_end = max(curr_end, end)
                else:
                    merged_indices.append((curr_start, curr_end))
                    curr_start, curr_end = start, end
            merged_indices.append((curr_start, curr_end))
            
        # Add merged chunks to result until max_chars is reached
        for start, end in merged_indices:
            if start < 2000: # Skip if already in header
                continue
            chunk = content[start:end]
            if len(extracted) + len(chunk) > max_chars:
                break
            extracted += "\n\n[...]\n\n" + chunk
            
        return extracted

    def _extract_locator_candidates(self, content: str) -> list:
        """
        Extract candidate locator URLs from content using keyword heuristics.
        Returns a list of dicts with url/text/source.
        """
        if not content:
            return []

        keyword_phrases = [
            'find a dealer', 'dealer locator', 'locate a dealer',
            'dealer directory', 'dealer search', 'find dealer',
            'dealers', 'dealer'
        ]
        keyword_phrases = [k.lower() for k in keyword_phrases]

        candidates = []

        # Match markdown links: [text](url)
        link_matches = re.findall(r'\[([^\]]+)\]\((https?://[^)]+|/[^)]+)\)', content)
        for text, url in link_matches:
            text_lower = text.lower()
            url_lower = url.lower()
            if any(k in text_lower for k in keyword_phrases) or any(k in url_lower for k in keyword_phrases):
                candidates.append({'url': url, 'text': text, 'source': 'markdown'})

        # Match bare URLs that include dealer keywords
        bare_url_matches = re.findall(r'(https?://[^\s\)\]]+)', content)
        for url in bare_url_matches:
            url_lower = url.lower()
            if any(k in url_lower for k in keyword_phrases):
                candidates.append({'url': url, 'text': '', 'source': 'bare'})

        return self._filter_locator_candidates(candidates)

    def _clean_candidate_url(self, url: str) -> str:
        """Clean a candidate URL string."""
        if not url:
            return ""
        return url.strip().rstrip(').,;]')

    def _normalize_url_for_compare(self, url: str) -> str:
        """Normalize URL for comparison across candidates/LLM output."""
        if not url:
            return ""
        normalized = self._clean_candidate_url(url).lower()
        if normalized.endswith('/'):
            normalized = normalized[:-1]
        return normalized

    def _filter_locator_candidates(self, candidates: list) -> list:
        """
        Lightly filter and de-duplicate locator candidates to keep them focused.
        """
        if not candidates:
            return []

        negative_keywords = [
            'incentive', 'offer', 'build', 'price', 'compare', 'inventory',
            'preowned', 'lease', 'apr', 'credit', 'quote', 'estimate', 'payment',
            'test-drive', 'schedule'
        ]
        positive_keywords = ['dealer', 'dealers', 'locator', 'location', 'directory', 'find']

        filtered = []
        seen = set()
        for candidate in candidates:
            url = self._clean_candidate_url(candidate.get('url') or '')
            if not url or url in seen or url.startswith('javascript:'):
                continue

            url_lower = url.lower()
            text_lower = (candidate.get('text') or '').lower()
            has_positive = any(k in url_lower for k in positive_keywords)

            if any(k in url_lower or k in text_lower for k in negative_keywords) and not has_positive:
                continue

            seen.add(url)
            filtered.append(candidate)

        return filtered

    def _order_locator_candidates(self, candidates: list) -> list:
        """
        Order locator candidates by heuristic score (descending).
        """
        if not candidates:
            return []
        scored = [(self._score_locator_candidate(url), url) for url in candidates]
        scored.sort(reverse=True, key=lambda x: x[0])
        ordered = []
        seen = set()
        for _, url in scored:
            normalized = self._normalize_url_for_compare(url)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(url)
        return ordered

    def _score_locator_candidate(self, url: str) -> int:
        """
        Score a locator URL candidate by common path patterns.
        """
        if not url:
            return 0

        url_lower = url.lower()
        patterns = [
            '/dealers', '/dealer', '/dealer-locator', '/find-a-dealer',
            '/dealer-locator', '/dealer-search', '/dealer-directory',
            '/locations', '/locator'
        ]
        score = 0
        for pattern in patterns:
            if pattern in url_lower:
                score += 2
        if '#default' in url_lower:
            score += 1
        return score

    def _select_best_locator_candidate(self, candidates: list) -> Optional[str]:
        """
        Select the best locator candidate using heuristic scoring.
        """
        if not candidates:
            return None

        scored = [(self._score_locator_candidate(url), url) for url in candidates]
        scored.sort(reverse=True, key=lambda x: x[0])
        best_score, best_url = scored[0]
        if best_score <= 0:
            return None
        return best_url

    def _parse_locator_selection_response(self, response: str) -> Optional[str]:
        """
        Parse a locator URL from an LLM response that returns JSON or plain text.
        """
        if not response:
            return None

        # Extract JSON if present
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
            json_str = re.sub(r'^```json\s*', '', json_str, flags=re.MULTILINE)
            json_str = re.sub(r'^```\s*', '', json_str, flags=re.MULTILINE)
            json_str = json_str.strip()
            json_str = re.sub(r',\s*}', '}', json_str)
            json_str = re.sub(r',\s*]', ']', json_str)
            try:
                data = json.loads(json_str)
                if isinstance(data, dict):
                    locator_url = data.get('locator_url')
                    if locator_url:
                        return locator_url
            except json.JSONDecodeError:
                pass

        # Fallback: try to pull a URL from plain text
        url_match = re.search(r'(https?://\S+|/\S+)', response)
        if url_match:
            return url_match.group(0)

        return None

    def find_dealer_locator_url(self, content: str, url: str) -> Optional[Dict[str, Any]]:
        """
        Analyze page content to find the dealer locator URL.

        Args:
            content: Page content
            url: Page URL

        Returns:
            Dictionary with 'is_locator' (bool) and 'locator_url' (str)
        """
        if not self.enabled:
            return None

        # Extract relevant content instead of just truncating
        relevant_content = self._extract_relevant_content(content)
        candidates = self._extract_locator_candidates(content)
        candidate_urls = [
            self._clean_candidate_url(candidate.get('url') or '')
            for candidate in candidates
            if candidate.get('url')
        ]
        candidate_url_set = {
            self._normalize_url_for_compare(url)
            for url in candidate_urls
            if url
        }

        prompt = f"""You are navigating a car manufacturer's website to find the "Find a Dealer" or "Dealer Locator" page.

Website URL: {url}

Page Content:
{relevant_content}

Your task:
1. Determine if this CURRENT page is already the dealer locator / search page (where you enter a zip code to find dealers).
2. If NOT, find the URL or link text that leads to the dealer locator. Look for "Find a Dealer", "Locate a Dealer", "Find", "Locations", "Dealers", "Shopping Tools".

Return ONLY valid JSON in this format:
{{
  "is_locator": boolean,  // true if this page IS the locator (zip input visible)
  "locator_url": "string or null", // The URL path to the locator if found (e.g., "/dealers", "https://site.com/locate"). If uncertain, use null.
  "confidence": 0.0-1.0
}}

Examples:
- If page has "Enter Zip Code" input -> is_locator: true
- If page has "Find a Dealer" link to "/dealerships" -> is_locator: false, locator_url: "/dealerships"
- If page is just marketing info -> is_locator: false, locator_url: "/find-dealer" (if link exists)

Return ONLY the JSON. /no_think"""

        try:
            response = self._call_llm(prompt)
            if not response:
                response = ""

            result = self._parse_llm_response(response)
            if not result:
                result = {}

            # Normalize structure
            is_locator = bool(result.get('is_locator', False))
            locator_url = result.get('locator_url')
            if locator_url:
                locator_url = self._clean_candidate_url(locator_url)
                if candidate_url_set and self._normalize_url_for_compare(
                    locator_url
                ) not in candidate_url_set:
                    locator_url = None

            # If LLM claims current page is locator, validate by checking URL path
            # and presence of dealer keywords in content
            url_path = urlparse(url).path.lower()
            url_path_is_locator = any(
                keyword in url_path for keyword in ['dealer', 'dealers', 'locator', 'locations']
            )
            content_has_locator_signal = 'zip' in relevant_content.lower() and 'dealer' in relevant_content.lower()

            # If LLM says locator but URL path doesn't look like it, try fallback
            if is_locator and not url_path_is_locator and not content_has_locator_signal:
                is_locator = False

            if not is_locator or not locator_url:
                # Fallback: extract candidates directly from content
                if candidates:
                    if self.enabled:
                        formatted_candidates = []
                        for candidate in candidates[:12]:
                            text = candidate.get('text', '').strip()
                            url_value = candidate.get('url', '').strip()
                            if text:
                                formatted_candidates.append(f"- text: \"{text}\" | url: {url_value}")
                            else:
                                formatted_candidates.append(f"- url: {url_value}")

                        candidate_list = "\n".join(formatted_candidates)
                        selection_prompt = f"""You are choosing the best dealer locator URL from a list.
Website URL: {url}

Guidance:
- Prefer full paths over hash fragments (e.g., avoid "#app-..." if a real path exists).
- Prefer URLs that clearly represent a dealer locator with zip search (e.g., /find-dealer, /dealers, /dealer-directory, /locations).
- If all candidates are hash fragments or look non-locator, you may infer a likely locator path based on common patterns (e.g., /find-dealer or /shopping-tools/find-dealer).

Candidates:
{candidate_list}

Return ONLY valid JSON:
{{ "locator_url": "best_url_here", "confidence": 0.0-1.0 }}
"""
                        selection_response = self._call_llm(selection_prompt)
                        selected_url = self._parse_locator_selection_response(
                            selection_response or ""
                        )
                        if selected_url:
                            selected_url = self._clean_candidate_url(selected_url)
                            if not candidate_url_set or self._normalize_url_for_compare(
                                selected_url
                            ) in candidate_url_set:
                                locator_url = selected_url
                    if not locator_url:
                        ordered_candidates = self._order_locator_candidates(
                            candidate_urls
                        )
                        locator_url = ordered_candidates[0] if ordered_candidates else None

            return {
                'is_locator': is_locator,
                'locator_url': locator_url,
                'locator_candidates': self._order_locator_candidates(candidate_urls),
                'confidence': result.get('confidence', 0.5)
            }

        except Exception as e:
            print(f"Error finding locator URL: {e}")
            return None

    def _build_analysis_prompt(self, content: str, url: str, max_chars: int = 8000, concise: bool = False) -> str:
        """
        Build structured prompt for LLM analysis.

        Args:
            content: Page content
            url: Page URL

        Returns:
            Formatted prompt string
        """
        # Use intelligent extraction instead of blind truncation
        content_preview = self._extract_relevant_content(content, max_chars=max_chars)

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
  "popup": {{
    "has_blocking_popup": false,
    "popup_container": "CSS selector for popup/modal content container",
    "popup_overlay": "CSS selector for blocking overlay if separate",
    "popup_zip_input": "CSS selector for zip input within popup",
    "popup_submit_button": "CSS selector for submit button in popup",
    "popup_type": "zip_required"
  }},
  "confidence": 0.85,
  "notes": "Additional observations about the page structure"
}}

IMPORTANT Guidelines:
1. **search_input**: Input field for zip codes/city. Look for: input[placeholder*='zip'], input[name*='zip'], input[id*='location']
2. **search_button**: Button to submit search. May be: button[type='submit'], button containing 'Search', 'Find', 'Go'
3. **apply_button**: Button to apply filters (if separate from search). Look for: button containing 'Apply', 'Filter'
4. **view_more_button**: Pagination button. Look for: button containing 'View More', 'Load More', 'Show More', 'See More'
5. **dealer_cards**: Container for each dealer. Choose a selector that REPEATS per dealer and contains name/address/phone within it. Avoid high-level containers or search/filter UI. Look for: li[class*='dealer'], div[class*='dealer'], article[class*='result']
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
13. **popup**: Check if the page shows a blocking popup/modal that requires zip input BEFORE showing dealer results:
    - has_blocking_popup: true if a modal/popup blocks the page until zip is entered
    - popup_container: CSS selector for the modal content (e.g., .modal-content, .modal-dialog, [role='dialog'])
    - popup_overlay: CSS selector for the overlay/backdrop (e.g., .modal-overlay, .modal-backdrop)
    - popup_zip_input: CSS selector for the zip input INSIDE the popup
    - popup_submit_button: CSS selector for submit button in popup
    - popup_type: "zip_required" if zip input needed, "location_permission" for geolocation prompts, "other" otherwise

Return ONLY the JSON, no additional text or markdown formatting. /no_think"""

        if concise:
            prompt += "\n\nConcise mode: Limit each selector list to <=3 items. Keep fields minimal."

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
                    "num_predict": self.max_tokens
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

    def _fix_bracket_mismatches(self, json_str: str) -> str:
        """
        Fix bracket mismatches in JSON strings.
        
        LLMs sometimes output ) instead of ] or ( instead of [.
        This method attempts to fix these common errors.
        
        Args:
            json_str: JSON string potentially with bracket errors
            
        Returns:
            Fixed JSON string
        """
        if not json_str:
            return json_str
        
        # Track bracket positions and their types
        # We'll fix mismatches by looking at context
        result = list(json_str)
        bracket_stack = []  # Stack of (index, char, expected_close)
        
        i = 0
        in_string = False
        escape_next = False
        
        while i < len(result):
            char = result[i]
            
            # Handle string boundaries
            if escape_next:
                escape_next = False
                i += 1
                continue
            
            if char == '\\' and in_string:
                escape_next = True
                i += 1
                continue
            
            if char == '"':
                in_string = not in_string
                i += 1
                continue
            
            # Skip if we're inside a string
            if in_string:
                i += 1
                continue
            
            # Track opening brackets
            if char == '[':
                bracket_stack.append((i, '[', ']'))
            elif char == '{':
                bracket_stack.append((i, '{', '}'))
            elif char == '(':
                # Check if this looks like it should be a [ (e.g., after : or ,)
                # Look back for context
                prev_non_space = None
                for j in range(i - 1, -1, -1):
                    if result[j] not in ' \t\n\r':
                        prev_non_space = result[j]
                        break
                
                if prev_non_space in [':', ',', '[']:
                    # This ( should probably be [
                    result[i] = '['
                    bracket_stack.append((i, '[', ']'))
                else:
                    bracket_stack.append((i, '(', ')'))
            
            # Handle closing brackets
            elif char in ']})':
                if bracket_stack:
                    open_idx, open_char, expected_close = bracket_stack[-1]
                    
                    if char == expected_close:
                        # Correct match
                        bracket_stack.pop()
                    elif char == ')' and expected_close == ']':
                        # ) should be ]
                        result[i] = ']'
                        bracket_stack.pop()
                    elif char == ']' and expected_close == ')':
                        # ] should be ) (less common, but handle it)
                        result[i] = ')'
                        bracket_stack.pop()
                    elif char == ')' and expected_close == '}':
                        # ) should be }
                        result[i] = '}'
                        bracket_stack.pop()
                    elif char == '}' and expected_close == ')':
                        # } should be )
                        result[i] = ')'
                        bracket_stack.pop()
                    elif char == ']' and expected_close == '}':
                        # Mismatched - probably should be }
                        result[i] = '}'
                        bracket_stack.pop()
                    elif char == '}' and expected_close == ']':
                        # Mismatched - probably should be ]
                        result[i] = ']'
                        bracket_stack.pop()
                    else:
                        # Some other mismatch - try to close the current bracket
                        bracket_stack.pop()
            
            i += 1
        
        return ''.join(result)

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

        # Fix common LLM JSON syntax errors
        # 1. Trailing commas in objects/arrays
        json_str = re.sub(r',\s*}', '}', json_str)
        json_str = re.sub(r',\s*]', ']', json_str)
        
        # 2. Fix bracket mismatches - LLM sometimes uses ) instead of ] and vice versa
        # This handles cases like: ["item1", "item2") -> ["item1", "item2"]
        json_str = self._fix_bracket_mismatches(json_str)
        
        # 3. Fix unescaped quotes in strings (common LLM error)
        # json_str = re.sub(r'([{,])\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r'\1"\2":', json_str)

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
                'notes': analysis.get('notes', ''),
                # Pass through locator fields if present
                'is_locator': analysis.get('is_locator'),
                'locator_url': analysis.get('locator_url')
            }

            # If this is a locator discovery response, return it as is
            if 'is_locator' in analysis:
                return analysis

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
