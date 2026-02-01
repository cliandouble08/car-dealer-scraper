# Dealer Scraping Guide

This guide shows you how to run the dealer scraper for testing and full production runs.

## Prerequisites

First, install the required dependencies:

```bash
pip install -r requirements.txt
```

Or if using Python 3 specifically:

```bash
pip3 install -r requirements.txt
```

## Test Run (Small Subset)

Start with a small test to verify everything works. Use the `test_zip_codes.txt` file which contains 7 zip codes from major cities:

```bash
# Test with a few zip codes (headless mode - no browser window)
python scrape_dealers.py --brand ford --zip-file test_zip_codes.txt --headless

# Or test with visible browser window (useful for debugging)
python scrape_dealers.py --brand ford --zip-file test_zip_codes.txt --no-headless

# Test with just a couple zip codes directly
python scrape_dealers.py --brand ford --zip-codes "10001,02134,33101"
```

**Expected output:**
- The script will open a browser (or run headless)
- Search for dealers near each zip code
- Extract dealer information (name, address, phone, website)
- Save results to `output/ford_dealers_TIMESTAMP.csv` and `.json`

## Full Production Run

Once testing is successful, run with the full centroid zip code list (1062 zip codes):

```bash
# Full run with single worker (sequential)
python scrape_dealers.py --brand ford --zip-file centroid_zip_codes.txt --headless

# Full run with 4 parallel workers (recommended for speed)
python scrape_dealers.py --brand ford --zip-file centroid_zip_codes.txt --headless --workers 4

# Full run with 8 parallel workers (faster, but uses more resources)
python scrape_dealers.py --brand ford --zip-file centroid_zip_codes.txt --headless --workers 8
```

**Note:** The full run with 1062 zip codes will take several hours. With 4 workers, expect approximately:
- ~1062 zip codes / 4 workers = ~266 zip codes per worker
- ~2-5 seconds per zip code = ~9-22 minutes per worker
- Total time: ~9-22 minutes (depending on network speed and website response times)

## Command Options

```text
--brand          Brand to scrape (ford, toyota, etc.) - default: ford
--zip-codes      Comma-separated zip codes (e.g., "10001,02134")
--zip-file       File with zip codes (one per line)
--output-dir     Output directory (default: output)
--headless       Run browser in headless mode (default: True)
--no-headless    Run browser with visible window
--workers, -w    Number of parallel browser instances (default: 1)
--list-brands    List available brands
--enable-ai      Enable AI features (Jina Reader and LLM analysis) (default: enabled)
--disable-ai     Disable AI features, use basic auto-detection only
```

## AI Features (Jina Reader & LLM Analysis)

The scraper includes intelligent AI-powered features that automatically adapt to different manufacturer websites:

### What It Does

- **Jina Reader**: Converts manufacturer websites into LLM-friendly content
- **LLM Analysis**: Uses local LLM (Ollama) to analyze page structure and extract CSS selectors
- **Automatic Adaptation**: No manual configuration needed for new manufacturers
- **Intelligent Caching**: LLM-generated configs are cached for future use

### Default Behavior

By default, AI features are **enabled**. The scraper will:
1. Check for cached LLM-generated configs
2. If not found, use Jina Reader to fetch page content
3. Analyze with LLM to extract selectors and patterns
4. Cache the results for future runs

### Disabling AI Features

To use basic auto-detection only (no Jina Reader, no LLM analysis):

```bash
# Disable AI features - uses only basic auto-detection patterns
python scrape_dealers.py --brand ford --zip-file test_zip_codes.txt --disable-ai
```

When disabled, the scraper uses:
- Manual configs (if exist in `configs/{brand}.yaml`)
- Base config patterns (`configs/base_config.yaml`)
- Auto-detection fallbacks

### When to Disable AI Features

Disable AI features if:
- You want faster scraping without LLM analysis overhead
- You don't have Ollama installed or running
- You prefer manual configuration
- You're experiencing issues with Jina Reader API

### Setting Up AI Features (Optional)

If you want to use AI features, you'll need:

1. **Ollama** (for LLM analysis):
   ```bash
   # Install Ollama
   curl -fsSL https://ollama.ai/install.sh | sh
   
   # Pull a model
   ollama pull llama3
   
   # Start Ollama server
   ollama serve
   ```

2. **Internet connection** (for Jina Reader API)

See `LLM_FEATURES.md` for detailed setup instructions.

## Examples

### Example 1: Quick test with 3 zip codes
```bash
python scrape_dealers.py --brand ford --zip-codes "10001,02134,33101" --no-headless
```

### Example 2: Test with sample zip codes file
```bash
python scrape_dealers.py --brand ford --zip-file sample_zip_codes.txt --headless
```

### Example 3: Full production run with parallel workers
```bash
python scrape_dealers.py --brand ford --zip-file centroid_zip_codes.txt --headless --workers 4
```

### Example 4: Check available brands
```bash
python scrape_dealers.py --list-brands
```

### Example 5: Run with AI features disabled (basic auto-detection)
```bash
python scrape_dealers.py --brand ford --zip-file test_zip_codes.txt --disable-ai
```

## Output Files

Results are saved in the `output/` directory with timestamps:

- `ford_dealers_YYYYMMDD_HHMMSS.csv` - CSV format for Excel/spreadsheets
- `ford_dealers_YYYYMMDD_HHMMSS.json` - JSON format for programmatic use

Each dealer record includes:
- brand
- name
- address, city, state, zip_code
- phone
- website
- dealer_type
- distance_miles
- search_zip (the zip code used to find this dealer)
- scrape_date

## Troubleshooting

### Browser/Driver Issues
If you see ChromeDriver errors, the script will automatically download the correct driver via `webdriver-manager`. Make sure you have Chrome browser installed.

### Network Issues
If scraping fails for certain zip codes, the script will continue with the next zip code. Check the console output for error messages.

### Memory Issues
If running with many workers (8+), you may run into memory issues. Reduce the number of workers or run sequentially.

### Rate Limiting
The script includes delays between requests to be respectful. If you encounter rate limiting, you can increase delays in the config files.
