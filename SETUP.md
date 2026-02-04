# Setup Guide for Dealer Scraper

## Quick Start

### 1. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 2. Install and Configure Ollama (Local LLM)

```bash
# Install Ollama (macOS/Linux)
curl -fsSL https://ollama.ai/install.sh | sh

# Pull the model
ollama pull gemma2:2b

# Start Ollama server (in a separate terminal)
ollama serve
```

### 3. Configure Environment (Optional)

```bash
# Copy environment template
cp .env.template .env

# Edit .env with your preferred settings (optional, defaults work fine)
nano .env
```

### 4. Run the Scraper

```bash
# Basic usage - scrape one website for specific zip codes
python scrape_dealers.py --websites websites.txt --zip-codes "10001,90210"

# Scrape with zip code file
python scrape_dealers.py --websites websites.txt --zip-file test_zip_codes.txt

# Parallel execution (4 workers per website)
python scrape_dealers.py --websites websites.txt --zip-file centroid_zip_codes.txt --workers 4

# With visible browser (for debugging)
python scrape_dealers.py --websites websites.txt --zip-codes "10001" --no-headless
```

## Architecture

This scraper uses **Crawl4AI** for all browser automation:
- URL discovery: Crawl4AI crawls manufacturer homepages to find dealer locator URLs
- Form automation: Crawl4AI fills search forms and submits searches
- Result expansion: Crawl4AI handles "Load More" buttons and infinite scroll
- Data extraction: BeautifulSoup parses HTML to extract dealer information

**LLM** (Ollama/Gemma) analyzes page structure to generate:
- CSS selectors for dealer cards and form elements
- JavaScript code templates for Crawl4AI interactions
- Data field extraction patterns

**Post-search validation** runs once per domain to:
- Verify dealer cards appeared after search
- Refine selectors if initial analysis was incorrect
- Improve accuracy with LLM feedback

## Configuration Hierarchy

Configurations are loaded with this priority (highest to lowest):
1. `configs/{domain}.yaml` - Manual overrides (highest priority)
2. `configs/llm_generated/{domain}_llm.yaml` - AI-generated (cached)
3. `configs/base_config.yaml` - Default fallback

## Troubleshooting

### Ollama Connection Error

```bash
# Make sure Ollama is running
ollama serve

# Test connection
curl http://localhost:11434/api/generate \
  -d '{"model": "gemma2:2b", "prompt": "Hello", "stream": false}'
```

### No Dealers Found

1. Run with `--no-headless` to see the browser
2. Check analysis artifacts in `data/analysis/{domain}/`:
   - `{timestamp}_screenshot.png` - Page screenshot
   - `{timestamp}_content.txt` - LLM-friendly text content
3. Verify the LLM-generated config in `configs/llm_generated/{domain}_llm.yaml`
4. Create a manual override in `configs/{domain}.yaml` if needed

### Low Confidence LLM Results

The config is still saved but may need manual refinement:
1. Check `configs/llm_generated/{domain}_llm.yaml`
2. Identify incorrect selectors
3. Create a manual override with corrected selectors in `configs/{domain}.yaml`

## Output Files

Results are saved to `output/` directory:
- `{domain}_dealers_{timestamp}.csv` - For Excel/spreadsheets
- `{domain}_dealers_{timestamp}.json` - For programmatic use

Each dealer record includes:
- `source_url`, `name`, `address`, `city`, `state`, `zip_code`
- `phone`, `website`, `dealer_type`
- `distance_miles`, `search_zip`, `scrape_date`

## Advanced Usage

### Generate Centroid Zip Codes

```bash
# Generate nationwide coverage
python generate_centroid_zips.py

# Custom radius
python generate_centroid_zips.py --radius 75 --output custom_zips.txt
```

### List Websites

```bash
python scrape_dealers.py --websites websites.txt --list-websites
```

### Disable AI (Use Default Selectors Only)

```bash
python scrape_dealers.py --websites websites.txt --zip-codes "10001" --disable-ai
```

## System Requirements

- Python 3.8+
- 4GB RAM minimum (8GB+ recommended for parallel execution)
- Ollama with gemma2:2b model (~1.5GB disk space)
- Internet connection for scraping and Jina Reader API

## Notes

- Discovery results are cached for 30 days to avoid redundant crawling
- Post-search validation runs once per domain (cached for the session)
- Crawl4AI handles browser automation internally (no manual browser management needed)
- All temporary files go to session-specific scratchpad directory
