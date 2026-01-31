"""
Utilities package for dealer scraping.
"""

from .extraction import (
    extract_phone,
    parse_address,
    extract_website_url,
    clean_name,
    extract_distance
)

__all__ = [
    'extract_phone',
    'parse_address',
    'extract_website_url',
    'clean_name',
    'extract_distance',
]
