#!/usr/bin/env python3
"""
Generalized Extraction Utilities

Provides robust extraction functions for dealer information including
phone numbers, addresses, websites, and names with multiple format support.
"""

import re
from typing import Optional, Tuple, List
from urllib.parse import urlparse


def extract_phone(text: str, patterns: Optional[List[str]] = None) -> str:
    """
    Extract phone number from text using multiple patterns.

    Supports formats:
    - (XXX) XXX-XXXX
    - XXX-XXX-XXXX
    - XXX.XXX.XXXX
    - XXX XXX XXXX
    - XXXXXXXXXX

    Args:
        text: Text to search for phone number
        patterns: Optional list of regex patterns to try

    Returns:
        Extracted phone number or empty string
    """
    if patterns is None:
        patterns = [
            r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',  # Standard US format
            r'\d{3}[-.\s]?\d{3}[-.\s]?\d{4}',  # Without parentheses
            r'\+?1[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',  # With country code
        ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            phone = match.group()
            # Normalize phone number
            phone = re.sub(r'[^\d]', '', phone)
            if len(phone) == 10:
                return f"({phone[0:3]}) {phone[3:6]}-{phone[6:10]}"
            elif len(phone) == 11 and phone[0] == '1':
                phone = phone[1:]
                return f"({phone[0:3]}) {phone[3:6]}-{phone[6:10]}"
            else:
                return match.group().strip()

    return ""


def parse_address(text: str) -> Tuple[str, str, str, str]:
    """
    Parse address text into components.

    Args:
        text: Full address string

    Returns:
        Tuple of (full_address, city, state, zip_code)
    """
    # Common US address pattern: Street, City, State ZIP
    # Example: "123 Main St, Anytown, CA 12345"
    address_patterns = [
        r'(.+?),\s*([A-Za-z\s]+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)',
        r'(.+?)\s+([A-Za-z\s]+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)',
        r'(.+?)\s+([A-Z]{2})\s+(\d{5}(?:-\d{4})?)',  # Missing city
    ]

    for pattern in address_patterns:
        match = re.search(pattern, text)
        if match:
            groups = match.groups()
            if len(groups) == 4:
                return (groups[0].strip(), groups[1].strip(), groups[2].strip(), groups[3].strip())
            elif len(groups) == 3:
                # Missing city case
                return (groups[0].strip(), "", groups[1].strip(), groups[2].strip())

    # Fallback: try to extract zip code
    zip_match = re.search(r'\b(\d{5}(?:-\d{4})?)\b', text)
    zip_code = zip_match.group(1) if zip_match else ""

    # Try to extract state (2-letter code)
    state_match = re.search(r'\b([A-Z]{2})\b', text)
    state = state_match.group(1) if state_match else ""

    return (text.strip(), "", state, zip_code)


def extract_website_url(text: str, links: Optional[List] = None, 
                        skip_domains: Optional[List[str]] = None) -> str:
    """
    Extract website URL from text or links.

    Args:
        text: Text content to search
        links: Optional list of link elements (Selenium WebElements)
        skip_domains: List of domains to skip (e.g., ['maps.google.com'])

    Returns:
        Website URL or empty string
    """
    if skip_domains is None:
        skip_domains = ['maps.google.com', 'google.com', 'tel:', 'mailto:']

    # First, try to extract from links if provided
    if links:
        for link in links:
            try:
                href = link.get_attribute("href") or ""
                link_text = (link.text or "").lower()

                # Skip internal/navigation links
                if any(skip in href.lower() for skip in skip_domains):
                    continue

                # Look for dealer website indicators
                if any(indicator in link_text for indicator in ['website', 'dealer site', 'visit']):
                    if href.startswith('http'):
                        return href

                # Accept external http/https links that aren't in skip list
                if href.startswith('http') and not any(skip in href.lower() for skip in skip_domains):
                    # Additional validation: check if it looks like a dealer website
                    parsed = urlparse(href)
                    if parsed.netloc and '.' in parsed.netloc:
                        return href
            except Exception:
                continue

    # Try to extract URL from text using regex
    url_patterns = [
        r'https?://[^\s<>"\'\)]+',
        r'www\.[^\s<>"\'\)]+',
    ]

    for pattern in url_patterns:
        matches = re.findall(pattern, text)
        for match in matches:
            url = match if match.startswith('http') else f"https://{match}"
            if not any(skip in url.lower() for skip in skip_domains):
                parsed = urlparse(url)
                if parsed.netloc and '.' in parsed.netloc:
                    return url

    return ""


def clean_name(name: str, skip_patterns: Optional[List[str]] = None) -> Optional[str]:
    """
    Clean and validate dealer name.

    Args:
        name: Raw dealer name
        skip_patterns: Patterns to skip (e.g., ['view more', 'search'])

    Returns:
        Cleaned name or None if invalid
    """
    if not name or len(name) < 3:
        return None

    if skip_patterns is None:
        skip_patterns = [
            'search by', 'location', 'name', 'clear', 'advanced search',
            'view map', 'make my dealer', 'chat with dealer', 'dealer website',
            'find more', 'view more', 'load more', 'show more', 'see more',
        ]

    name_lower = name.lower().strip()

    # Check against skip patterns
    if any(pattern in name_lower for pattern in skip_patterns):
        return None

    # Remove common prefixes/suffixes
    name = re.sub(r'^\d+\.\s*', '', name)  # Remove "1. " prefix
    name = re.sub(r'\s+', ' ', name)  # Normalize whitespace
    name = name.strip()

    if len(name) < 3:
        return None

    return name


def extract_distance(text: str) -> str:
    """
    Extract distance in miles from text.

    Args:
        text: Text containing distance information

    Returns:
        Distance string (e.g., "5.2") or empty string
    """
    patterns = [
        r'([\d.]+)\s*mi\b',
        r'([\d.]+)\s*miles?\b',
        r'([\d.]+)\s*mi\.',
    ]

    for pattern in patterns:
        match = re.search(pattern, text.lower())
        if match:
            return match.group(1)

    return ""
