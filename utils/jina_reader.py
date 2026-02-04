#!/usr/bin/env python3
"""
Jina Reader Integration

Fetches LLM-friendly content from URLs using the Jina Reader API.
Converts any URL to an LLM-friendly input with https://r.jina.ai/
"""

import os
import time
import json
import requests
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
from urllib.parse import urlparse


class JinaReader:
    """Client for Jina Reader API to fetch LLM-friendly content."""

    BASE_URL = "https://r.jina.ai/"
    DEFAULT_TIMEOUT = 30
    EXTENDED_TIMEOUT = 60  # Extended timeout for retry attempts
    MAX_RETRIES = 3
    RETRY_DELAY = 2
    RATE_LIMIT_DELAY = 10  # Delay when rate limited (429)
    RATE_LIMIT_MAX_RETRIES = 2  # Additional retries for rate limiting

    def __init__(self, enabled: bool = True):
        """
        Initialize Jina Reader client.

        Args:
            enabled: Whether Jina Reader is enabled (can be disabled via env var)
        """
        self.enabled = enabled and os.getenv('JINA_READER_ENABLED', 'true').lower() == 'true'
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })
        # Allow custom TLS verification behavior for environments with SSL interception.
        # Use JINA_SSL_VERIFY=false to disable verification, or JINA_CA_BUNDLE to point
        # to a custom CA bundle file.
        verify_env = os.getenv('JINA_SSL_VERIFY', 'true').lower()
        if verify_env in ['0', 'false', 'no']:
            self.session.verify = False
        else:
            ca_bundle = os.getenv('JINA_CA_BUNDLE')
            if ca_bundle:
                self.session.verify = ca_bundle
        # Track domains that have rate limited us
        self._rate_limited_domains = {}

    def _debug_log(self, hypothesis_id: str, location: str, message: str, data: Dict[str, Any]):
        """Append a small NDJSON debug log line."""
        try:
            payload = {
                "sessionId": "debug-session",
                "runId": "run1",
                "hypothesisId": hypothesis_id,
                "location": location,
                "message": message,
                "data": data,
                "timestamp": int(time.time() * 1000)
            }
            with open(
                "/Users/Lucy_Wang/Library/CloudStorage/OneDrive-McKinsey&Company/Documents/GitHub/car-dealer-scraper/.cursor/debug.log",
                "a",
                encoding="utf-8"
            ) as log_file:
                log_file.write(json.dumps(payload) + "\n")
        except Exception:
            pass

    def fetch_page_content(
        self,
        url: str,
        wait_selector: Optional[str] = None,
        timeout: Optional[int] = None,
        streaming: bool = False
    ) -> Optional[str]:
        """
        Fetch LLM-friendly content from a URL using Jina Reader.

        Args:
            url: URL to fetch
            wait_selector: Optional CSS selector to wait for (for SPAs)
            timeout: Request timeout in seconds
            streaming: Whether to use streaming mode

        Returns:
            LLM-friendly markdown content or None if failed
        """
        if not self.enabled:
            return None

        if not url or not url.startswith(('http://', 'https://')):
            return None

        # region agent log
        try:
            import certifi
            certifi_path = certifi.where()
        except Exception:
            certifi_path = None
        self._debug_log(
            "H1",
            "utils/jina_reader.py:fetch_page_content",
            "entry",
            {
                "url": url,
                "enabled": self.enabled,
                "streaming": streaming,
                "timeout": timeout,
                "session_verify": getattr(self.session, "verify", None),
                "requests_ca_bundle": os.getenv("REQUESTS_CA_BUNDLE"),
                "ssl_cert_file": os.getenv("SSL_CERT_FILE"),
                "certifi_where": certifi_path
            }
        )
        # endregion

        # Extract domain to check for rate limiting
        domain = self.extract_domain(url)
        
        # Check if this domain was recently rate limited
        if domain in self._rate_limited_domains:
            last_limited = self._rate_limited_domains[domain]
            if time.time() - last_limited < self.RATE_LIMIT_DELAY * 2:
                print(f"  Skipping {domain} - recently rate limited, waiting...")
                time.sleep(self.RATE_LIMIT_DELAY)

        timeout = timeout or self.DEFAULT_TIMEOUT
        jina_url = f"{self.BASE_URL}{url}"

        headers = {}
        if wait_selector:
            headers['x-wait-for-selector'] = wait_selector
        if timeout:
            headers['x-timeout'] = str(timeout)
        if streaming:
            headers['Accept'] = 'text/event-stream'

        # Try with streaming first, then fallback to non-streaming
        modes_to_try = [streaming]
        if streaming:
            modes_to_try.append(False)  # Fallback to non-streaming

        for use_streaming in modes_to_try:
            current_headers = headers.copy()
            if use_streaming:
                current_headers['Accept'] = 'text/event-stream'
            elif 'Accept' in current_headers:
                del current_headers['Accept']

            for attempt in range(self.MAX_RETRIES):
                # Exponential backoff delay
                delay = self.RETRY_DELAY * (2 ** attempt)
                current_timeout = timeout if attempt == 0 else self.EXTENDED_TIMEOUT

                try:
                    # region agent log
                    self._debug_log(
                        "H3",
                        "utils/jina_reader.py:fetch_page_content",
                        "request_attempt",
                        {
                            "attempt": attempt + 1,
                            "use_streaming": use_streaming,
                            "timeout": current_timeout,
                            "jina_url": jina_url,
                            "has_wait_selector": bool(wait_selector)
                        }
                    )
                    # endregion
                    if use_streaming:
                        response = self._fetch_streaming(jina_url, current_headers, current_timeout)
                    else:
                        resp = self.session.get(jina_url, headers=current_headers, timeout=current_timeout)
                        
                        # Handle rate limiting (429)
                        if resp.status_code == 429:
                            self._rate_limited_domains[domain] = time.time()
                            retry_after = int(resp.headers.get('Retry-After', self.RATE_LIMIT_DELAY))
                            print(f"  Rate limited (429) for {domain}, waiting {retry_after}s...")
                            time.sleep(retry_after)
                            if attempt < self.MAX_RETRIES - 1:
                                continue
                            else:
                                return None
                        
                        resp.raise_for_status()
                        response = resp.text

                    # region agent log
                    self._debug_log(
                        "H3",
                        "utils/jina_reader.py:fetch_page_content",
                        "response_received",
                        {
                            "use_streaming": use_streaming,
                            "response_len": len(response) if response else 0
                        }
                    )
                    # endregion

                    # Check if we got a valid response (not an error page)
                    if response and len(response) > 100:
                        return response
                    elif response:
                        # Got something but it's very short - might be an error
                        # Check for common error indicators
                        lower_resp = response.lower()
                        if any(err in lower_resp for err in ['security checkpoint', 'access denied', 'blocked']):
                            print(f"  Warning: Got blocked/security response for {url}")
                            if attempt < self.MAX_RETRIES - 1:
                                time.sleep(delay * 2)  # Wait longer for security blocks
                                continue
                            return None
                        return response

                except requests.exceptions.Timeout:
                    if attempt < self.MAX_RETRIES - 1:
                        print(f"  Timeout (attempt {attempt + 1}/{self.MAX_RETRIES}), retrying in {delay}s...")
                        time.sleep(delay)
                        continue
                    # If streaming timed out, we'll try non-streaming in outer loop
                    if use_streaming and not streaming:
                        print(f"  Streaming timeout, will try non-streaming...")
                        break
                    print(f"Warning: Jina Reader timeout for {url}")
                    return None

                except requests.exceptions.HTTPError as e:
                    status_code = e.response.status_code if e.response else None
                    
                    # Handle specific HTTP errors
                    if status_code == 429:
                        self._rate_limited_domains[domain] = time.time()
                        retry_after = int(e.response.headers.get('Retry-After', self.RATE_LIMIT_DELAY))
                        print(f"  Rate limited (429) for {domain}, waiting {retry_after}s...")
                        time.sleep(retry_after)
                        if attempt < self.MAX_RETRIES - 1:
                            continue
                    elif status_code in [502, 503, 504]:
                        # Server errors - retry with backoff
                        if attempt < self.MAX_RETRIES - 1:
                            print(f"  Server error ({status_code}), retrying in {delay}s...")
                            time.sleep(delay)
                            continue
                    elif status_code == 403:
                        # Forbidden - likely blocked, wait longer
                        if attempt < self.MAX_RETRIES - 1:
                            print(f"  Forbidden (403), retrying in {delay * 2}s...")
                            time.sleep(delay * 2)
                            continue
                    
                    print(f"Warning: Jina Reader HTTP error for {url}: {e}")
                    if use_streaming and False in modes_to_try:
                        break  # Try non-streaming
                    return None

                except requests.exceptions.RequestException as e:
                    # region agent log
                    self._debug_log(
                        "H1",
                        "utils/jina_reader.py:fetch_page_content",
                        "request_exception",
                        {
                            "attempt": attempt + 1,
                            "use_streaming": use_streaming,
                            "error_type": type(e).__name__,
                            "error_msg": str(e),
                            "is_ssl_error": isinstance(e, requests.exceptions.SSLError)
                        }
                    )
                    # endregion
                    if attempt < self.MAX_RETRIES - 1:
                        print(f"  Request error (attempt {attempt + 1}/{self.MAX_RETRIES}): {e}")
                        time.sleep(delay)
                        continue
                    print(f"Warning: Jina Reader error for {url}: {e}")
                    if use_streaming and False in modes_to_try:
                        break  # Try non-streaming
                    return None

        return None

    def _fetch_streaming(self, url: str, headers: Dict[str, str], timeout: int) -> str:
        """
        Fetch content using streaming mode.

        Args:
            url: Jina Reader URL
            headers: Request headers
            timeout: Request timeout

        Returns:
            Complete content from stream
        """
        response = self.session.get(url, headers=headers, timeout=timeout, stream=True)
        response.raise_for_status()

        content_parts = []
        for line in response.iter_lines(decode_unicode=True):
            if line.startswith('data: '):
                content = line[6:]  # Remove 'data: ' prefix
                if content:
                    content_parts.append(content)

        # Return the last (most complete) chunk
        return content_parts[-1] if content_parts else ""

    def fetch_with_screenshot(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Fetch page content with screenshot URL.

        Args:
            url: URL to fetch

        Returns:
            Dict with 'content' and 'screenshot_url' or None
        """
        if not self.enabled:
            return None

        jina_url = f"{self.BASE_URL}{url}"
        headers = {'x-respond-with': 'screenshot'}

        try:
            response = self.session.get(jina_url, headers=headers, timeout=self.DEFAULT_TIMEOUT)
            response.raise_for_status()
            screenshot_url = response.text.strip()

            # Fetch the actual content
            content = self.fetch_page_content(url)

            return {
                'content': content,
                'screenshot_url': screenshot_url
            }
        except Exception as e:
            print(f"Warning: Failed to fetch screenshot for {url}: {e}")
            return None

    def save_analysis_artifacts(
        self,
        url: str,
        base_dir: str = "data/analysis",
        streaming: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch page content and save to disk for troubleshooting.

        Args:
            url: URL to fetch and analyze
            base_dir: Base directory for saving artifacts
            streaming: Whether to use streaming mode for content fetch

        Returns:
            Dict with 'content', 'content_path', 'domain' or None
        """
        if not self.enabled:
            return None

        if not url or not url.startswith(('http://', 'https://')):
            return None

        # Extract domain for directory naming
        parsed = urlparse(url)
        domain = parsed.netloc.replace('www.', '')

        # Create directory structure
        domain_dir = Path(base_dir) / domain
        domain_dir.mkdir(parents=True, exist_ok=True)

        # Generate timestamp for file naming
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        result = {
            'url': url,
            'domain': domain,
            'timestamp': timestamp,
            'content': None,
            'content_path': None,
        }

        # Fetch content
        print(f"  Fetching content from {url}...")
        content = self.fetch_page_content(url, streaming=streaming)
        if content:
            result['content'] = content
            content_path = domain_dir / f"{timestamp}_content.txt"
            try:
                with open(content_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                result['content_path'] = str(content_path)
                print(f"  Saved content to {content_path}")
            except Exception as e:
                print(f"  Warning: Failed to save content: {e}")

        # Return None if we couldn't get content
        if not result['content']:
            print(f"  Warning: Could not fetch content from {url}")
            return None

        return result

    @staticmethod
    def extract_domain(url: str) -> str:
        """
        Extract clean domain from URL.

        Args:
            url: Full URL

        Returns:
            Clean domain name (without www.)
        """
        if not url:
            return ""
        parsed = urlparse(url)
        return parsed.netloc.replace('www.', '')


# Global instance
_jina_reader: Optional[JinaReader] = None


def get_jina_reader() -> JinaReader:
    """Get or create the global Jina Reader instance."""
    global _jina_reader
    if _jina_reader is None:
        _jina_reader = JinaReader()
    return _jina_reader
