#!/usr/bin/env python3
"""
Configuration Manager for Dealer Scrapers

Loads and manages manufacturer-specific configurations for dealer scraping.
Supports YAML configuration files with fallback to base defaults.
"""

import os
import yaml
from typing import Dict, Optional, Any
from pathlib import Path

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
        self._manufacturer_configs: Dict[str, Dict[str, Any]] = {}
        self._llm_configs: Dict[str, Dict[str, Any]] = {}  # Memory cache for LLM configs

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

    def get_config(self, manufacturer: str) -> Dict[str, Any]:
        """
        Get merged configuration for a manufacturer.

        Args:
            manufacturer: Manufacturer name (e.g., 'ford', 'toyota')

        Returns:
            Merged configuration dictionary
        """
        # Load base config
        config = self._get_base_config()

        # Load LLM-generated config first (highest priority)
        llm_config = self._load_llm_generated_config(manufacturer)
        if llm_config:
            config = self._deep_merge(config, llm_config)

        # Load manufacturer-specific manual config (overrides LLM if exists)
        if manufacturer not in self._manufacturer_configs:
            manufacturer_config_path = self.config_dir / f"{manufacturer.lower()}.yaml"
            if manufacturer_config_path.exists():
                self._manufacturer_configs[manufacturer] = self._load_yaml(
                    manufacturer_config_path
                )
            else:
                self._manufacturer_configs[manufacturer] = {}

        manufacturer_config = self._manufacturer_configs[manufacturer]

        # Merge configurations (manual config overrides LLM, which overrides base)
        config = self._deep_merge(config, manufacturer_config)

        return config

    def _load_llm_generated_config(self, manufacturer: str) -> Optional[Dict[str, Any]]:
        """
        Load LLM-generated config from cache (memory or file).

        Args:
            manufacturer: Manufacturer name

        Returns:
            LLM config dictionary or None if not found
        """
        # Check memory cache first
        if manufacturer in self._llm_configs:
            return self._llm_configs[manufacturer]

        # Load from file cache
        llm_config = load_dynamic_config(manufacturer, self.llm_cache_dir)
        if llm_config:
            # Store in memory cache
            self._llm_configs[manufacturer] = llm_config
            return llm_config

        return None

    def get_llm_config(self, brand: str, url: str) -> Optional[Dict[str, Any]]:
        """
        Get LLM-generated config, checking cache first.

        Args:
            brand: Manufacturer brand name
            url: Manufacturer website URL

        Returns:
            LLM config dictionary or None if not available
        """
        return self._load_llm_generated_config(brand.lower())

    def cache_llm_config(self, config: Dict[str, Any], brand: str) -> Optional[Path]:
        """
        Cache LLM-generated config (both memory and file).

        Args:
            config: Configuration dictionary
            brand: Manufacturer brand name

        Returns:
            Path to saved config file or None if failed
        """
        brand_lower = brand.lower()

        # Store in memory cache
        self._llm_configs[brand_lower] = config

        # Save to file cache
        file_path = save_dynamic_config(config, brand_lower, self.llm_cache_dir)
        return file_path

    def has_llm_config(self, manufacturer: str) -> bool:
        """
        Check if LLM-generated config exists for manufacturer.

        Args:
            manufacturer: Manufacturer name

        Returns:
            True if LLM config exists
        """
        # Check memory cache
        if manufacturer.lower() in self._llm_configs:
            return True

        # Check file cache
        from utils.dynamic_config import load_dynamic_config
        config = load_dynamic_config(manufacturer.lower(), self.llm_cache_dir)
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

    def get_selector(self, manufacturer: str, selector_type: str) -> list:
        """
        Get selectors for a specific type (e.g., 'search_input', 'dealer_cards').

        Args:
            manufacturer: Manufacturer name
            selector_type: Type of selector to retrieve

        Returns:
            List of CSS selectors
        """
        config = self.get_config(manufacturer)
        selectors = config.get('selectors', {})
        return selectors.get(selector_type, [])

    def get_interaction_config(self, manufacturer: str) -> Dict[str, Any]:
        """Get interaction configuration (delays, timeouts, etc.)."""
        config = self.get_config(manufacturer)
        return config.get('interactions', {})

    def get_extraction_config(self, manufacturer: str) -> Dict[str, Any]:
        """Get extraction patterns configuration."""
        config = self.get_config(manufacturer)
        return config.get('extraction', {})


# Global config manager instance
_config_manager: Optional[ConfigManager] = None


def get_config_manager(config_dir: str = "configs") -> ConfigManager:
    """Get or create the global configuration manager instance."""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager(config_dir)
    return _config_manager
