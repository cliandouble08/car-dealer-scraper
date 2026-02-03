#!/usr/bin/env python3
"""
Jina Reader Integration

Fetches LLM-friendly content from URLs using the Jina Reader API.
Converts any URL to an LLM-friendly input with https://r.jina.ai/
"""

import os
import time
import requests
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
from urllib.parse import urlparse


class JinaReader:
    """Client for Jina Reader API to fetch LLM-friendly content."""

    BASE_URL = "https://r.jina.ai/"
    DEFAULT_TIMEOUT = 30
    MAX_RETRIES = 3
    RETRY_DELAY = 2

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

        timeout = timeout or self.DEFAULT_TIMEOUT
        jina_url = f"{self.BASE_URL}{url}"

        headers = {}
        if wait_selector:
            headers['x-wait-for-selector'] = wait_selector
        if timeout:
            headers['x-timeout'] = str(timeout)
        if streaming:
            headers['Accept'] = 'text/event-stream'

        for attempt in range(self.MAX_RETRIES):
            try:
                if streaming:
                    response = self._fetch_streaming(jina_url, headers, timeout)
                else:
                    response = self.session.get(jina_url, headers=headers, timeout=timeout)
                    response.raise_for_status()
                    response = response.text

                return response

            except requests.exceptions.Timeout:
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(self.RETRY_DELAY)
                    continue
                print(f"Warning: Jina Reader timeout for {url}")
                return None

            except requests.exceptions.RequestException as e:
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(self.RETRY_DELAY)
                    continue
                print(f"Warning: Jina Reader error for {url}: {e}")
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
