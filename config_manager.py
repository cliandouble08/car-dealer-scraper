#!/usr/bin/env python3
"""
Configuration Manager for Dealer Scrapers

Loads and manages site-specific configurations for dealer scraping.
Supports both brand names (e.g., 'ford') and domain names (e.g., 'ford.com').
YAML configuration files with fallback to base defaults.
"""

import os
import re
import yaml
import json
from typing import Dict, Optional, Any
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime

from utils.dynamic_config import load_dynamic_config, save_dynamic_config


class ConfigManager:
    """Manages configuration loading and merging for dealer scrapers."""

    def __init__(self, config_dir: str = "configs", llm_cache_dir: str = "configs/llm_generated"):
        """
        Initialize the configuration manager.

        Args:
            config_dir: Directory containing configuration files
            llm_cache_dir: Directory for LLM-generated configs
        """
        self.config_dir = Path(config_dir)
        self.llm_cache_dir = llm_cache_dir
        self._base_config: Optional[Dict[str, Any]] = None
        self._site_configs: Dict[str, Dict[str, Any]] = {}  # Renamed from _manufacturer_configs
        self._llm_configs: Dict[str, Dict[str, Any]] = {}  # Memory cache for LLM configs

    @staticmethod
    def _normalize_key(key: str) -> str:
        """
        Normalize a key (brand name or domain) for consistent lookup.

        Args:
            key: Brand name (e.g., 'Ford') or domain (e.g., 'www.ford.com')

        Returns:
            Normalized key (lowercase, without www.)
        """
        if not key:
            return ""
        # Remove www. prefix and lowercase
        normalized = key.lower().replace('www.', '')
        # Remove trailing slashes
        normalized = normalized.rstrip('/')
        return normalized

    @staticmethod
    def extract_domain(url: str) -> str:
        """
        Extract clean domain from URL.

        Args:
            url: Full URL (e.g., 'https://www.ford.com/dealerships/')

        Returns:
            Clean domain (e.g., 'ford.com')
        """
        if not url:
            return ""
        if url.startswith(('http://', 'https://')):
            parsed = urlparse(url)
            return parsed.netloc.replace('www.', '')
        return url.replace('www.', '')

    def _load_yaml(self, file_path: Path) -> Dict[str, Any]:
        """Load a YAML configuration file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        except FileNotFoundError:
            return {}
        except yaml.YAMLError as e:
            print(f"Warning: Error loading config {file_path}: {e}")
            return {}

    def _get_base_config(self) -> Dict[str, Any]:
        """Load base configuration with default patterns."""
        if self._base_config is None:
            base_config_path = self.config_dir / "base_config.yaml"
            self._base_config = self._load_yaml(base_config_path)
        return self._base_config.copy()

    def get_config(self, site_key: str) -> Dict[str, Any]:
        """
        Get merged configuration for a site.

        Args:
            site_key: Site identifier - can be:
                - Brand name (e.g., 'ford', 'toyota')
                - Domain (e.g., 'ford.com', 'toyota.com')
                - Full URL (e.g., 'https://www.ford.com/dealerships/')

        Returns:
            Merged configuration dictionary
        """
        # Normalize the key
        normalized_key = self._normalize_key(site_key)

        # Load base config
        config = self._get_base_config()

        # If empty key, just return base config
        if not normalized_key:
            return config

        # Load LLM-generated config (from domain-based cache)
        llm_config = self._load_llm_generated_config(normalized_key)
        if llm_config:
            config = self._deep_merge(config, llm_config)

        # Load site-specific manual config (overrides LLM if exists)
        if normalized_key not in self._site_configs:
            # Try both as-is and with common variations
            config_names = [
                f"{normalized_key}.yaml",
                f"{normalized_key.replace('.', '_')}.yaml",
                # Also try just the brand part (e.g., 'ford' from 'ford.com')
                f"{normalized_key.split('.')[0]}.yaml" if '.' in normalized_key else None
            ]
            config_names = [n for n in config_names if n]

            site_config = {}
            for config_name in config_names:
                config_path = self.config_dir / config_name
                if config_path.exists():
                    site_config = self._load_yaml(config_path)
                    break

            self._site_configs[normalized_key] = site_config

        site_config = self._site_configs[normalized_key]

        # Merge configurations (manual config overrides LLM, which overrides base)
        config = self._deep_merge(config, site_config)

        return config

    def _load_llm_generated_config(self, site_key: str) -> Optional[Dict[str, Any]]:
        """
        Load LLM-generated config from cache (memory or file).

        Args:
            site_key: Normalized site key (domain or brand)

        Returns:
            LLM config dictionary or None if not found
        """
        normalized = self._normalize_key(site_key)

        # Check memory cache first
        if normalized in self._llm_configs:
            return self._llm_configs[normalized]

        # Load from file cache
        llm_config = load_dynamic_config(normalized, self.llm_cache_dir)
        if llm_config:
            # Store in memory cache
            self._llm_configs[normalized] = llm_config
            return llm_config

        return None

    def get_llm_config(self, site_key: str, url: str = "") -> Optional[Dict[str, Any]]:
        """
        Get LLM-generated config, checking cache first.

        Args:
            site_key: Site identifier (brand name, domain, or URL)
            url: Optional URL (for backwards compatibility)

        Returns:
            LLM config dictionary or None if not available
        """
        normalized = self._normalize_key(site_key)
        return self._load_llm_generated_config(normalized)

    def cache_llm_config(self, config: Dict[str, Any], site_key: str) -> Optional[Path]:
        """
        Cache LLM-generated config (both memory and file).

        Args:
            config: Configuration dictionary
            site_key: Site identifier (brand name or domain)

        Returns:
            Path to saved config file or None if failed
        """
        normalized = self._normalize_key(site_key)

        # Store in memory cache
        self._llm_configs[normalized] = config

        # Save to file cache
        file_path = save_dynamic_config(config, normalized, self.llm_cache_dir)
        return file_path

    def has_llm_config(self, site_key: str) -> bool:
        """
        Check if LLM-generated config exists for a site.

        Args:
            site_key: Site identifier (brand name, domain, or URL)

        Returns:
            True if LLM config exists
        """
        normalized = self._normalize_key(site_key)

        # Check memory cache
        if normalized in self._llm_configs:
            return True

        # Check file cache
        config = load_dynamic_config(normalized, self.llm_cache_dir)
        return config is not None

    def _deep_merge(self, base: Dict, override: Dict) -> Dict:
        """Deep merge two dictionaries."""
        result = base.copy()

        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value

        return result

    def get_selector(self, site_key: str, selector_type: str) -> list:
        """
        Get selectors for a specific type (e.g., 'search_input', 'dealer_cards').

        Args:
            site_key: Site identifier (brand name, domain, or URL)
            selector_type: Type of selector to retrieve

        Returns:
            List of CSS selectors
        """
        config = self.get_config(site_key)
        selectors = config.get('selectors', {})
        return selectors.get(selector_type, [])

    def get_interaction_config(self, site_key: str) -> Dict[str, Any]:
        """Get interaction configuration (delays, timeouts, etc.)."""
        config = self.get_config(site_key)
        return config.get('interactions', {})

    def get_extraction_config(self, site_key: str) -> Dict[str, Any]:
        """Get extraction patterns configuration."""
        config = self.get_config(site_key)
        return config.get('extraction', {})

    def get_data_fields_config(self, site_key: str) -> Dict[str, Any]:
        """Get data fields configuration for extracting dealer info."""
        config = self.get_config(site_key)
        return config.get('data_fields', {})

    def get_crawl4ai_interactions_config(self, site_key: str) -> Dict[str, Any]:
        """Get Crawl4AI interactions configuration (JavaScript templates, etc.)."""
        config = self.get_config(site_key)
        return config.get('crawl4ai_interactions', {})

    def get_post_search_validation_config(self, site_key: str) -> Dict[str, Any]:
        """Get post-search validation configuration."""
        config = self.get_config(site_key)
        return config.get('post_search_validation', {})

    def get_discovery_config(self, site_key: str) -> Dict[str, Any]:
        """Get discovery configuration (Crawl4AI-based URL discovery settings)."""
        config = self.get_config(site_key)
        return config.get('discovery', {})

    # Discovery cache management methods
    def get_discovery_cache_path(self, domain: str) -> Path:
        """
        Get cache file path for discovery results.

        Args:
            domain: Domain name (e.g., 'ford.com')

        Returns:
            Path to discovery cache file
        """
        cache_dir = Path("data/discovery_cache")
        cache_dir.mkdir(parents=True, exist_ok=True)
        normalized = self._normalize_key(domain)
        return cache_dir / f"{normalized}.json"

    def get_cached_discovery(self, domain: str, ttl_days: int = 30) -> Optional[Dict]:
        """
        Load cached discovery result if still valid.

        Args:
            domain: Domain name
            ttl_days: Cache TTL in days (default: 30)

        Returns:
            Cached discovery result or None if expired/missing
        """
        cache_path = self.get_discovery_cache_path(domain)
        if not cache_path.exists():
            return None

        try:
            with open(cache_path, 'r') as f:
                data = json.load(f)

                # Check TTL
                if 'cached_at' in data:
                    cached_at = datetime.fromisoformat(data['cached_at'])
                    age = (datetime.now() - cached_at).days
                    if age < ttl_days:
                        return data
                    else:
                        print(f"Discovery cache expired for {domain} (age: {age} days)")
                        return None

                # Legacy cache without timestamp
                return data

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            print(f"Error loading discovery cache for {domain}: {e}")
            return None

    def cache_discovery_result(self, domain: str, result: Dict):
        """
        Cache discovery result to file.

        Args:
            domain: Domain name
            result: Discovery result dictionary
        """
        cache_path = self.get_discovery_cache_path(domain)
        cache_path.parent.mkdir(parents=True, exist_ok=True)

        # Add timestamp
        result['cached_at'] = datetime.now().isoformat()

        try:
            with open(cache_path, 'w') as f:
                json.dump(result, f, indent=2)
            print(f"Cached discovery result for {domain}")
        except Exception as e:
            print(f"Error caching discovery result for {domain}: {e}")


# Global config manager instance
_config_manager: Optional[ConfigManager] = None


def get_config_manager(config_dir: str = "configs") -> ConfigManager:
    """Get or create the global configuration manager instance."""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager(config_dir)
    return _config_manager
