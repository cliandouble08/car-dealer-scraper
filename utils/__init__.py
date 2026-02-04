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
from .jina_reader import get_jina_reader, JinaReader
from .llm_analyzer import get_llm_analyzer, LLMAnalyzer
from .dynamic_config import (
    generate_config_from_analysis,
    save_dynamic_config,
    load_dynamic_config,
    validate_selectors
)
from .crawl4ai_discovery import (
    Crawl4AIDiscovery,
    get_crawl4ai_discovery,
    find_dealer_locator_sync,
    CRAWL4AI_AVAILABLE
)

__all__ = [
    'extract_phone',
    'parse_address',
    'extract_website_url',
    'clean_name',
    'extract_distance',
    'get_jina_reader',
    'JinaReader',
    'get_llm_analyzer',
    'LLMAnalyzer',
    'generate_config_from_analysis',
    'save_dynamic_config',
    'load_dynamic_config',
    'validate_selectors',
    'Crawl4AIDiscovery',
    'get_crawl4ai_discovery',
    'find_dealer_locator_sync',
    'CRAWL4AI_AVAILABLE',
]
