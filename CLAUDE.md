# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a generalized web scraping system for extracting car dealership information from any dealer locator website. The scraper uses:
1. **Crawl4AI**: Unified browser automation for URL discovery, form submission, and data extraction
2. **LLM Form Discovery**: Real-time intelligent form field identification using Crawl4AI's LLMExtractionStrategy
3. **Jina Reader**: Converts web pages to LLM-friendly text and captures screenshots
4. **Local LLM (Ollama/Gemma)**: Analyzes page structure and dynamically discovers form elements
5. **Post-Search Validation**: Validates and refines selectors based on actual search results
6. **Iframe Support**: Automatic detection and processing of embedded iframe content

## Core Architecture

### Main Components

**scrape_dealers.py** - Main scraper implementation
- `GenericDealerScraper`: Works with any dealer locator URL
- `scrape_website()`: Async function to scrape a single website
- `scrape_parallel()`: Parallel execution with multiple workers
- Uses Crawl4AI for all browser automation (async)

**config_manager.py** - Configuration management
- Supports both brand names (e.g., 'ford') and domains (e.g., 'ford.com')
- Loads configs with priority: manual YAML > LLM-generated > base config
- `ConfigManager.get_config()`: Merges configs using deep merge strategy

**utils/** - Utility modules
- `crawl4ai_scraper.py`: Crawl4AI-based browser automation for form submission and scraping
- `post_search_validator.py`: Post-search validation and selector refinement
- `firecrawl_discovery.py`: Crawl4AI-based URL discovery for dealer locator pages
- `jina_reader.py`: Fetches LLM-friendly content and screenshots via Jina Reader API
- `llm_analyzer.py`: LLM-based page structure analysis (generates Crawl4AI JavaScript templates)
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
- `crawl4ai_interactions`: JavaScript code templates for Crawl4AI browser automation
- `post_search_validation`: Validation settings (always enabled for accuracy)
- `discovery`: Crawl4AI-based URL discovery settings
- `extraction`: Regex patterns for extracting data from text

### Workflow

```
1. Load websites from websites.txt
2. For each website:
   a. Discovery: Use Crawl4AI to find dealer locator URL (cached 30 days)
   b. Pre-Search Analysis:
      - Fetch page with Jina Reader
      - Save screenshot and text to data/analysis/{domain}/
      - Analyze with LLM to generate Crawl4AI config (JavaScript templates)
      - Cache generated config
   c. For each zip code:
      - Use Crawl4AI to fill form and submit search
      - Post-search validation (once per domain):
         * Verify dealer cards appeared
         * Refine selectors if needed using LLM
      - Crawl4AI expands results (Load More / virtual scroll)
      - Extract dealer info from HTML with BeautifulSoup
   d. Save results to output/
3. Move to next website
```

## Common Commands

### Install Dependencies
```bash
pip install -r requirements.txt
# Note: Crawl4AI handles browser installation automatically
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
ollama pull gemma2:2b
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
- `crawl4ai_interactions`: JavaScript code templates for browser automation
- `input_fields`: Zip code and radius inputs

### Crawl4AI-Based Automation

The project uses Crawl4AI for all browser automation:
- **URL Discovery**: Crawls manufacturer homepages to find dealer locator URLs
- **Form Submission**: Executes LLM-generated JavaScript to fill forms and submit searches
- **Result Expansion**: Handles "Load More" buttons and infinite scroll automatically
- **Virtual Scrolling**: Twitter-style infinite scroll support
- **HTML Extraction**: Returns full HTML for BeautifulSoup parsing

### Post-Search Validation

Runs once per domain to improve accuracy:
- Verifies dealer cards appeared after search submission
- Uses heuristics to find alternative selectors if expected ones fail
- Falls back to LLM refinement for low-confidence results
- Updates config automatically for subsequent zip codes

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

### Crawl4AI Not Installed
```bash
pip install crawl4ai
# Crawl4AI handles browser installation automatically
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
