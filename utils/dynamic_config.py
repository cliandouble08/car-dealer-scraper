#!/usr/bin/env python3
"""
Dynamic Config Generator

Generates YAML configuration files from LLM analysis results.
Validates and saves configurations for use by the scraper.
"""

import os
import yaml
from datetime import datetime
from typing import Dict, Any, Optional
from pathlib import Path


def generate_config_from_analysis(
    analysis_result: Dict[str, Any],
    brand: str,
    url: str
) -> Dict[str, Any]:
    """
    Generate YAML-compatible config from LLM analysis result.

    Args:
        analysis_result: LLM analysis output
        brand: Manufacturer brand name
        url: Source URL

    Returns:
        Configuration dictionary ready for YAML serialization
    """
    config = {
        'manufacturer': brand.capitalize(),
        'base_url': url,
        'generated_by': 'llm_analyzer',
        'generated_date': datetime.now().isoformat(),
        'confidence': analysis_result.get('confidence', 0.5),
        'notes': analysis_result.get('notes', ''),
        'selectors': {},
        'interactions': {},
        'extraction': {}
    }

    # Process selectors
    selectors = analysis_result.get('selectors', {})
    for selector_type, selector_list in selectors.items():
        if isinstance(selector_list, list) and selector_list:
            # Validate and filter selectors
            validated = [s for s in selector_list if _is_valid_selector(s)]
            if validated:
                config['selectors'][selector_type] = validated

    # Process interactions
    interactions = analysis_result.get('interactions', {})
    if isinstance(interactions, dict):
        config['interactions'] = {
            k: v for k, v in interactions.items()
            if isinstance(v, (int, float)) and v >= 0
        }

    # Process extraction patterns
    extraction = analysis_result.get('extraction', {})
    if isinstance(extraction, dict):
        config['extraction'] = {
            k: v for k, v in extraction.items()
            if isinstance(v, list) and v
        }

    return config


def _is_valid_selector(selector: str) -> bool:
    """
    Basic validation of CSS selector.

    Args:
        selector: CSS selector string

    Returns:
        True if selector appears valid
    """
    if not selector or not isinstance(selector, str):
        return False

    # Basic checks - not comprehensive but catches obvious issues
    if len(selector) < 2:
        return False

    # Allow common patterns even if not perfect CSS
    # (some selectors might be XPath-like or have :contains())
    return True


def save_dynamic_config(
    config: Dict[str, Any],
    brand: str,
    cache_dir: str = "configs/llm_generated"
) -> Optional[Path]:
    """
    Save dynamically generated config to cache directory.

    Args:
        config: Configuration dictionary
        brand: Manufacturer brand name
        cache_dir: Cache directory path

    Returns:
        Path to saved config file or None if failed
    """
    try:
        cache_path = Path(cache_dir)
        cache_path.mkdir(parents=True, exist_ok=True)

        filename = f"{brand.lower()}_llm.yaml"
        file_path = cache_path / filename

        with open(file_path, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

        print(f"Saved LLM-generated config to: {file_path}")
        return file_path

    except Exception as e:
        print(f"Error saving dynamic config: {e}")
        return None


def load_dynamic_config(
    brand: str,
    cache_dir: str = "configs/llm_generated"
) -> Optional[Dict[str, Any]]:
    """
    Load dynamically generated config from cache.

    Args:
        brand: Manufacturer brand name
        cache_dir: Cache directory path

    Returns:
        Configuration dictionary or None if not found
    """
    try:
        cache_path = Path(cache_dir)
        filename = f"{brand.lower()}_llm.yaml"
        file_path = cache_path / filename

        if not file_path.exists():
            return None

        with open(file_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        return config

    except Exception as e:
        print(f"Error loading dynamic config: {e}")
        return None


def validate_selectors(selectors: Dict[str, list]) -> Dict[str, list]:
    """
    Validate and clean selector lists.

    Args:
        selectors: Dictionary of selector types to lists

    Returns:
        Validated selectors dictionary
    """
    validated = {}
    for selector_type, selector_list in selectors.items():
        if isinstance(selector_list, list):
            validated[selector_type] = [
                s for s in selector_list
                if _is_valid_selector(s)
            ]
    return validated
