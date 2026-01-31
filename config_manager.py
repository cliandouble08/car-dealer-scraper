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


class ConfigManager:
    """Manages configuration loading and merging for dealer scrapers."""

    def __init__(self, config_dir: str = "configs"):
        """
        Initialize the configuration manager.

        Args:
            config_dir: Directory containing configuration files
        """
        self.config_dir = Path(config_dir)
        self._base_config: Optional[Dict[str, Any]] = None
        self._manufacturer_configs: Dict[str, Dict[str, Any]] = {}

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

        # Load manufacturer-specific config if exists
        if manufacturer not in self._manufacturer_configs:
            manufacturer_config_path = self.config_dir / f"{manufacturer.lower()}.yaml"
            if manufacturer_config_path.exists():
                self._manufacturer_configs[manufacturer] = self._load_yaml(
                    manufacturer_config_path
                )
            else:
                self._manufacturer_configs[manufacturer] = {}

        manufacturer_config = self._manufacturer_configs[manufacturer]

        # Merge configurations (manufacturer config overrides base)
        config = self._deep_merge(config, manufacturer_config)

        return config

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
