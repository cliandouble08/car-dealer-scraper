# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a generalized web scraping system for extracting car dealership information from any dealer locator website. The scraper uses:
1. **Crawl4AI**: Discovers and extracts all URLs from a website to find the dealer locator page
2. **Jina Reader**: Converts web pages to LLM-friendly text and captures screenshots
3. **Local LLM (Ollama/Llama)**: Analyzes page structure to identify selectors and interaction patterns
4. **Playwright**: Browser automation for scraping with the LLM-identified patterns

## Core Architecture

### Main Components

**scrape_dealers.py** - Main scraper implementation
- `GenericDealerScraper`: Works with any dealer locator URL
- `scrape_website()`: Async function to scrape a single website
- `scrape_parallel()`: Parallel execution with multiple workers
- Uses Playwright for browser automation (async)

**config_manager.py** - Configuration management
- Supports both brand names (e.g., 'ford') and domains (e.g., 'ford.com')
- Loads configs with priority: manual YAML > LLM-generated > base config
- `ConfigManager.get_config()`: Merges configs using deep merge strategy

**utils/** - Utility modules
- `crawl4ai_discovery.py`: URL discovery using Crawl4AI to find dealer locator pages
- `jina_reader.py`: Fetches LLM-friendly content and screenshots via Jina Reader API
- `llm_analyzer.py`: LLM-based page structure analysis using Ollama
- `dynamic_config.py`: Config generation from LLM analysis results
- `extraction.py`: Text extraction (phone, address, website, distance)

### Configuration System

Configurations are YAML-based with three layers:
1. `configs/base_config.yaml` - Default selectors and patterns
2. `configs/llm_generated/{domain}_llm.yaml` - Auto-generated from AI analysis
3. `configs/{domain}.yaml` - Manual overrides (highest priority)

Each config contains:
- `selectors`: CSS selectors for page elements (search inputs, dealer cards, buttons)
- `data_fields`: Selectors for extracting specific dealer info (name, address, phone, website)
- `interactions`: Timing parameters and behavior (search_sequence, pagination_type)
- `extraction`: Regex patterns for extracting data from text

### Workflow

```
1. Load websites from websites.txt
2. For each website:
   a. Fetch page with Jina Reader for initial content
   b. Use Crawl4AI to discover all URLs on the page
   c. Ask LLM to identify which URL is the dealer locator page
   d. If not already on locator page, redirect to the discovered URL
   e. Analyze page structure with LLM to identify selectors
   f. Cache generated config
   g. For each zip code:
      - Navigate to page with Playwright
      - Fill search input with zip code
      - Click search/press Enter
      - Expand results (View More / scroll)
      - Extract dealer info from cards
   h. Save results to output/
3. Move to next website
```

## Common Commands

### Install Dependencies
```bash
pip install -r requirements.txt
playwright install chromium
crawl4ai-setup  # Set up Crawl4AI browser
```

### Scraping

```bash
# Basic usage - scrape websites in websites.txt
python scrape_dealers.py --websites websites.txt --zip-file test_zip_codes.txt

# With visible browser (for debugging)
python scrape_dealers.py --websites websites.txt --zip-codes "10001" --no-headless

# Parallel execution (4 workers per website)
python scrape_dealers.py --websites websites.txt --zip-file centroid_zip_codes.txt --workers 4

# Disable AI (use default selectors only)
python scrape_dealers.py --websites websites.txt --zip-codes "10001" --disable-ai
```

### Generate Zip Code Coverage
```bash
python generate_centroid_zips.py
python generate_centroid_zips.py --radius 75 --output custom_zips.txt
```

### AI Setup (Required for LLM analysis)
```bash
# Install and start Ollama
curl -fsSL https://ollama.ai/install.sh | sh
ollama pull llama3
ollama serve
```

### List Websites
```bash
python scrape_dealers.py --websites websites.txt --list-websites
```

## Website List Format

Create a `websites.txt` file with one URL per line:

```text
# Comments start with #
https://www.ford.com/dealerships/
https://www.toyota.com/dealers/
# https://www.honda.com/find-a-dealer  # Commented out
```

## Key Implementation Details

### GenericDealerScraper

The scraper works with any dealer locator URL:
1. Analyzes the page structure using LLM
2. Identifies search inputs, buttons, and dealer cards
3. Extracts data_fields (name, address, phone, website) from each card
4. Handles pagination via View More buttons or scrolling

### Jina Reader Integration

- `save_analysis_artifacts()`: Fetches and saves both screenshot and text
- Files saved to `data/analysis/{domain}/` with timestamps
- Used for troubleshooting and LLM analysis

### LLM Analysis

The LLM prompt asks for:
- `selectors`: CSS selectors for page elements
- `data_fields`: How to extract dealer info from cards
- `interactions`: Search sequence and pagination type
- `input_fields`: Zip code and radius inputs

### Playwright vs Selenium

The project uses Playwright because:
- Better async support
- Built-in auto-waiting
- More reliable for dynamic content
- Simpler selector syntax (`:has-text()`, etc.)

### Parallel Execution

Uses `ProcessPoolExecutor` to run multiple async scrapers:
- Each worker handles a subset of zip codes
- Workers are staggered to avoid resource contention
- Deduplication happens after workers complete

## Adding a New Website

Simply add the URL to `websites.txt`:

```text
https://www.newbrand.com/dealer-locator/
```

The scraper will automatically:
1. Analyze the page with LLM
2. Generate and cache a config
3. Scrape using the identified patterns

### Manual Configuration Override

If LLM analysis isn't accurate, create `configs/{domain}.yaml`:

```yaml
site: newbrand.com
base_url: https://www.newbrand.com/dealer-locator/
selectors:
  search_input:
    - "#dealer-zip-input"
  dealer_cards:
    - ".dealer-result-card"
data_fields:
  name:
    selector: ".dealer-name h3"
    type: text
  phone:
    selector: "a.phone-link"
    type: href
    attribute: href
interactions:
  pagination_type: scroll
  wait_after_search: 5
```

## Output Format

Results are saved to `output/` directory:
- `{domain}_dealers_{timestamp}.csv` - For Excel/spreadsheets
- `{domain}_dealers_{timestamp}.json` - For programmatic use

Each dealer record includes:
- `source_url`, `name`, `address`, `city`, `state`, `zip_code`
- `phone`, `website`, `dealer_type` (e.g., "Elite", "Certified")
- `distance_miles`, `search_zip`, `scrape_date`

## Debug Artifacts

Analysis artifacts are saved to `data/analysis/{domain}/`:
- `{timestamp}_screenshot.png` - Page screenshot
- `{timestamp}_content.txt` - LLM-friendly text content

## Environment Variables

```bash
export LLM_ENDPOINT="http://localhost:11434/api/generate"  # Ollama endpoint
export LLM_MODEL="llama3"  # Model name
export LLM_TIMEOUT="120"  # Timeout in seconds
export JINA_READER_ENABLED="true"  # Enable/disable Jina Reader
export LLM_ANALYSIS_ENABLED="true"  # Enable/disable LLM analysis
```

## Troubleshooting

### Playwright Not Installed
```bash
pip install playwright
playwright install chromium
```

### LLM Connection Error
```bash
# Make sure Ollama is running
ollama serve
```

### No Dealers Found
1. Run with `--no-headless` to see the browser
2. Check `data/analysis/{domain}/` for screenshot and text
3. Verify the LLM-generated config in `configs/llm_generated/`
4. Create a manual override in `configs/{domain}.yaml`

### Low Confidence LLM Results
The config is still saved but may need manual refinement:
1. Check `configs/llm_generated/{domain}_llm.yaml`
2. Create a manual override with corrected selectors
